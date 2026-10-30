from copy import deepcopy
from unittest.mock import patch

import pytest

from generation.artifacts import sha256
from generation.providers.fake import fixture_response
from generation.providers.fake import generate as fake_generate
from studio.models import Chat, User
from studio.services import create_run
from studio.tasks import process_run


@pytest.fixture
def maker(settings):
    settings.GAMEFORGE_PROVIDER = 'fake'
    settings.GAMEFORGE_MODEL = 'fixture'
    with patch('studio.services.schedule'), patch('studio.tasks.dispatch_outbox'):
        yield Chat.objects.create(owner=User.objects.create_user(username='v7-maker'))


@pytest.mark.django_db
@pytest.mark.browser
@pytest.mark.parametrize('case', ['normal', 'duplicate', 'stale_report'])
def test_syntax_repair_with_incomplete_checks_then_review_uses_real_browser(maker, case):
    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'code-first'})
    original = fixture_response()
    original['checks'] = original['checks'][:2]
    if case == 'duplicate':
        original['checks'].append(deepcopy(original['checks'][0]))
    game = next(f for f in original['files'] if f['path'] == 'game.js')
    game['content'] += '\nreturn 1;'
    operations = []
    def model(request, **kwargs):
        operations.append(request['operation'])
        result = fake_generate(request, **kwargs)
        if request['operation'] == 'create':
            result['response'] = deepcopy(original)
        elif request['operation'] == 'repair':
            basis = request['code_repair_basis']
            assert basis['defects'] == ['javascript_syntax']
            if case == 'stale_report':
                from studio.models import CheckReport
                CheckReport.objects.filter(pk=basis['report_id']).update(identity='superseded-report')
            result['response'].update(operation='repair', base_revision=request['base_revision'], files=[], checks=[],
                patches=[{'path': 'game.js', 'file_hash': sha256(request['files']['game.js']), 'old_text': '\nreturn 1;', 'new_text': '\nwindow.repaired = true;'}])
        else:
            policy = request['check_repair']
            result['response'] = {'status': 'unchanged', 'operation': 'check_repair',
                'base_revision': request['base_revision'], 'artifact_hash': policy['artifact_hash'],
                'checks_hash': policy['checks_hash'], 'checks': [], 'message': 'Нужен ручной разбор.'}
        return result
    with patch('generation.providers.fake.generate', side_effect=model):
        process_run(str(run.id))
    run.refresh_from_db()
    assert operations[:2] == ['create', 'repair'], (operations, run.error)
    assert len(operations) <= 3
    if case == 'stale_report':
        assert run.status == 'needs_attention' and run.error['code'] == 'stale_code_repair_basis'
        assert run.revisions.count() == 1 and run.invocations.count() == 2
        return
    first, repaired = run.revisions.order_by('number')
    assert first.checks == repaired.checks == original['checks']
    assert first.design == repaired.design and first.title == repaired.title
    assert repaired.files['game.js'].endswith('window.repaired = true;')
    assert not repaired.accepted and run.status == 'needs_attention'
    assert first.reports.first().findings[0]['code'] == 'javascript_syntax'
    assert repaired.reports.first().assessment['gates_passed'] is True


@pytest.mark.django_db
def test_guard_prevents_manual_or_successful_finish_with_unresolved_invocation(maker):
    from django.db import transaction

    from studio.services import DomainError, finish_run, reserve_invocation

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'finish-guard'})
    with transaction.atomic():
        inv = reserve_invocation(run, {'operation': 'create'})
    for status in ['succeeded', 'unverified', 'needs_attention']:
        with transaction.atomic(), pytest.raises(DomainError) as caught:
            finish_run(run.id, run.fence, status, 'premature')
        assert caught.value.code == 'invocation_pending'
    inv.state = 'returned'
    inv.save(update_fields=['state'])
    with transaction.atomic(), pytest.raises(DomainError):
        finish_run(run.id, run.fence, 'unverified', 'unapplied')
    run.refresh_from_db()
    assert run.status == 'queued'


@pytest.mark.django_db
def test_direct_transport_cannot_repeat_sent_call_on_worker_reentry(maker):
    from django.db import transaction
    from django.utils import timezone

    from studio.services import reserve_invocation

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'direct-sent'})
    with transaction.atomic():
        inv = reserve_invocation(run, {'operation': 'create'})
    inv.state, inv.sent_at = 'sent', timezone.now()
    inv.save(update_fields=['state', 'sent_at'])
    with patch('generation.service.generate') as inference:
        process_run(str(run.id))
    inference.assert_not_called()
    run.refresh_from_db()
    inv.refresh_from_db()
    assert run.status == inv.state == 'unknown'


