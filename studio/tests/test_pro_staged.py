from unittest.mock import Mock

from generation.errors import GenerationError, GenerationPending
from generation.providers.fake import fixture_response
from studio.tests.test_pro_parallel import answer, planned, tick
from studio.tests.test_pro_parallel import context as context  # noqa: F401


def staged_run(owner):
    run = planned(owner)
    run.pro_parallel_version = 4
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
    if request['pro_parallel_branch'] == 'gameplay':
        result['response']['checks'] = []
    return result


def test_scenarios_wait_for_source_and_resources_and_do_not_regenerate_them(context):
    run = staged_run(context)
    first = Mock(side_effect=GenerationPending('running'))
    assert tick(run, first) is None and first.call_count == 3
    second = Mock(side_effect=staged_answer)
    revision = tick(run, second)
    assert revision and second.call_count == 4, list(run.invocations.values('state', 'error'))
    checks = run.invocations.get(request__pro_parallel_branch='checks')
    source = run.invocations.get(request__pro_parallel_branch='gameplay')
    assert checks.request['files'] == {f['path']: f['content'] for f in source.response['files']}
    assert source.request['reasoning_effort'] == 'medium' and source.response['checks'] == []
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
