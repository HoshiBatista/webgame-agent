import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from generation.errors import GenerationError, GenerationPending
from generation.prompts import build_messages, system_prompt
from generation.providers.fake import fixture_response
from generation.providers.fake import generate as fake_generate
from studio.models import Budget, Invocation, Run
from studio.services import budget_snapshot, create_run, settle_invocation, tariff
from studio.tasks import process_run, request_for
from studio.tests.test_pro_parallel import SINGLE, answer, new_run, planned, resource_contract, tick
from studio.tests.test_pro_parallel import context as context  # noqa: F401
from tests.test_pro_audio import SCORE
from tests.test_pro_creative import creative_brief
from tests.test_validation import fixture_report


def staged_run(owner, version=4):
    run = planned(owner)
    run.pro_parallel_version = version
    run.requirement_manifest['requirements'] = [
        {k: c[k] for k in ('id', 'requirement', 'category', 'viewport')}
        for c in fixture_response()['checks']]
    run.save(update_fields=['pro_parallel_version', 'requirement_manifest'])
    return run


def staged_answer(request, **kwargs):
    if request['pro_parallel_branch'] == 'checks':
        return {'response': {'operation': 'pro_checks', 'source_hash': request['source_hash'],
                             'checks': fixture_response()['checks']},
                'usage': {'input_tokens': 10, 'output_tokens': 10}}
    result = answer(request)
    if request['pro_parallel_branch'] == 'audio' and request['pro_parallel'] == 5:
        result['response'] = {'score': SCORE}
    if request['pro_parallel_branch'] == 'gameplay':
        result['response']['checks'] = []
    return result


def test_touch_control_guidance_is_pinned_only_for_new_multiagent_plans(context):
    prompt = 'Штурвал с перетаскиванием управляет направлением корабля.'
    run = new_run(context, prompt=prompt)
    ordinary = new_run(context, model_profile='pro', prompt=prompt)
    planner_input = json.loads(build_messages(request_for(run, None, []))[1]['content'])
    guidance = planner_input['requirement_manifest']['touch_control_guidance']
    assert guidance == run.requirement_manifest['touch_control_guidance']
    assert guidance['version'] == 1 and 'hold_touch' in guidance['plan'] and 'tap_fraction' in guidance['plan']
    assert 'Keep explicitly requested drag gestures playable' in guidance['gestures']
    assert planner_input['game_request'] == prompt and not planner_input['preferences']
    assert 'touch_control_guidance' not in json.loads(
        build_messages(request_for(ordinary, None, []))[1]['content'])['requirement_manifest']

    # A saved request from before this feature keeps its original planning input on continuation.
    old = new_run(context, prompt=prompt)
    del old.requirement_manifest['touch_control_guidance']
    old.status = 'needs_attention'
    old.error = {'code': 'budget_exhausted'}
    old.save(update_fields=['requirement_manifest', 'status', 'error'])
    continued = create_run(old.chat, {'idempotency_key': 'continue'}, continued_from=old)
    assert request_for(continued, None, [])['requirement_manifest'] == old.requirement_manifest


