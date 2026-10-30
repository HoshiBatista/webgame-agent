import uuid
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from generation.artifacts import materialize
from generation.providers.fake import fixture_response
from studio.models import Chat, CheckReport, Invocation, Message, Revision, Run, User, ValidationTask
from studio.tasks import check_identity
from studio.validation_tasks import (
    cancel_validation,
    dispatch_validations,
    execute_validation,
    process_validation,
)
from validation.contracts import VIEWPORTS, implementation_hash
from validation.evidence import gates, receipt


@pytest.fixture
def game(db):
    owner = User.objects.create_user(username='validation-owner')
    chat = Chat.objects.create(owner=owner)
    artifact = materialize(fixture_response(), operation='create')
    revision = Revision.objects.create(chat=chat, number=1, **artifact)
    client = Client()
    client.force_login(owner)
    with patch('studio.validation_tasks.dispatch_validation'):
        yield revision, client


def browser(html, checks, **kwargs):
    environment = f'mini-browser-v1:{implementation_hash()}:test-browser'
    evidence = receipt(kwargs['artifact_hash'], environment, {'status': 'passed', 'scripts': 1}, [
        {'viewport': viewport, 'loaded': True, 'errors': [], 'requests': [],
         'surface': {'overflow': False, 'canvases': [{'visible': True, 'width': 200, 'height': 200}]}}
        for viewport in VIEWPORTS
    ])
    return {'status': 'passed', 'artifact_hash': kwargs['artifact_hash'], 'environment': environment,
            'artifact_evidence': evidence, 'gates': gates(evidence),
            'findings': [], 'stages': [{'stage': 'syntax', 'status': 'passed'}],
            'facts': [{**{k: c[k] for k in ('id', 'category', 'requirement', 'viewport')},
                       'status': 'passed', 'actions': c['steps']} for c in checks]}


def submit(revision, client, key='request'):
    response = client.post(f'/api/revisions/{revision.id}/validations/',
                           {'artifact_hash': revision.artifact_hash, 'idempotency_key': key},
                           content_type='application/json')
    assert response.status_code == 202, response.content
    return ValidationTask.objects.get(pk=response.json()['id'])


def test_manual_check_is_read_only_fresh_idempotent_and_owner_only(game):
    revision, client = game
    baseline = (Run.objects.count(), Invocation.objects.count(), Message.objects.count(), Revision.objects.count())
    first = submit(revision, client)
    assert submit(revision, client).id == first.id
    assert submit(revision, client, 'double-click').id == first.id
    with patch('generation.service.generate', side_effect=AssertionError('inference forbidden')), \
            patch('validation.service.validate', side_effect=browser) as validator:
        process_validation(str(first.id))
        process_validation(str(first.id))
        assert validator.call_count == 1
        assert submit(revision, client, 'double-click').id == first.id
        second = submit(revision, client, 'fresh')
        process_validation(str(second.id))
        assert validator.call_count == 2  # explicit refresh never uses passed cache
    revision.refresh_from_db()
    assert not revision.accepted and revision.chat.current_revision_id is None
    assert revision.reports.count() == 2
    assert baseline == (Run.objects.count(), Invocation.objects.count(), Message.objects.count(), Revision.objects.count())
    stranger = User.objects.create_user(username='validation-stranger')
    client.force_login(stranger)
    assert client.get(f'/api/validations/{first.id}/').status_code == 404
    assert client.post(f'/api/validations/{first.id}/cancel/').status_code == 404
    assert client.post(f'/api/revisions/{revision.id}/validations/').status_code == 404


