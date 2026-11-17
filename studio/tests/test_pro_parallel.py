from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from generation.artifacts import materialize
from generation.errors import ContractError, GenerationError, GenerationPending
from generation.pro_parallel import BRANCHES, validate_contract
from generation.providers.fake import fixture_assets, fixture_response
from generation.providers.fake import generate as fake_generate
from generation.requirements import digest, manifest
from studio.capacity import capacity_full
from studio.model_profiles import configured_profiles, profile_options, unavailable_reason
from studio.models import Chat, Invocation, Run, User
from studio.pro_parallel import advance, branch_request
from studio.services import DomainError, cancel_run, create_run, finish_run
from studio.tasks import Lease, claim_run, request_for
from tests.test_pro_creative import creative_brief

SINGLE = {'mode': 'single', 'reason': 'Одна короткая механика не требует раздельных модулей.', 'interface': None}

def resource_contract():
    return {'graphics': [{'id': 'target', 'purpose': 'Крупная цель для попадания', 'width': 100, 'height': 100}],
            'sounds': [{'id': 'hit', 'event': 'Настоящее попадание в цель'}],
            'audience_adaptations': fixture_assets()['audience_adaptations'], 'silence_reason': ''}


def answer(request, **kwargs):
    role = request['pro_parallel_branch']
    recipe = fixture_assets()
    if role == 'gameplay':
        reply = fixture_response(with_assets=True)
        reply['assets'] = None
    else:
        keys = ['graphics'] if role == 'graphics' else ['instruments', 'sounds', 'music', 'silence_reason']
        reply = {'operation': 'pro_' + role, **{key: recipe[key] for key in keys}}
    return {'response': reply, 'usage': {'input_tokens': 10, 'output_tokens': 10}, 'provider_metadata': {}}


@pytest.fixture
def context(db, settings):
    settings.GAMEFORGE_PROVIDER = 'codex_api'
    settings.GAMEFORGE_PRO_PROVIDER = 'codex_api'
    settings.GAMEFORGE_PRO_ENABLED = True
    settings.GAMEFORGE_PRO_PARALLEL_ENABLED = True
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 100
    settings.GAMEFORGE_PRO_VISUAL_REVIEW_ENABLED = False
    settings.GAMEFORGE_RUN_INLINE = False
    owner = User.objects.create_user(username='parallel-owner')
    with (patch('studio.services.schedule'), patch('studio.tasks.dispatch_outbox'),
          patch('generation.providers.codex_api.available_models', return_value=[{'id': 'gpt-6-sol'}]),
          patch('generation.providers.codex_api.prepare', side_effect=lambda r, ident: {'job_id': ident}),
          patch('studio.services.tariff', return_value={'input': 0, 'output': 0})):
        yield owner


def new_run(owner, **fields):
    chat = Chat.objects.create(owner=owner)
    return create_run(chat, {'prompt': 'Попади в цель три раза', 'idempotency_key': 'one',
                            'model_profile': 'pro_multi', **fields})


def planned(owner, **fields):
    run = new_run(owner, **fields)
    plan_request = request_for(run, None, [])
    plan = fake_generate(plan_request, on_event=lambda _: None, is_cancelled=lambda: False)['response']['plan']
    plan['resource_contract'] = resource_contract()
    plan['gameplay_partition'] = SINGLE
    plan['experience_direction'] = creative_brief()
    validate_contract(plan['resource_contract'])
    run.game_plan, run.requirement_manifest = plan, manifest(run.game_request, plan)
    run.save()
    return run


def tick(run, generator):
    current = claim_run(run.id)
    assert current
    result = advance(current, Lease(current), generator, materialize)
    run.refresh_from_db()
    return result


def test_explicit_opt_in_preserves_normal_pro_plan_limits_and_disabled_catalog(context, settings):
    normal = new_run(context, model_profile='pro')
    experiment = new_run(context)
    assert normal.max_model_calls == 5 and normal.max_repair_attempts == 3
    assert experiment.max_model_calls == 10 and experiment.max_repair_attempts == 5
    assert not normal.pro_parallel and experiment.pro_parallel
    assert 'pro_parallel' not in request_for(normal, None, [])
    assert request_for(experiment, None, [])['pro_parallel'] == 3
    assert planned(context).max_model_calls == 9
    settings.GAMEFORGE_PRO_PARALLEL_ENABLED = False
    assert 'pro_multi' not in {p['id'] for p in profile_options(None)}
    with pytest.raises(DomainError, match='не включена'):
        new_run(context)
    settings.GAMEFORGE_PRO_PARALLEL_ENABLED = True
    profile = {**configured_profiles()['pro_multi'], 'provider': 'codex'}
    assert 'Pro API' in unavailable_reason(profile)
    with pytest.raises(DomainError):
        new_run(context, generation_profile='compact')
    with pytest.raises(DomainError):
        new_run(context, model_profile='pro', model_call_limit=9)