@pytest.mark.django_db
@pytest.mark.parametrize('fault', ['old_version', 'stale_report', 'wrong_hash', 'uncertain'])
def test_controller_cannot_issue_source_permission_from_untrusted_or_stale_evidence(maker, fault):
    from django.db import transaction

    from generation.artifacts import materialize
    from studio.acceptance import assess
    from studio.check_repair import code_repair_basis
    from studio.models import CheckReport, Invocation
    from studio.tasks import check_identity, claim_run, store_candidate
    from validation.contracts import implementation_hash
    from validation.evidence import receipt

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'authority-' + fault})
    with transaction.atomic():
        current = claim_run(run.id)
        artifact = materialize(fixture_response(), operation='create')
        base = store_candidate(current, artifact, None)
    environment = 'mini-browser-v1:' + implementation_hash() + ':test'
    evidence = receipt(base.artifact_hash, environment, {'status': 'failed', 'scripts': 1}, [])
    result = {'status': 'failed', 'findings': [{'code': 'javascript_syntax'}], 'facts': [],
              'artifact_evidence': evidence, 'artifact_hash': base.artifact_hash, 'environment': environment}
    with patch('validation.service.environment_identity', return_value=environment):
        report = CheckReport.objects.create(revision=base, validation_run=run, status='failed',
            checks=base.checks, findings=result['findings'], environment=environment,
            identity=check_identity(base), assessment=assess(result, base.checks, []))
        assert code_repair_basis(run, base) is not None
        if fault == 'old_version':
            run.pipeline_version = 6
            run.save(update_fields=['pipeline_version'])
            Invocation.objects.create(run=run, attempt=1, state='settled',
                request={'generation_contract': {'pipeline_version': 6}})
        elif fault == 'stale_report':
            report.identity = 'old-identity'
        elif fault == 'wrong_hash':
            report.assessment['artifact_evidence']['artifact_hash'] = 'another-game'
        else:
            report.findings = [{'code': 'effect_mismatch'}]
        report.save()
        assert code_repair_basis(run, base) is None


@pytest.mark.django_db(transaction=True)
def test_duplicate_worker_and_stale_fence_keep_one_receipt_and_one_application(maker):
    import threading
    import uuid
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    from studio.models import Run
    from studio.tests.test_check_repair import browser

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'two-workers'})
    entered, release = threading.Event(), threading.Event()
    def blocked(request, **kwargs):
        entered.set()
        assert release.wait(5)
        # A completed remote receipt may arrive after its worker fence became stale.
        return fake_generate(request, on_event=lambda event: None, is_cancelled=lambda: False)
    def worker():
        try:
            process_run(str(run.id))
        finally:
            connections.close_all()
    with patch('generation.service.generate', side_effect=blocked) as inference, \
            patch('validation.service.validate', side_effect=browser), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        assert entered.wait(5)
        try:
            process_run(str(run.id))  # Duplicate delivery cannot claim the active run.
            assert inference.call_count == 1
            Run.objects.filter(pk=run.id).update(fence=uuid.uuid4())
        finally:
            release.set()
        future.result(timeout=5)
        assert not run.revisions.exists()
        assert run.invocations.get().state == 'returned'
        Run.objects.filter(pk=run.id).update(status='queued')
        process_run(str(run.id))
    run.refresh_from_db()
    assert inference.call_count == 1
    assert run.status == 'succeeded' and run.revisions.count() == 1
    assert run.invocations.get().state == 'settled'


@pytest.mark.django_db
@pytest.mark.parametrize('provider', ['fake', 'codex'])
@pytest.mark.parametrize('expired', [False, True])
def test_unsent_reservation_recovers_same_request_with_one_call_limit(maker, provider, expired):
    from datetime import timedelta

    from django.utils import timezone

    from studio.services import reserve_invocation
    from studio.tasks import claim_run, recover_expired, request_for
    from studio.tests.test_check_repair import browser

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'before-send', 'model_call_limit': 1})
    if provider == 'codex':
        run.provider, run.model = 'codex', 'gpt-6.1-sol'
        run.save(update_fields=['provider', 'model'])
    run = claim_run(run.id)
    inv = reserve_invocation(run, request_for(run, None, []))
    frozen = deepcopy(inv.request)
    run.attempts = inv.attempt
    run.lease_until = timezone.now() - timedelta(seconds=5)
    if expired:
        run.model_call_deadline = timezone.now() - timedelta(seconds=1)
    run.save()
    recover_expired()
    inv.refresh_from_db()
    assert inv.state == 'reserved' and inv.sent_at is None
    with patch('generation.service.generate', side_effect=fake_generate) as inference, \
            patch('validation.service.validate', side_effect=browser):
        process_run(str(run.id))
    run.refresh_from_db()
    inv.refresh_from_db()
    assert run.invocations.get().id == inv.id and inv.request == frozen and run.attempts == 1
    if expired:
        assert inference.call_count == 0 and inv.sent_at is None
        assert run.status == 'needs_attention' and run.error['code'] == 'model_deadline'
    else:
        assert inference.call_count == 1 and run.status == 'succeeded'
        assert inv.state == 'settled' and inv.sent_at is not None