@pytest.mark.parametrize('keyboard', [False, True])
def test_simple_lite_keeps_keyboard_requirement_without_media(game, keyboard):
    from generation.check_repair import permission
    from generation.requirements import manifest

    revision, client = game
    revision.requirement_manifest = manifest('Играть на телефоне и клавиатуре')
    revision.requirement_manifest['require_keyboard'] = True
    if keyboard:
        revision.checks = fixture_response(with_assets=True)['checks']
    revision.save()
    amended = manifest('Игра', previous=revision.requirement_manifest, amendment='Светлый фон')
    assert amended['require_keyboard'] is True
    repair = permission(revision.artifact_hash, revision.checks, revision.design, amended)
    assert repair['require_keyboard'] is True
    assert any(r['category'] == 'control' and r['viewport'] == 'desktop' for r in repair['requirements'])
    report = execute_validation(submit(revision, client), validate=browser)
    assert report.status == ('passed' if keyboard else 'unverified')
    assert any(f['code'] == 'missing_keyboard_control' for f in report.findings) is not keyboard
    assert report.assessment['action'] == ('accept' if keyboard else 'review')


def test_hash_format_and_csrf_are_enforced(game):
    revision, client = game
    url = f'/api/revisions/{revision.id}/validations/'
    assert client.post(url, {'idempotency_key': 'bad', 'artifact_hash': 'old'}).status_code == 409
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(revision.chat.owner)
    assert strict.post(url, {'idempotency_key': 'bad', 'artifact_hash': revision.artifact_hash}).status_code == 403
    revision.pipeline_version = 8
    revision.save(update_fields=['pipeline_version'])
    assert client.post(url, {'idempotency_key': 'old', 'artifact_hash': revision.artifact_hash}).status_code == 409
    assert not ValidationTask.objects.exists()


def test_historical_validation_does_not_restore_or_promote(game):
    revision, client = game
    current = Revision.objects.create(chat=revision.chat, number=2, **materialize(fixture_response(), operation='create'))
    Chat.objects.filter(pk=revision.chat_id).update(current_revision=current)
    job = submit(revision, client)
    execute_validation(job, validate=browser)
    assert Chat.objects.get(pk=revision.chat_id).current_revision_id == current.id


@pytest.mark.parametrize('during', [False, True])
def test_cancel_never_publishes_late_report(game, during):
    revision, client = game
    job = submit(revision, client)
    def delayed(*args, **kwargs):
        cancel_validation(job)
        assert kwargs['cancelled']()  # service polls cancellation, never the model
        return browser(*args, **kwargs)
    if not during:
        cancel_validation(job)
    execute_validation(job, validate=delayed)
    job.refresh_from_db()
    assert job.status == 'cancelled' and not job.report_id
    assert not CheckReport.objects.exists()


def test_identity_uses_actual_receipt_even_if_probe_unavailable(game):
    revision, client = game
    job = submit(revision, client)
    with patch('validation.service.environment_identity', return_value='mini-browser-v1:unavailable') as probe:
        report = execute_validation(job, validate=browser)
    assert report.identity == check_identity(revision, report.environment)
    assert 'unavailable' not in report.environment
    probe.assert_not_called()


def test_batch_plan_executes_mobile_start_after_thirteen_other_checks(game):
    revision, client = game
    originals = revision.checks
    revision.checks = [{**deepcopy(originals[1]), 'id': f'control-{i}'} for i in range(12)] + [originals[2], originals[0]]
    revision.save(update_fields=['checks'])
    job = submit(revision, client)
    batches = []
    def execute(html, checks, **kwargs):
        batches.append(checks)
        return browser(html, checks, **kwargs)
    report = execute_validation(job, validate=execute)
    assert len(batches) == 2 and all(len(group) <= 12 for group in batches)
    assert batches[0][0]['category'] == 'start'
    assert len(report.facts) == 14 and report.status == 'passed'
    assert not report.assessment['not_run']
    assert report.assessment['gates_passed']


def test_expired_worker_is_fenced_without_silent_rerun(game):
    revision, client = game
    job = submit(revision, client)
    ValidationTask.objects.filter(pk=job.pk).update(status='checking', lease_until=timezone.now()-timedelta(seconds=1))
    dispatch_validations()
    with patch('validation.service.validate') as validator:
        process_validation(str(job.id))
    validator.assert_not_called()
    job.refresh_from_db()
    assert job.status == 'infrastructure_error' and not job.report_id