def test_budget_refusal_before_plan_resumes_pinned_multiagent_creation(context, client, settings):
    prior = new_run(context)
    prior.invocations.create(attempt=1, request={}, state='settled', cost_usd=Decimal('70.182276'))
    liability = prior.invocations.create(attempt=2, request={}, state='unknown', reservation_usd=Decimal('6.53'),
                                         sent_at=timezone.now(), price=tariff('codex_api', 'gpt-6.2-sol'))
    Budget.objects.update_or_create(pk=1, defaults={'limit_usd': 100})
    deadline = timezone.now() + timedelta(hours=1)
    original = new_run(context, model_call_limit=8, model_call_deadline=deadline.isoformat())
    assert budget_snapshot()['available_usd'] == 23.287724
    with patch('studio.services.tariff', tariff), patch('generation.service.generate') as model:
        process_run(str(original.pk))
        model.assert_not_called()
    original.refresh_from_db()
    assert original.status == 'needs_attention' and original.error['code'] == 'budget_exhausted'
    assert not original.invocations.exists() and not original.game_plan

    settings.GAMEFORGE_PRO_PARALLEL_MODEL = settings.GAMEFORGE_PRO_PARALLEL_PLANNER_MODEL = 'changed'
    client.force_login(context)
    url = f'/api/runs/{original.pk}/continue/'
    payload = {'idempotency_key': 'resume'}
    for override in ({'model_call_limit': 9}, {'model_call_deadline': (deadline + timedelta(days=1)).isoformat()}):
        invalid = client.post(url, {**payload, **override}, content_type='application/json')
        assert invalid.status_code == 400 and invalid.json()['error']['code'] == 'invalid_call_budget'

    # Another job's final receipt releases enough headroom under the unchanged shared limit.
    settle_invocation(liability.pk, response={'received': True},
                      usage={'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 10})
    response = client.post(url, payload, content_type='application/json')
    assert response.status_code == 202, response.content
    resumed = Run.objects.get(pk=response.json()['id'])
    assert resumed.continued_from_id == original.pk and resumed.operation == 'create'
    assert resumed.planning_required and resumed.pro_parallel_version == original.pro_parallel_version == 5
    assert resumed.model_call_limit == resumed.max_model_calls == 8 and resumed.model_call_deadline == deadline
    assert resumed.policy_snapshot == original.policy_snapshot
    assert resumed.model == original.model == 'gpt-6.2-sol'
    assert resumed.planner_model == original.planner_model == 'gpt-6.2-astra'
    assert client.post(url, payload, content_type='application/json').json()['id'] == str(resumed.pk)

    def generate(request, **kwargs):
        if request['operation'] == 'plan':
            result = fake_generate(request, **kwargs)
            result['response']['plan'].update(resource_contract=resource_contract(), gameplay_partition=SINGLE,
                                              experience_direction=creative_brief())
            return result
        result = staged_answer(request)
        if request['pro_parallel_branch'] == 'checks':
            result['response']['checks'] = fixture_response(with_assets=True)['checks']
        result['usage']['cached_input_tokens'] = 0
        return result

    with (patch('studio.services.tariff', tariff), patch('generation.service.generate', side_effect=generate),
          patch('validation.service.validate', side_effect=lambda html, checks, **kwargs: fixture_report(html, checks))):
        # A worker may yield to the queue between dependent stages.
        for _ in range(resumed.max_model_calls + 1):
            process_run(str(resumed.pk))
            resumed.refresh_from_db()
            if resumed.status not in Run.ACTIVE:
                break
    assert resumed.status == 'succeeded', (resumed.stage, resumed.message, resumed.error,
                                            list(resumed.invocations.values_list('state', 'error')))
    assert resumed.chat.current_revision_id == resumed.result_revision_id and resumed.result_revision_id
    assert list(resumed.invocations.order_by('attempt').values_list('request__operation', 'request__model',
                                                                     'reservation_usd')) == [
        ('plan', 'gpt-6.2-astra', Decimal('26.12')),
        *((role, 'gpt-6.2-sol', Decimal('6.53')) for role in ('create', 'pro_graphics', 'pro_audio', 'pro_checks'))]
    assert budget_snapshot()['limit_usd'] == 100
    assert client.post(url, payload, content_type='application/json').json()['id'] == str(resumed.pk)
    stale = client.post(url, {'idempotency_key': 'duplicate'}, content_type='application/json')
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'cannot_continue'
    assert original.continuations.count() == 1 and not original.invocations.exists()
    assert Invocation.objects.filter(run__chat=original.chat).count() == 5


@pytest.mark.parametrize('profile,has_receipt', [('pro', False), ('pro_multi', True)])
def test_preplan_budget_resume_excludes_normal_pro_and_chains_with_paid_receipts(context, profile, has_receipt):
    original = new_run(context, model_profile=profile, model_call_limit=3)
    original.status = 'needs_attention'
    original.error = {'code': 'budget_exhausted'}
    original.save(update_fields=['status', 'error'])
    if has_receipt:
        ancestor = new_run(context)
        # Move the completed ancestor into the chain with a paid planning receipt.
        Run.objects.filter(pk=ancestor.pk).update(chat=original.chat, status='failed', idempotency_key='ancestor')
        ancestor.invocations.create(attempt=1, state='failed', cost_usd=1, request={'operation': 'plan'})
        original.continued_from = ancestor
        original.save(update_fields=['continued_from'])
    resumed = create_run(original.chat, {'idempotency_key': 'resume'}, continued_from=original)
    assert resumed.operation == 'repair' and resumed.model_call_limit is None


@pytest.mark.parametrize('version', [4, 5])
def test_scenarios_wait_for_source_and_resources_and_do_not_regenerate_them(context, version):
    run = staged_run(context, version)
    first = Mock(side_effect=GenerationPending('running'))
    assert tick(run, first) is None and first.call_count == 3
    second = Mock(side_effect=staged_answer)
    revision = tick(run, second)
    assert revision and second.call_count == 4, list(run.invocations.values('state', 'error'))
    checks = run.invocations.get(request__pro_parallel_branch='checks')
    assert ('within 60 ms' in system_prompt(checks.request)) == (version == 5)
    saved_request = {k: v for k, v in checks.request.items() if k != 'pro_audio_check_timing'}
    assert 'within 60 ms' not in system_prompt(saved_request)
    source = run.invocations.get(request__pro_parallel_branch='gameplay')
    assert checks.request['files'] == {f['path']: f['content'] for f in source.response['files']}
    assert source.request['reasoning_effort'] == 'medium' and source.response['checks'] == []
    audio = run.invocations.get(request__pro_parallel_branch='audio')
    assert audio.request['reasoning_effort'] == ('medium' if version == 5 else 'high')
    assert bool(audio.response.get('score')) == (version == 5)
    assert checks.request['assets']['music']['notes'][0]['note'] == 60
    assert len(revision.checks) > 0 and run.max_model_calls == 10


def test_repeated_output_limits_stop_one_role_without_repeating_paid_siblings(context):
    run = staged_run(context)
    def limited(request, **kwargs):
        if request['pro_parallel_branch'] == 'gameplay':
            raise GenerationError('response_output_limit', 'Interrupted', outcome_unknown=False,
                                  usage={'input_tokens': 10, 'output_tokens': 10})
        return staged_answer(request)
    for _ in range(3):
        tick(run, limited)
    assert run.status == 'needs_attention' and run.error['code'] == 'parallel_branch_exhausted'
    assert run.invocations.count() == 4
    assert run.invocations.filter(state='settled').count() == 2
    assert not run.candidate_revision_id


def test_failed_packaging_invalidates_scenarios_before_new_source_is_joined(context):
    from generation.errors import ContractError
    from studio.pro_parallel import advance
    from studio.tasks import Lease, claim_run

    run = staged_run(context)
    tick(run, staged_answer)  # Sources first; checks depend on settled source receipts.
    current = claim_run(run.id)
    assert advance(current, Lease(current), staged_answer,
                   Mock(side_effect=ContractError('invalid_html', 'Bad source'))) is None
    run.refresh_from_db()
    assert run.invocations.get(request__pro_parallel_branch='checks').error['code'] == 'parallel_source_changed'
    assert run.invocations.get(request__pro_parallel_branch='gameplay').state == 'failed'
    assert run.invocations.filter(state='settled').count() == 2