@pytest.mark.django_db
def test_stale_worker_cannot_send_the_reservation_owned_by_its_successor(maker):
    import uuid

    from studio.models import Run
    from studio.services import reserve_invocation, settle_invocation
    from studio.tasks import claim_run, mark_invocation_sent, request_for
    from studio.tests.test_check_repair import browser

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'stale-unsent', 'model_call_limit': 1})
    run = claim_run(run.id)
    inv = reserve_invocation(run, request_for(run, None, []))
    Run.objects.filter(pk=run.id).update(attempts=1, fence=uuid.uuid4(), status='queued')
    assert not mark_invocation_sent(run, inv)
    settle_invocation(inv.id, unsent_fence=run.fence, error={'code': 'cancelled'})
    inv.refresh_from_db()
    assert inv.state == 'reserved' and inv.sent_at is None
    with patch('generation.service.generate', side_effect=fake_generate) as inference, \
            patch('validation.service.validate', side_effect=browser):
        process_run(str(run.id))
    run.refresh_from_db()
    assert inference.call_count == 1 and run.status == 'succeeded'
    assert run.invocations.get().id == inv.id


@pytest.mark.django_db
def test_unsent_cleanup_cannot_erase_a_committed_send_marker(maker):
    from studio.services import reserve_invocation, settle_invocation
    from studio.tasks import claim_run, mark_invocation_sent, request_for

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'sent-marker'})
    run = claim_run(run.id)
    inv = reserve_invocation(run, request_for(run, None, []))
    assert mark_invocation_sent(run, inv)
    settle_invocation(inv.id, unsent_fence=run.fence, error={'code': 'cancelled'})
    inv.refresh_from_db()
    assert inv.state == 'sent' and inv.sent_at is not None and inv.finished_at is None


@pytest.mark.django_db
def test_send_marker_checks_the_current_deadline_under_the_run_lock(maker):
    from datetime import timedelta

    from django.utils import timezone

    from studio.models import Run
    from studio.services import reserve_invocation
    from studio.tasks import claim_run, mark_invocation_sent, request_for

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'locked-deadline'})
    run = claim_run(run.id)
    inv = reserve_invocation(run, request_for(run, None, []))
    Run.objects.filter(pk=run.id).update(model_call_deadline=timezone.now() - timedelta(seconds=1))
    assert run.model_call_deadline is None
    assert not mark_invocation_sent(run, inv)
    inv.refresh_from_db()
    assert inv.state == 'reserved' and inv.sent_at is None


@pytest.mark.django_db
def test_cancelled_recovered_unsent_reservation_releases_capacity_without_a_send(maker):
    from datetime import timedelta

    from django.utils import timezone

    from studio.services import budget_snapshot, cancel_run, reserve_invocation
    from studio.tasks import claim_run, recover_expired, request_for

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'cancel-unsent'})
    run.provider, run.model = 'codex', 'gpt-6.1-sol'
    run.save(update_fields=['provider', 'model'])
    run = claim_run(run.id)
    inv = reserve_invocation(run, request_for(run, None, []))
    run.attempts = 1
    run.lease_until = timezone.now() - timedelta(seconds=5)
    run.save()
    recover_expired()
    run.refresh_from_db()
    assert run.lease_until is None and budget_snapshot()['reserved_usd'] > 0
    cancel_run(run)
    with patch('generation.service.generate') as inference:
        recover_expired()
        process_run(str(run.id))
    inference.assert_not_called()
    inv.refresh_from_db()
    assert inv.state == 'failed' and inv.cost_usd == 0 and inv.sent_at is None
    assert budget_snapshot()['reserved_usd'] == 0