def test_policy_change_while_waiting_requires_explicit_new_check(game):
    revision, client = game
    job = submit(revision, client)
    with patch('studio.validation_tasks.implementation_hash', return_value='new-policy'), \
            patch('validation.service.validate') as validator:
        process_validation(str(job.id))
    validator.assert_not_called()
    job.refresh_from_db()
    assert job.error['code'] == 'policy_changed' and not job.report_id


def test_old_worker_cannot_cancel_or_overwrite_successor(game):
    revision, client = game
    job = submit(revision, client)
    successor = uuid.uuid4()
    def replaced(*args, **kwargs):
        ValidationTask.objects.filter(pk=job.id).update(fence=successor)
        return browser(*args, **kwargs)
    assert execute_validation(job, validate=replaced) is None
    job.refresh_from_db()
    assert job.fence == successor and job.status == 'checking' and not job.report_id


def test_run_restart_resumes_completed_batches_without_replaying_them(game):
    from studio.validation_tasks import automatic_validation

    revision, _ = game
    revision.checks += [{**deepcopy(revision.checks[1]), 'id': f'extra-{i}'} for i in range(11)]
    revision.save(update_fields=['checks'])
    run = Run.objects.create(chat=revision.chat, operation='create', prompt='Fixture', provider='fake', model='fixture',
                             status='checking', fence=uuid.uuid4(), idempotency_key='restart', request_fingerprint='0'*64)
    calls = []
    def crash(html, checks, **kwargs):
        calls.append(checks)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return browser(html, checks, **kwargs)
    with pytest.raises(KeyboardInterrupt):
        automatic_validation(run, revision, validate=crash, cancelled=lambda: False)
    assert len(ValidationTask.objects.get(run=run).batches) == 1
    run.fence = uuid.uuid4()
    run.save(update_fields=['fence'])
    with patch('validation.service.validate', side_effect=browser) as validator:
        report = automatic_validation(run, revision, validate=validator, cancelled=lambda: False)
    assert validator.call_count == 1 and len(validator.call_args.args[1]) == 2
    assert report.status == 'passed' and len(report.facts) == 14


def test_manual_time_budget_keeps_not_run_explicit(game):
    revision, client = game
    revision.checks += [{**deepcopy(revision.checks[1]), 'id': f'extra-{i}'} for i in range(11)]
    revision.save(update_fields=['checks'])
    job = submit(revision, client)
    def slow(html, checks, **kwargs):
        return {**browser(html, checks, **kwargs), 'elapsed_seconds': 400}
    report = execute_validation(job, validate=slow)
    assert report.status == 'unverified' and len(report.assessment['not_run']) == 2
    assert {f['id'] for f in report.facts if f['status'] == 'not_run'} == set(report.assessment['not_run'])


def test_saved_report_is_marked_stale_after_policy_changes(game):
    from studio.serialization import report_data

    revision, client = game
    report = execute_validation(submit(revision, client), validate=browser)
    assert report_data(report)['current']
    with patch('validation.contracts.implementation_hash', return_value='next-policy'):
        assert not report_data(report)['current']


def test_manual_pass_requires_explicit_confirmation_and_new_check_blocks_it(game):
    from studio.acceptance import confirmation_report

    revision, client = game
    run = Run.objects.create(chat=revision.chat, operation='create', prompt='Fixture', provider='fake', model='fixture',
                             status='needs_attention', candidate_revision=revision,
                             idempotency_key='confirm', request_fingerprint='0'*64)
    report = execute_validation(submit(revision, client), validate=browser)
    assert confirmation_report(run).pk == report.pk
    assert Chat.objects.get(pk=revision.chat_id).current_revision_id is None
    fresh = submit(revision, client, 'fresh-confirmation')
    assert confirmation_report(run) is None
    cancel_validation(fresh)
    with patch('validation.service.environment_identity', return_value=report.environment):
        response = client.post(f'/api/runs/{run.id}/confirm/', {
            'confirmed': True, 'artifact_hash': revision.artifact_hash, 'report_id': report.pk,
        }, content_type='application/json')
    assert response.status_code == 200, response.content
    assert Chat.objects.get(pk=revision.chat_id).current_revision_id == revision.pk
    assert Invocation.objects.count() == 0


