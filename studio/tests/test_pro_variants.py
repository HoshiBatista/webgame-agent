"""Four ordinary Pro workers share one prompt and chat, never one mutable candidate."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connections
from django.test import Client

from generation.prompts import system_prompt
from generation.providers.fake import generate as fixture_generate
from studio.models import Budget, Chat, Invocation, Outbox, Revision, Run, User, VariantAnalyticsExperiment
from studio.services import DomainError, budget_snapshot, reserve_invocation
from studio.tasks import claim_run, process_run, request_for
from studio.tests.test_completion import uncertain
from studio.tests.test_staged_generation import PASS
from studio.validation_tasks import process_validation

pytestmark = pytest.mark.django_db(transaction=True)
PROMPT = 'Сделай игру про попадание в цель'


@pytest.fixture
def workspace(client, settings):
    settings.GAMEFORGE_PROVIDER = 'codex_api'
    settings.GAMEFORGE_PRO_PROVIDER = 'codex_api'
    settings.GAMEFORGE_PRO_ENABLED = True
    settings.GAMEFORGE_PRO_ACCESS = 'local'
    settings.GAMEFORGE_LOCAL_ONLY = True
    settings.GAMEFORGE_APP_ORIGIN = 'http://127.0.0.1:8000'
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 4
    settings.GAMEFORGE_PRO_VISUAL_REVIEW_ENABLED = False
    settings.GAMEFORGE_RUN_INLINE = False
    owner = User.objects.create_user(username='four-pro-owner')
    client.force_login(owner)
    with (
        patch('studio.tasks.dispatch_run'),
        patch('studio.tasks.dispatch_outbox'),
        patch('generation.providers.codex_api.available_models', return_value=[{'id': 'gpt-6.2-sol'}]),
        patch('generation.providers.codex_api.prepare', side_effect=lambda request, job: {'job_id': job}),
        patch('studio.services.tariff', return_value={'input': 0, 'cached': 0, 'output': 0}),
        patch('validation.service.environment_identity', return_value='variants-test'),
    ):
        yield Chat.objects.create(owner=owner)


def post(client, path, **payload):
    return client.post(path, payload, content_type='application/json')


def submit(client, chat, **changes):
    payload = {'prompt': PROMPT, 'model_profile': 'pro', 'idempotency_key': 'four-first', **changes}
    return post(client, f'/api/chats/{chat.pk}/variant-batches/', **payload)


def create_batch(client, chat, **changes):
    response = submit(client, chat, **changes)
    assert response.status_code == 202, response.content
    return response.json()


def detail(client, chat):
    response = client.get(f'/api/chats/{chat.pk}/')
    assert response.status_code == 200, response.content
    return response.json()


def select(client, chat, batch, revision, **changes):
    payload = {'revision_id': revision['id'], 'artifact_hash': revision['artifact_hash'],
               'expected_current_revision_id': None, **changes}
    return post(client, f"/api/chats/{chat.pk}/variant-batches/{batch['id']}/select/", **payload)


def concurrently(items, action):
    # Each thread acts like a separate worker/request on its own PostgreSQL connection.
    def execute(item):
        close_old_connections()
        try:
            return action(item)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(items)) as pool:
        return list(pool.map(execute, items))


def test_duplicate_submissions_persist_one_prompt_and_four_ordinary_jobs(workspace):
    clients = [Client() for _ in range(2)]
    for client in clients:
        client.force_login(workspace.owner)
    entering = Barrier(2)

    def same_request(client):
        entering.wait(timeout=15)
        return create_batch(client, workspace, audience='children')

    first, other = concurrently(clients, same_request)
    assert first['id'] == other['id']
    assert first['selected_revision_id'] is None
    assert [v['index'] for v in first['variants']] == [1, 2, 3, 4]
    ids = {v['run_id'] for v in first['variants']}
    assert len(ids) == 4 and ids == {v['run_id'] for v in other['variants']}
    assert Run.objects.count() == Outbox.objects.count() == len(ids)
    assert not Invocation.objects.exists()
    assert list(workspace.messages.filter(role='user').values_list('content', flat=True)) == [PROMPT]
    for run in workspace.runs.all():
        assert str(run.id) in ids
        assert (run.prompt, run.audience, run.model_profile, run.provider) == (
            PROMPT, 'children', 'pro', 'codex_api')
        assert run.model == "gpt-6.2-sol" and run.model_for("plan") == run.model
        assert run.planning_required and not run.pro_parallel

    client = clients[0]
    assert submit(client, workspace, prompt='Измени запрос').status_code == 409
    assert submit(client, workspace, idempotency_key='different').status_code == 409
    assert post(client, f'/api/chats/{workspace.pk}/runs/', prompt=PROMPT,
                model_profile='pro', idempotency_key='ordinary').status_code == 409
    assert Run.objects.count() == Outbox.objects.count() == 4


def test_four_model_requests_overlap_and_each_game_can_be_exported_and_selected(client, workspace):
    batch = create_batch(client, workspace)
    rendezvous = Barrier(4)

    def model(request, **kwargs):
        if request['operation'] == 'plan':
            rendezvous.wait(timeout=20)
        result = fixture_generate(request, **kwargs)
        if request['operation'] == 'create':
            # Four distinct games make a mistaken preview/current revision observable.
            job_id = request['codex_api']['job_id']
            number = Invocation.objects.get(pk=job_id).run.variant_index
            css = next(file for file in result['response']['files'] if file['path'] == 'styles.css')
            css['content'] += f'\nbody {{ --variant-number: {number}; }}'
        return result

    with (patch('generation.service.generate', side_effect=model),
          patch('validation.service.validate', return_value=PASS)):
        concurrently([variant['run_id'] for variant in batch['variants']], process_run)
    loaded = detail(client, workspace)
    [batch] = loaded['variant_batches']
    assert loaded['current_revision'] is None and batch['selected_revision_id'] is None
    assert workspace.revisions.count() == 4
    assert sorted(workspace.revisions.values_list('number', flat=True)) == [1, 2, 3, 4]
    assert len({r['artifact_hash'] for r in loaded['revisions']}) == 4
    ordinary_chat = Chat.objects.create(owner=workspace.owner)
    ordinary = post(client, f'/api/chats/{ordinary_chat.pk}/runs/', prompt=PROMPT, model_profile='pro',
                    idempotency_key='standard-pro')
    assert ordinary.status_code == 202
    ordinary_plan = request_for(Run.objects.get(pk=ordinary.json()['id']), None, [])
    plans = [run.invocations.get(request__operation='plan').request
             for run in workspace.runs.order_by('variant_index')]
    assert all(plan['prompt'] == plan['game_request'] == PROMPT for plan in plans)
    directions = [system_prompt(plan) for plan in plans]
    assert directions[0] == system_prompt(ordinary_plan)
    assert len(set(directions)) == 4
    for entry in batch['variants']:
        run = Run.objects.get(pk=entry['run_id'])
        assert entry['status'] == 'succeeded', run.error
        assert list(run.invocations.order_by('attempt').values_list('request__operation', flat=True)) == [
            'plan', 'create']
        revision = entry['revision']
        assert revision['accepted'] and str(run.result_revision_id) == revision['id']
        exported = client.get(revision['export_url'])
        assert hashlib.sha256(exported.content).hexdigest() == revision['artifact_hash']
        assert f"--variant-number: {entry['index']}".encode() in exported.content
        assert revision['preview_url']

    chosen = batch['variants'][2]['revision']
    assert select(client, workspace, batch, chosen, revision_id='not-a-uuid').status_code in (400, 404)
    assert select(client, workspace, batch, chosen, artifact_hash='0' * 64).status_code in (400, 409)
    selected = select(client, workspace, batch, chosen)
    assert selected.status_code == 200, selected.content
    assert selected.json()['current_revision']['id'] == chosen['id']
    assert select(client, workspace, batch, chosen).status_code == 200
    other = batch['variants'][0]['revision']
    assert select(client, workspace, batch, other).status_code == 409
    assert select(client, workspace, batch, other, expected_current_revision_id=chosen['id']).status_code == 200
    assert select(client, workspace, batch, chosen, expected_current_revision_id=other['id']).status_code == 200
    assert workspace.revisions.count() == 4 and Invocation.objects.count() == 8
    edit = post(client, f'/api/chats/{workspace.pk}/runs/', prompt='Сделай цель крупнее', idempotency_key='edit',
                model_profile='pro', source_revision_id=chosen['id'], source_artifact_hash=chosen['artifact_hash'])
    assert edit.status_code == 202, edit.content
    assert edit.json()['source_revision_id'] == edit.json()['base_revision_id'] == chosen['id']
    assert not Run.objects.get(pk=edit.json()['id']).pro_parallel


def test_early_pick_survives_cancelled_and_late_siblings_and_four_edits_use_one_source(client, workspace):
    batch = create_batch(client, workspace)
    one, two, three, four = [item['run_id'] for item in batch['variants']]
    with (patch('generation.service.generate', side_effect=fixture_generate),
          patch('validation.service.validate', return_value=PASS)):
        process_run(one)
        finished = detail(client, workspace)['variant_batches'][0]['variants'][0]
        assert finished['status'] == 'succeeded', Run.objects.get(pk=one).error
        chosen = finished['revision']
        assert select(client, workspace, batch, chosen).status_code == 200
        assert post(client, f'/api/runs/{two}/cancel/').status_code == 200
        process_run(three)
        process_run(four)

    refreshed = detail(client, workspace)
    assert refreshed['current_revision']['id'] == chosen['id']
    [group] = refreshed['variant_batches']
    assert group['selected_revision_id'] == chosen['id']
    assert [variant['status'] for variant in group['variants']] == ['succeeded', 'cancelled', 'succeeded', 'succeeded']
    wrong_source = submit(client, workspace, idempotency_key='edits', source_revision_id=chosen['id'],
                          source_artifact_hash='1' * 64)
    assert wrong_source.status_code == 409
    assert Run.objects.count() == 4
    edits = create_batch(client, workspace, prompt='Поменяй фон', idempotency_key='edits',
                         source_revision_id=chosen['id'], source_artifact_hash=chosen['artifact_hash'])
    runs = Run.objects.filter(variant_batch_id=edits['id'])
    assert runs.count() == 4 and all(str(r.base_revision_id) == str(r.source_revision_id) == chosen['id']
                                     and r.operation == 'edit' for r in runs)
    assert len({r['run_id'] for r in edits['variants']}) == 4
    variant = runs.get(variant_index=3)
    ordinary = copy(variant)
    ordinary.variant_batch_id = ordinary.variant_index = None
    for candidate_id, expected_op in ((None, 'edit'), (chosen['id'], 'repair')):
        variant.candidate_revision_id = ordinary.candidate_revision_id = candidate_id
        actual = request_for(variant, variant.source_revision, [])
        assert actual['operation'] == expected_op and 'variant_index' not in actual
        assert actual == request_for(ordinary, ordinary.source_revision, [])


def test_capacity_and_aggregate_budget_govern_the_four_runs(client, workspace, settings):
    batch = create_batch(client, workspace)
    runs = [Run.objects.get(pk=v['run_id']) for v in batch['variants']]
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 2
    assert claim_run(runs[0].id) and claim_run(runs[1].id)
    assert claim_run(runs[2].id) is False and claim_run(runs[3].id) is False
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 4
    assert claim_run(runs[2].id) and claim_run(runs[3].id)
    Budget.objects.update_or_create(pk=1, defaults={'limit_usd': Decimal('2')})
    start = Barrier(4)

    def reserve(run):
        start.wait(timeout=15)
        try:
            reserve_invocation(run, {'operation': 'plan'})
        except DomainError as exc:
            return exc.code
        return 'admitted'

    with patch('generation.service.estimate_reservation', return_value=Decimal('1')):
        outcomes = concurrently(runs, reserve)
    assert sorted(outcomes) == ['admitted', 'admitted', 'budget_exhausted', 'budget_exhausted']
    assert Invocation.objects.count() == 2 and budget_snapshot()['reserved_usd'] == 2


def test_manual_recheck_and_confirmation_only_accept_their_variant(client, workspace):
    batch = create_batch(client, workspace)
    one, two, *_ = [item['run_id'] for item in batch['variants']]
    review = {**uncertain(), 'environment': 'variants-test'}
    with patch('generation.service.generate', side_effect=fixture_generate):
        with patch('validation.service.validate', return_value=PASS):
            process_run(one)
        chosen = detail(client, workspace)['variant_batches'][0]['variants'][0]['revision']
        assert select(client, workspace, batch, chosen).status_code == 200
        with patch('validation.service.validate', return_value=review):
            process_run(two)
    second = client.get(f'/api/runs/{two}/').json()
    assert second['can_confirm'], (second['status'], second['error'])
    revision = detail(client, workspace)['variant_batches'][0]['variants'][1]['revision']
    assert not revision['accepted']
    assert select(client, workspace, batch, revision, expected_current_revision_id=chosen['id']).status_code == 404
    with (patch('studio.validation_tasks.dispatch_validation'),
          patch('validation.service.validate', return_value=review),
          patch('generation.service.generate') as model):
        recheck = post(client, f"/api/revisions/{revision['id']}/validations/",
                       idempotency_key='recheck', artifact_hash=revision['artifact_hash'])
        assert recheck.status_code == 202, recheck.content
        process_validation(recheck.json()['id'])
        confirmation = client.get(f'/api/runs/{two}/').json()['confirmation']
        assert confirmation and confirmation['report_id'] != second['confirmation']['report_id']
        accepted = post(client, f'/api/runs/{two}/confirm/', confirmed=True, **confirmation)
        assert accepted.status_code == 200, accepted.content
        model.assert_not_called()
    refreshed = detail(client, workspace)
    assert refreshed['current_revision']['id'] == refreshed['variant_batches'][0]['selected_revision_id'] == chosen['id']
    assert refreshed['variant_batches'][0]['variants'][1]['revision']['accepted']
    assert select(client, workspace, batch, revision, expected_current_revision_id=chosen['id']).status_code == 200


def test_editing_a_saved_variant_draft_preserves_acceptance_and_exact_source(client, workspace):
    batch = create_batch(client, workspace)
    first, second, third, fourth = [item['run_id'] for item in batch['variants']]
    with patch('generation.service.generate', side_effect=fixture_generate):
        with patch('validation.service.validate', return_value=uncertain()):
            process_run(first)
        with patch('validation.service.validate', return_value=PASS):
            process_run(second)
    for sibling in (third, fourth):
        assert post(client, f'/api/runs/{sibling}/cancel/').status_code == 200
    refreshed = detail(client, workspace)
    candidate = refreshed['variant_batches'][0]['variants'][0]['revision']
    assert not candidate['accepted'] and refreshed['current_revision'] is None
    payload = dict(prompt='Добавь монету', model_profile='pro', idempotency_key='edit-draft',
                   source_revision_id=candidate['id'], source_is_historical=True)
    url = f'/api/chats/{workspace.pk}/runs/'
    assert post(client, url, **payload, source_artifact_hash='1' * 64).status_code == 409
    edit = post(client, url, **payload, source_artifact_hash=candidate['artifact_hash'])
    assert edit.status_code == 202, edit.content
    assert edit.json()['source_revision_id'] == candidate['id'] and edit.json()['base_revision_id'] is None
    assert not workspace.revisions.get(pk=candidate['id']).accepted


def test_continuation_keeps_its_slot_and_respects_unknown_cost_after_another_pick(client, workspace):
    batch = create_batch(client, workspace)
    one, two, *_ = [item['run_id'] for item in batch['variants']]
    with (patch('generation.service.generate', side_effect=fixture_generate),
          patch('validation.service.validate', return_value=PASS)):
        process_run(one)
    chosen = detail(client, workspace)['variant_batches'][0]['variants'][0]['revision']
    assert select(client, workspace, batch, chosen).status_code == 200
    stopped = Run.objects.get(pk=two)
    stopped.status = 'unknown'
    stopped.save(update_fields=['status'])
    liability = Invocation.objects.create(run=stopped, state='unknown', request={}, attempt=1,
                                         reservation_usd=Decimal('1'))
    url = f'/api/runs/{two}/continue/'
    assert post(client, url, idempotency_key='retry-slot').status_code == 409
    retry = post(client, url, idempotency_key='retry-slot', accept_unknown_cost=True)
    assert retry.status_code == 202, retry.content
    retry_id = retry.json()['id']
    continuation = Run.objects.get(pk=retry_id)
    assert continuation.variant_index == stopped.variant_index
    assert continuation.variant_batch_id == stopped.variant_batch_id
    assert continuation.base_revision_id == stopped.base_revision_id
    assert liability.pk in Invocation.objects.filter(state='unknown').values_list('id', flat=True)
    assert budget_snapshot()['unknown_usd'] == 1
    assert post(client, url, idempotency_key='second-retry', accept_unknown_cost=True).status_code == 409
    assert post(client, url, idempotency_key='retry-slot', accept_unknown_cost=True).json()['id'] == retry_id
    refreshed = detail(client, workspace)
    assert refreshed['current_revision']['id'] == chosen['id']
    [group] = refreshed['variant_batches']
    assert group['variants'][1]['root_run_id'] == two
    assert group['variants'][1]['run_id'] == retry_id and len(group['variants']) == 4
    # During Django's cascade, removing the old run temporarily nulls the
    # continuation link. Its slot must not conflict with the original run.
    workspace.owner.delete()
    assert not Run.objects.exists() and not Chat.objects.exists()


def test_owner_boundary_and_explicit_pro_are_checked_before_new_work(client, workspace, settings):
    for profile in ('lite', 'pro_multi'):
        assert submit(client, workspace, model_profile=profile).status_code in (400, 409)
    assert not Run.objects.exists() and not Outbox.objects.exists()
    settings.GAMEFORGE_PRO_ACCESS = 'restricted'
    assert submit(client, workspace).status_code == 403
    assert not Run.objects.exists() and not Outbox.objects.exists()
    settings.GAMEFORGE_PRO_ACCESS = 'local'
    batch = create_batch(client, workspace)
    foreign = User.objects.create_user(username='other-variant-owner')
    client.force_login(foreign)
    response = submit(client, workspace)
    assert response.status_code == 404
    assert client.get(f'/api/chats/{workspace.pk}/').status_code == 404
    assert select(client, workspace, batch, {'id': batch['id'], 'artifact_hash': '0' * 64}).status_code == 404
    assert client.get(f"/api/runs/{batch['variants'][0]['run_id']}/").status_code == 404
    assert Run.objects.count() == 4
    client.force_login(workspace.owner)
    assert client.delete(f'/api/chats/{workspace.pk}/').status_code == 204
    assert workspace.runs.filter(status='cancelled').count() == 4
    assert submit(client, workspace).status_code == 404


def test_experiment_defaults_on_and_retries_preserve_assignment(client, workspace):
    hint = {'text': 'Сначала предложи короткую цель.', 'hint_key': 'first_goal'}
    with (patch('studio.analytics_hints.choose_analytics_hint', return_value=hint) as lookup,
          patch('studio.variants.secrets.randbelow', return_value=2) as draw):
        clients = [Client() for _ in range(2)]
        for instance in clients:
            instance.force_login(workspace.owner)
        gate = Barrier(2)

        def submit_experiment(instance):
            gate.wait(timeout=15)
            return create_batch(instance, workspace)

        first, retry = concurrently(clients, submit_experiment)
        assert first == retry
        assert first['analytics_experiment'] == {'status': 'applied'}
        experiment = VariantAnalyticsExperiment.objects.get(batch_id=first['id'])
        assert experiment.hint_variant_index == 3 and experiment.hint == hint
        assert experiment.first_choice_at is None
        assert create_batch(client, workspace, analytics_experiment=True) == first
        assert submit(client, workspace, analytics_experiment=False).status_code == 409
        lookup.assert_called_once_with(prompt=PROMPT, audience='everyone')
        draw.assert_called_once_with(4)
        ordinary = Chat.objects.create(owner=workspace.owner)
        for bad in ('true', 1, None, {}):
            assert submit(client, ordinary, analytics_experiment=bad).status_code == 400
        assert post(client, f'/api/chats/{ordinary.pk}/runs/', prompt=PROMPT, model_profile='pro',
                    analytics_experiment=True, idempotency_key='single').status_code == 400
        assert not ordinary.runs.exists()
        normal = create_batch(client, ordinary, analytics_experiment=False)
        assert 'analytics_experiment' not in normal
        # A missing field on replay also preserves batches created before the default changed.
        assert create_batch(client, ordinary) == normal
        assert create_batch(client, ordinary, analytics_experiment=False)['id'] == normal['id']
        assert submit(client, ordinary, analytics_experiment=True).status_code == 409
        lookup.assert_called_once()
    with (patch('studio.analytics_hints.choose_analytics_hint', return_value=None) as lookup,
          patch('studio.variants.secrets.randbelow') as draw):
        empty = Chat.objects.create(owner=workspace.owner)
        result = create_batch(client, empty)
        assert result['analytics_experiment'] == {'status': 'insufficient_data'}
        assert len(result['variants']) == 4
        experiment = VariantAnalyticsExperiment.objects.get(batch_id=result['id'])
        assert experiment.hint is None and experiment.hint_variant_index is None
        assert create_batch(client, empty, analytics_experiment=True) == result
        lookup.assert_called_once()
        draw.assert_not_called()


def test_experiment_rejects_edits_without_creating_jobs(client, workspace):
    revision = Revision.objects.create(chat=workspace, number=1, title='Игра', files={},
                                       html='', artifact_hash='a'*64, accepted=True)
    workspace.current_revision = revision
    workspace.save(update_fields=['current_revision'])
    response = submit(client, workspace, source_revision_id=str(revision.pk),
                      source_artifact_hash=revision.artifact_hash, analytics_experiment=True)
    assert response.status_code == 400 and response.json()['error']['code'] == 'invalid_analytics_experiment'
    assert not workspace.runs.exists() and not workspace.variant_batches.exists()
    assert not workspace.messages.exists() and not Outbox.objects.exists()
    with patch('studio.analytics_hints.choose_analytics_hint') as lookup:
        edit = create_batch(client, workspace, source_revision_id=str(revision.pk), source_artifact_hash=revision.artifact_hash)
        assert 'analytics_experiment' not in edit
        assert workspace.runs.filter(operation='edit').count() == 4
        lookup.assert_not_called()


@pytest.mark.parametrize(('pick_draft', 'shown_indexes', 'ready'), [
    (False, [1, 2, 3, 4], 4),
    (False, [1, 2], 2),  # Two more finished after the last chat poll.
    (False, [1, 2, 3, 0], 3),  # A UUID from outside the batch does not count.
    (False, None, None),  # Older client with no snapshot.
    (True, [1, 2, 3, 4], 3),  # Slot one is still an unaccepted draft.
    (True, [], 0),
    (True, None, None),
])
def test_first_experimental_choice_survives_later_selections(client, workspace, pick_draft, shown_indexes, ready):
    with patch('studio.analytics_hints.choose_analytics_hint', return_value={'text': 'Подсказка'}):
        batch = create_batch(client, workspace, analytics_experiment=True)
    slots = list(workspace.runs.order_by('variant_index'))
    revisions = []
    for run in slots:
        draft = pick_draft and run.variant_index == 1
        revision = Revision.objects.create(chat=workspace, run=run, number=run.variant_index, title='Игра',
            files={}, html='', artifact_hash=str(run.variant_index)*64, accepted=not draft)
        run.status = 'unverified' if draft else 'succeeded'
        if draft:
            run.candidate_revision = revision
        else:
            run.result_revision = revision
        run.save()
        revisions.append({'id': str(revision.pk), 'artifact_hash': revision.artifact_hash})
    draft_url = f"/api/chats/{workspace.pk}/variant-batches/{batch['id']}/draft-choice/"
    snapshot = {} if shown_indexes is None else {'ready_revision_ids': [
        revisions[index - 1]['id'] if index else str(workspace.pk) for index in shown_indexes
    ]}
    if pick_draft:
        fields = {'revision_id': revisions[0]['id'], 'artifact_hash': revisions[0]['artifact_hash'], **snapshot}
        assert post(client, draft_url, **{**fields, 'artifact_hash': 'a'*64}).status_code == 409
        assert post(client, draft_url, revision_id=revisions[1]['id'],
                    artifact_hash=revisions[1]['artifact_hash']).status_code == 409
        assert post(client, draft_url, **fields).status_code == 204
        # A subsequent poll or retry cannot change the first observation.
        fields['ready_revision_ids'] = [item['id'] for item in revisions[1:]]
        assert post(client, draft_url, **fields).status_code == 204
        workspace.refresh_from_db()
        assert workspace.current_revision_id is None
    else:
        assert select(client, workspace, batch, revisions[0], **snapshot).status_code == 200
    experiment = VariantAnalyticsExperiment.objects.get(batch_id=batch['id'])
    assert experiment.first_choice_index == 1 and str(experiment.first_choice_revision_id) == revisions[0]['id']
    assert experiment.first_choice_at and experiment.ready_at_first_choice == ready
    first_choice_at = experiment.first_choice_at
    assert select(client, workspace, batch, revisions[1],
                  expected_current_revision_id=None if pick_draft else revisions[0]['id']).status_code == 200
    experiment.refresh_from_db()
    assert experiment.first_choice_index == 1 and experiment.first_choice_at == first_choice_at
    assert experiment.ready_at_first_choice == ready
    assert str(experiment.batch.selected_revision_id) == revisions[1]['id']


def test_invalid_displayed_snapshot_cannot_change_first_choice(client, workspace):
    batch = create_batch(client, workspace, analytics_experiment=True)
    run = workspace.runs.get(variant_index=1)
    revision = Revision.objects.create(chat=workspace, run=run, number=1, title='Игра', files={}, html='',
                                       artifact_hash='a' * 64, accepted=True)
    run.status, run.result_revision = 'succeeded', revision
    run.save()
    picked = {'id': str(revision.pk), 'artifact_hash': revision.artifact_hash}
    for invalid in (None, str(revision.pk), ['invalid'], [str(revision.pk)] * 2, [str(revision.pk)] * 5):
        reply = select(client, workspace, batch, picked, ready_revision_ids=invalid)
        assert reply.status_code == 400 and reply.json()['error']['code'] == 'invalid_ready_revisions'
    workspace.refresh_from_db()
    assert workspace.current_revision_id is None
    experiment = VariantAnalyticsExperiment.objects.get(batch_id=batch['id'])
    assert experiment.batch.selected_revision_id is None and experiment.first_choice_at is None