def test_all_three_jobs_are_sent_before_any_receipt_then_assembled_once(context):
    run = planned(context)
    first = Mock(side_effect=GenerationPending('running'))
    assert tick(run, first) is None
    assert first.call_count == run.attempts == 3
    ids = set(run.invocations.values_list('id', flat=True))
    assert run.invocations.filter(state='sent').count() == 3
    assert not run.chat.revisions.exists()
    second = Mock(side_effect=answer)
    revision = tick(run, second)
    assert revision and second.call_count == 3
    assert set(run.invocations.values_list('id', flat=True)) == ids
    assert run.invocations.filter(state='settled', revision=revision).count() == 3
    assert run.invocations.get(attempt=1).response['files'] == fixture_response(with_assets=True)['files']
    assert not revision.accepted and not run.chat.current_revision_id
    assert run.metrics['pro_parallel']['plan_hash'] == digest(run.game_plan)


def test_one_failed_branch_preserves_two_paid_answers_and_retries_only_that_branch(context):
    run = planned(context)
    def first(request, **kwargs):
        if request['pro_parallel_branch'] == 'audio':
            raise ContractError('invalid_assets', 'Нота выходит за длительность цикла.', usage={'output_tokens': 3})
        return answer(request)
    tick(run, first)
    assert run.invocations.filter(state='settled', revision__isnull=True).count() == 2
    second = Mock(side_effect=answer)
    assert tick(run, second)
    assert second.call_count == 1
    req = second.call_args.args[0]
    assert req['pro_parallel_branch'] == 'audio' and req['last_attempt_error']['code'] == 'invalid_assets'
    assert run.attempts == 4
    assert run.invocations.get(attempt=3).state == 'failed'


def test_reduced_capacity_and_expired_deadline_still_drain_all_receipts(context, settings):
    run = planned(context)
    tick(run, Mock(side_effect=GenerationPending('running')))
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 1
    Run.objects.filter(pk=run.id).update(model_call_deadline=timezone.now() - timedelta(seconds=1), policy_snapshot={})
    assert tick(run, answer)
    assert run.invocations.count() == 3 and run.candidate_revision_id