def test_batched_report_preserves_pro_visual_capture(game):
    revision, client = game
    revision.checks += [{**deepcopy(revision.checks[1]), 'id': f'extra-{i}'} for i in range(11)]
    revision.save(update_fields=['checks'])
    def capture(*args, **kwargs):
        assert kwargs['capture_visual']
        return {**browser(*args, **kwargs), 'visual_evidence': {'captured': True}}
    report = execute_validation(submit(revision, client), validate=capture, capture_visual=True)
    assert report.visual_evidence == {'captured': True}


def test_automatic_join_of_manual_check_preserves_pro_capture(game):
    from studio.validation_tasks import automatic_validation

    revision, client = game
    submit(revision, client)
    run = Run.objects.create(chat=revision.chat, operation='create', prompt='Fixture', provider='fake', model='fixture',
                             status='checking', visual_review_enabled=True, fence=uuid.uuid4(),
                             idempotency_key='visual-join', request_fingerprint='0'*64)
    def capture(*args, **kwargs):
        assert kwargs['capture_visual']
        return {**browser(*args, **kwargs), 'visual_evidence': {'captured': True}}
    report = automatic_validation(run, revision, validate=capture, cancelled=lambda: False)
    assert report.visual_evidence == {'captured': True}
    assert ValidationTask.objects.get().origin == 'manual'
    assert Invocation.objects.count() == 0


def test_validation_worker_is_registered_at_startup():
    from gameforge.celery import app

    assert 'studio.validation_tasks.process_validation' in app.tasks


def test_foreign_confirmation_cannot_trigger_environment_probe(game):
    revision, client = game
    run = Run.objects.create(chat=revision.chat, operation='create', prompt='Fixture', provider='fake', model='fixture',
                             status='needs_attention', candidate_revision=revision,
                             idempotency_key='foreign-confirm', request_fingerprint='0'*64)
    client.force_login(User.objects.create_user(username='foreign-confirm'))
    with patch('validation.service.environment_identity') as probe:
        response = client.post(f'/api/runs/{run.id}/confirm/', {'confirmed': True}, content_type='application/json')
    assert response.status_code == 404
    probe.assert_not_called()


@pytest.mark.browser
@pytest.mark.native_browser
@pytest.mark.parametrize('profile', ['full', 'compact'])
def test_manual_task_with_real_isolated_browser(game, monkeypatch, profile):
    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    revision, client = game
    if profile == 'compact':
        from tests.test_compact_generation import compact_response

        response = compact_response()
        response['probes'][1]['steps'].insert(1, {'action': 'await_condition', 'observation': 'phase',
                                                 'operator': 'eq', 'value': 'play', 'ms': 400})
        artifact = materialize(response, operation='create', generation_profile='compact')
        for key, value in artifact.items():
            setattr(revision, key, value)
    revision.checks += [{**deepcopy(revision.checks[1]), 'id': f'extra-{i}'} for i in range(11)]
    revision.save()
    job = submit(revision, client)
    with patch('generation.service.generate', side_effect=AssertionError('inference forbidden')):
        report = execute_validation(job)
    assert report.status == 'passed', report.findings
    assert report.assessment['gates_passed']
    assert len(report.facts) == 14 and not report.assessment['not_run']
    job.refresh_from_db()
    assert len(job.batches) == 2 and job.progress['completed'] == 14
    assert Chat.objects.get(pk=revision.chat_id).current_revision_id is None
