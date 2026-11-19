import pytest

from studio.models import CheckReport
from studio.services import create_run
from studio.tasks import check_identity, request_for
from studio.tests.test_draft_editing import saved
from studio.tests.test_draft_editing import workspace as draft_workspace
from tests.test_lite_checks import failed_pair
from validation.contracts import implementation_hash

workspace = draft_workspace


@pytest.mark.django_db
def test_causal_feedback_is_frozen_only_for_current_lite_artifact(workspace):
    chat, _ = workspace
    run = create_run(chat, {'prompt': 'Змейка', 'idempotency_key': 'causal-feedback'})
    base = saved(chat)
    run.provider = 'relay'
    run.generation_strategy = 'lite'
    run.planning_required = False
    run.candidate_revision = base
    run.save()
    findings = [{'code': 'effect_not_causal', 'check_id': 'wall'}]
    report = CheckReport.objects.create(
        revision=base, status='unverified', findings=findings, facts=[failed_pair()],
        checks=base.checks, identity=check_identity(base, 'lite-causal-test'), environment='lite-causal-test',
        assessment={'gates_passed': True, 'validator_hash': implementation_hash()},
    )
    req = request_for(run, base, findings)
    assert req['operation'] == 'check_repair' and req['lite_checks_policy'] == 2
    evidence = req['lite_causal_feedback']
    assert evidence['artifact_hash'] == base.artifact_hash and evidence['report_id'] == report.id
    assert evidence['comparisons'][0]['with_input']['after'] == 'playing'
    report.identity = 'stale'
    report.save(update_fields=['identity'])
    assert 'lite_causal_feedback' not in request_for(run, base, findings)
    report.identity = check_identity(base, 'lite-causal-test')
    report.assessment['validator_hash'] = 'stale'
    report.save(update_fields=['identity', 'assessment'])
    assert 'lite_causal_feedback' not in request_for(run, base, findings)
    run.provider, run.generation_strategy = 'codex_api', 'pro'
    assert 'lite_causal_feedback' not in request_for(run, base, findings)
    assert 'lite_checks_policy' not in request_for(run, base, findings)
    run.provider, run.generation_strategy = 'relay', 'lite'
    layout = {'code': 'mobile_overflow', 'check_id': 'artifact-landscape',
              'diagnostic': {'viewport': {'width': 844, 'height': 390},
                             'layout': {'width': 844, 'height': 430, 'overflowX': False, 'overflowY': True,
                                        'outside': [{'selector': '#help', 'rect': {'x': 20, 'y': 380, 'width': 200, 'height': 50}}]}}}
    report.findings = [layout]
    report.assessment['validator_hash'] = implementation_hash()
    report.save(update_fields=['findings', 'assessment'])
    req = request_for(run, base, [layout])
    assert req['operation'] == 'repair'
    assert req['lite_layout_feedback']['layouts'][0]['layout']['overflowY'] is True
    assert 'lite_causal_feedback' not in req
    run.provider, run.generation_strategy = 'codex_api', 'pro'
    assert 'lite_layout_feedback' not in request_for(run, base, [layout])