def test_one_slot_admits_each_branch_without_reissuing_previous_jobs(context, settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 1
    run = planned(context)
    pending = Mock(side_effect=GenerationPending('running'))
    tick(run, pending)
    assert run.attempts == 1 and pending.call_count == 1
    assert tick(run, answer)
    assert run.attempts == 3


def test_parallel_inferences_each_occupy_a_slot_visible_to_ordinary_pro(context, settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 3
    run = planned(context)
    tick(run, Mock(side_effect=GenerationPending('running')))
    normal = new_run(context, model_profile='pro')
    assert capacity_full(normal)
    call = run.invocations.first()
    call.state = 'failed'
    call.save()
    assert not capacity_full(normal)


def test_unknown_branch_blocks_replacements_but_other_paid_receipts_are_received(context):
    run = planned(context)
    tick(run, Mock(side_effect=GenerationPending('running')))
    def receive(request, **kwargs):
        if request['pro_parallel_branch'] == 'audio':
            raise GenerationError('unknown', 'Unknown', outcome_unknown=True)
        return answer(request)
    model = Mock(side_effect=receive)
    tick(run, model)
    assert model.call_count == 3 and run.status == 'unknown'
    assert run.invocations.filter(state='settled', revision__isnull=True).count() == 2
    assert run.invocations.filter(state='unknown').count() == 1
    assert run.invocations.count() == 3 and not run.candidate_revision_id


def test_partial_responses_survive_explicit_continuation_without_regeneration(context):
    run = planned(context, model_call_limit=2)
    tick(run, answer)
    assert run.status == 'needs_attention' and run.invocations.count() == 2
    continued = create_run(run.chat, {'prompt': run.prompt, 'idempotency_key': 'continue'}, continued_from=run)
    generator = Mock(side_effect=answer)
    revision = tick(continued, generator)
    assert revision and generator.call_count == 1
    assert generator.call_args.args[0]['pro_parallel_branch'] == 'audio'
    assert Invocation.objects.filter(revision=revision).count() == 3


def test_cancelled_fence_cannot_admit_or_apply_branches(context):
    run = planned(context)
    current = claim_run(run.id)
    lease = Lease(current)
    finish_run(current.id, current.fence, 'cancelled', 'Отмена')
    generator = Mock(side_effect=answer)
    assert advance(current, lease, generator, materialize) is None
    assert not generator.called and not run.invocations.exists()


def test_branch_request_hashes_freeze_role_contract(context):
    run = planned(context)
    requests = [branch_request(run, role) for role in BRANCHES]
    assert len({r['generation_contract']['system_prompt_sha256'] for r in requests}) == 3
    assert all(r['pro_parallel_plan_hash'] == digest(run.game_plan) for r in requests)
    assert all(r['reasoning_effort'] == 'high' for r in requests)


def test_full_pipeline_keeps_plan_then_three_branches_then_browser(context):
    from studio.tasks import process_run
    from tests.test_validation import fixture_report

    run = new_run(context)
    requests = []
    def model(req, **kwargs):
        requests.append(req)
        if req['operation'] == 'plan':
            result = fake_generate(req, **kwargs)
            result['response']['plan']['resource_contract'] = resource_contract()
            result['response']['plan']['gameplay_partition'] = SINGLE
            result['response']['plan']['experience_direction'] = creative_brief()
            return result
        result = answer(req)
        if req.get('pro_parallel_branch') == 'gameplay':
            result['response']['message'] = 'Попади в три светящиеся цели и собери все очки.'
        return result
    with patch('generation.service.generate', side_effect=model), patch(
        'validation.service.validate', side_effect=lambda html, checks, **kwargs: fixture_report(html, checks)
    ) as browser:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == 'succeeded', (run.error, run.private_diagnostics)
    assert [r['operation'] for r in requests] == ['plan', 'create', 'pro_graphics', 'pro_audio']
    assert browser.call_count == 1 and run.attempts == 4
    assert run.result_revision_id and run.chat.revisions.count() == 1
    assert 'Попади в три светящиеся цели' in run.chat.messages.get(role='assistant').content


def test_unvalidated_cancel_receipt_cannot_become_an_asset(context):
    run = planned(context, model_call_limit=3)
    tick(run, Mock(side_effect=GenerationPending('running')))
    call = run.invocations.get(request__pro_parallel_branch='graphics')
    call.state = 'returned'
    call.response = {'operation': 'pro_graphics', 'graphics': []}
    call.save()
    tick(run, answer)
    call.refresh_from_db()
    assert call.state == 'failed' and call.error['code'] == 'invalid_parallel_response'
    assert run.status == 'needs_attention' and not run.candidate_revision_id


def test_cancel_reconciles_all_three_receipts_without_applying_then_explicit_continue_reuses_them(context):
    from studio.tasks import reconcile_relay_cancellations

    run = planned(context)
    tick(run, Mock(side_effect=GenerationPending('running')))
    ids = set(run.invocations.values_list('id', flat=True))
    cancel_run(run)
    def fetch(req, **kwargs):
        assert kwargs == {'cancel': True}
        return answer(req)
    with patch('generation.providers.codex_api.fetch', side_effect=fetch) as delivery, \
            patch('generation.providers.codex_api.unpack', side_effect=lambda result, ident: result):
        reconcile_relay_cancellations()
    run.refresh_from_db()
    assert delivery.call_count == 3 and run.status == 'cancelled'
    assert run.invocations.filter(state='returned', finished_at__isnull=False).count() == 3
    assert not run.chat.revisions.exists()
    continued = create_run(run.chat, {'prompt': run.prompt, 'idempotency_key': 'continue-cancel'}, continued_from=run)
    model = Mock(side_effect=AssertionError('Paid replies must be reused'))
    revision = tick(continued, model)
    assert revision and not model.called
    assert set(Invocation.objects.filter(revision=revision).values_list('id', flat=True)) == ids


def test_branch_admission_rejects_a_worker_with_a_replaced_fence(context):
    import uuid

    from studio.services import reserve_invocation

    run = planned(context)
    current = claim_run(run.id)
    request = branch_request(current, 'gameplay')
    Run.objects.filter(pk=run.id).update(fence=uuid.uuid4())
    with pytest.raises(DomainError, match='остановлено'):
        reserve_invocation(current, request)
    assert not run.invocations.exists()


def split_run(owner, **fields):
    from tests.test_pro_partition import partition

    run = planned(owner, **fields)
    run.game_plan['gameplay_partition'] = partition()
    run.save(update_fields=['game_plan'])
    return run


def split_answer(request, **kwargs):
    from tests.test_pro_partition import split_replies

    return {'response': split_replies()[request['pro_parallel_branch']],
            'usage': {'input_tokens': 10, 'output_tokens': 10}, 'provider_metadata': {}}


def test_four_split_jobs_are_sent_before_receipt_and_join_without_fifth_inference(context):
    run = split_run(context)
    assert run.max_model_calls == 10
    sending = Mock(side_effect=GenerationPending('running'))
    assert tick(run, sending) is None
    assert sending.call_count == run.invocations.filter(state='sent').count() == 4
    assert [i.request['pro_parallel_branch'] for i in run.invocations.order_by('attempt')] == [
        'mechanics', 'scene', 'graphics', 'audio']
    ids = set(run.invocations.values_list('id', flat=True))
    receiving = Mock(side_effect=split_answer)
    revision = tick(run, receiving)
    assert revision and receiving.call_count == 4
    assert set(run.invocations.values_list('id', flat=True)) == ids
    assert run.invocations.filter(revision=revision, state='settled').count() == 4
    assert run.metrics['pro_parallel']['gameplay_mode'] == 'split'
    assert 'mechanics.js' in revision.files


def test_bad_mechanics_receipt_retries_only_mechanics_under_frozen_contract(context):
    run = split_run(context)
    def first(request, **kwargs):
        result = split_answer(request)
        if request['pro_parallel_branch'] == 'mechanics':
            result['response']['interface_hash'] = '0' * 64
        return result
    assert tick(run, first) is None
    assert run.invocations.filter(state='settled').count() == 3
    accepted_ids = set(run.invocations.filter(state='settled').values_list('id', flat=True))
    generator = Mock(side_effect=split_answer)
    assert tick(run, generator)
    assert generator.call_count == 1
    req = generator.call_args.args[0]
    assert req['pro_parallel_branch'] == 'mechanics' and req['last_attempt_error']['code'] == 'mechanics_interface_changed'
    assert accepted_ids <= set(run.invocations.filter(state='settled').values_list('id', flat=True))
    assert len(set(run.invocations.values_list('request__pro_parallel_plan_hash', flat=True))) == 1


def test_split_cancel_receipts_survive_and_continue_keeps_version_and_choice(context):
    from studio.tasks import reconcile_relay_cancellations

    run = split_run(context)
    tick(run, Mock(side_effect=GenerationPending('running')))
    cancel_run(run)
    with patch('generation.providers.codex_api.fetch', side_effect=split_answer), \
            patch('generation.providers.codex_api.unpack', side_effect=lambda result, ident: result):
        reconcile_relay_cancellations()
    run.refresh_from_db()
    continued = create_run(run.chat, {'prompt': run.prompt, 'idempotency_key': 'continue-split'}, continued_from=run)
    assert continued.pro_parallel_version == 3 and continued.game_plan == run.game_plan
    model = Mock(side_effect=AssertionError('Do not repeat saved branches'))
    assert tick(continued, model) and not model.called


@pytest.mark.parametrize('version', [1, 2])
def test_legacy_parallel_run_keeps_version_and_three_roles_on_continuation(context, version):
    run = planned(context)
    run.pro_parallel_version = version
    del run.game_plan['experience_direction']
    if version == 1:
        del run.game_plan['gameplay_partition']
    run.save()
    tick(run, Mock(side_effect=GenerationPending('running')))
    assert run.max_model_calls == 9 and run.invocations.count() == 3
    assert set(run.invocations.values_list('request__pro_parallel', flat=True)) == {version}
    cancel_run(run)
    run.refresh_from_db()
    # Retain the old protocol before any possible future receipt reconciliation.
    continued = create_run(run.chat, {'prompt': run.prompt, 'idempotency_key': 'continue-old'}, continued_from=run)
    assert continued.pro_parallel_version == version and continued.max_model_calls == 6


def test_split_pipeline_plans_once_assembles_then_uses_normal_browser_acceptance(context):
    from studio.tasks import process_run
    from tests.test_pro_partition import partition
    from tests.test_validation import fixture_report

    run = new_run(context)
    requests = []
    def model(req, **kwargs):
        requests.append(req)
        if req['operation'] == 'plan':
            result = fake_generate(req, **kwargs)
            result['response']['plan'].update(resource_contract=resource_contract(), gameplay_partition=partition(),
                                             experience_direction=creative_brief())
            return result
        return split_answer(req)
    with patch('generation.service.generate', side_effect=model), patch(
        'validation.service.validate', side_effect=lambda html, checks, **kw: fixture_report(html, checks)
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == 'succeeded', run.error
    assert [r['operation'] for r in requests] == ['plan', 'pro_mechanics', 'create', 'pro_graphics', 'pro_audio']
    assert run.attempts == 5 and run.chat.revisions.count() == 1
    assert run.result_revision.files['mechanics.js']