@pytest.mark.django_db
@pytest.mark.browser
@pytest.mark.parametrize('case', ['mobile_only', 'prestart_check', 'wrong_start', 'empty', 'desktop_route_missing'])
def test_startup_gaps_finish_or_repair_checks_without_rewriting_source(maker, case):
    from studio.acceptance import confirmation_report
    from studio.check_repair import code_repair_basis
    from tests.test_harness_surface import startup_game

    html, checks = startup_game(case)
    operations = []
    def model(request, **kwargs):
        operations.append(request['operation'])
        assert request['operation'] in {'create', 'check_repair'}
        if request['operation'] == 'create':
            reply = fixture_response()
            reply.update(files=[{'path': 'index.html', 'content': html}], checks=deepcopy(checks))
        else:
            policy = request['check_repair']
            _, corrected = startup_game('normal')
            repaired = [{**deepcopy(next(c for c in corrected if c['category'] == r['category'])), **r}
                        for r in policy['requirements']]
            reply = {'status': 'unchanged' if case == 'desktop_route_missing' else 'ok',
                     'operation': 'check_repair', 'base_revision': request['base_revision'],
                     'artifact_hash': policy['artifact_hash'], 'checks_hash': policy['checks_hash'],
                     'checks': [] if case == 'desktop_route_missing' else repaired, 'message': 'Проверка сценария.'}
        return {'response': reply, 'usage': {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}}

    run = create_run(maker, {'prompt': 'Два шага дают победу', 'idempotency_key': 'surface-' + case})
    with patch('generation.service.generate', side_effect=model):
        process_run(str(run.id))
    run.refresh_from_db()
    revisions = list(run.revisions.all())
    assert all(r.files == revisions[0].files and r.artifact_hash == revisions[0].artifact_hash for r in revisions)
    assert revisions[0].checks == checks
    assert code_repair_basis(run, run.candidate_revision) is None
    if case in {'mobile_only', 'prestart_check'}:
        assert operations == ['create'] and run.status == 'succeeded'
    elif case == 'desktop_route_missing':
        assert operations == ['create', 'check_repair'] and run.status == 'needs_attention'
        assert run.error['code'] != 'validator_unavailable' and confirmation_report(run) is None
        follow = create_run(maker, {'prompt': run.prompt, 'idempotency_key': 'again'}, continued_from=run)
        with patch('generation.service.generate') as inference:
            process_run(str(follow.id))
        inference.assert_not_called()
        follow.refresh_from_db()
        assert follow.status == 'needs_attention' and follow.error['code'] != 'validator_unavailable'
    else:
        assert operations == ['create', 'check_repair'] and run.status == 'unverified'
        assert revisions[-1].checks_review_required and confirmation_report(run) is not None


@pytest.mark.django_db
@pytest.mark.parametrize('fault', ['stale', 'runtime', 'missing_receipt', 'foreign_hash', 'infrastructure', 'legacy'])
def test_scenario_repair_for_unobserved_surface_requires_current_loading_evidence(maker, fault):
    from generation.artifacts import materialize
    from studio.acceptance import assess
    from studio.check_repair import code_repair_basis, needs_repair
    from studio.models import CheckReport
    from studio.tasks import check_identity, claim_run, store_candidate
    from validation.contracts import implementation_hash
    from validation.evidence import gates, receipt

    run = create_run(maker, {'prompt': 'Три попадания', 'idempotency_key': 'surface-proof'})
    run = claim_run(run.id)
    base = store_candidate(run, materialize(fixture_response(), operation='create'), None)
    environment = 'mini-browser-v1:' + implementation_hash() + ':test'
    evidence = receipt(base.artifact_hash, environment, {'status': 'passed', 'scripts': 1}, [
        {'viewport': viewport, 'loaded': True, 'errors': [], 'requests': [], 'surface': {}}
        for viewport in ['mobile', 'landscape', 'desktop']])
    result = {'status': 'unverified', 'findings': [{'code': 'surface_not_observed'}], 'facts': [],
              'artifact_evidence': evidence, 'artifact_hash': base.artifact_hash, 'environment': environment,
              'gates': gates(evidence), 'stages': [{'stage': 'syntax', 'status': 'passed'}]}
    with patch('validation.service.environment_identity', return_value=environment):
        report = CheckReport.objects.create(revision=base, validation_run=run, status='unverified',
            checks=base.checks, findings=result['findings'], environment=environment,
            identity=check_identity(base), assessment=assess(result, base.checks, []))
        assert needs_repair(run, base, report.findings)
        assert code_repair_basis(run, base) is None
        if fault == 'stale':
            report.identity = 'superseded'
        elif fault == 'runtime':
            report.assessment['artifact_evidence']['viewports'][0]['errors'] = ['real failure']
        elif fault == 'missing_receipt':
            report.assessment['artifact_evidence'] = None
        elif fault == 'foreign_hash':
            report.assessment['artifact_evidence']['artifact_hash'] = 'other'
        elif fault == 'infrastructure':
            report.status = 'infrastructure_error'
        else:
            run.pipeline_version = 6
            run.save(update_fields=['pipeline_version'])
        report.save()
        assert not needs_repair(run, base, report.findings)
