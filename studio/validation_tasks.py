"""Revision checks: durable, model-free work shared by automatic and manual paths."""

import logging
import time
import uuid
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from generation.requirements import coverage
from generation.source_map import locate_findings
from validation.checks import VERSION, review_checks
from validation.contracts import implementation_hash, suite_findings
from validation.suites import BUDGET_SECONDS, combine, plan

from .acceptance import assess
from .models import Chat, CheckReport, Revision, Run, ValidationRequest, ValidationTask
from .services import DomainError, fingerprint


def snapshot(revision):
    checks, corrections = review_checks(revision.checks)
    return {'artifact_hash': revision.artifact_hash, 'checks': checks, 'corrections': corrections,
            'requirement_manifest': revision.requirement_manifest, 'helpers': revision.helper_manifest,
            'compact_manifest': revision.compact_manifest, 'pipeline_version': revision.pipeline_version,
            'checks_review_required': revision.checks_review_required,
            'policy': VERSION, 'validator_hash': implementation_hash()}


@transaction.atomic
def create_validation(revision, data, *, run=None, enqueue=True):
    revision = Revision.objects.select_for_update().get(pk=revision.pk)
    if not revision.chat_id or revision.chat.deleted_at:
        raise DomainError('not_found', 'Игра недоступна.', 404)
    if revision.pipeline_version != 9:
        raise DomainError('unsupported_game', 'Этот игровой формат больше не поддерживается. Создайте новую игру.', 409)
    if data.get('artifact_hash') != revision.artifact_hash:
        raise DomainError('revision_changed', 'Выбранная версия изменилась. Откройте её заново.', 409)
    key = data.get('idempotency_key')
    if not isinstance(key, str) or not 1 <= len(key) <= 120:
        raise DomainError('idempotency_required', 'Не удалось определить запрос проверки.')
    previous = ValidationRequest.objects.filter(revision=revision, key=key).select_related('task').first()
    if previous:
        return previous.task
    frozen = snapshot(revision)
    active = revision.validations.filter(status__in=ValidationTask.ACTIVE).first()
    if active:
        if active.snapshot != frozen:
            raise DomainError('validation_changed', 'Дождитесь завершения текущей проверки.', 409)
        # An automatic run owns its repair/acceptance decisions. A manual request
        # can observe it, but must never grant those powers to a manual task.
        job = active
    else:
        job = ValidationTask.objects.create(revision=revision, run=run, run_fence=run.fence if run else None,
                                            origin='automatic' if run else 'manual', snapshot=frozen)
    ValidationRequest.objects.create(revision=revision, key=key, task=job)
    if enqueue and not active:
        transaction.on_commit(lambda: dispatch_validation(job.id), robust=True)
    return job


def dispatch_validation(ident):
    now = timezone.now()
    with transaction.atomic():
        job = ValidationTask.objects.select_for_update(skip_locked=True).filter(pk=ident, status='queued').filter(
            Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=now - timedelta(seconds=15))).first()
        if job is None:
            return
        job.dispatched_at = now
        job.save(update_fields=['dispatched_at'])
    try:
        process_validation.delay(str(ident))
    except Exception as exc:
        ValidationTask.objects.filter(pk=ident, dispatched_at=now).update(dispatched_at=None)
        logging.getLogger(__name__).warning('validation_dispatch_failed job=%s type=%s', ident, type(exc).__name__)


def dispatch_validations():
    # A dead worker cannot later publish an authoritative result. A fresh manual
    # check is explicit; do not silently repeat a costly browser suite forever.
    ValidationTask.objects.filter(status='checking', lease_until__lt=timezone.now()).update(
        status='infrastructure_error', stage='finished', fence=None, finished_at=timezone.now(),
        error={'code': 'worker_lost', 'message': 'Проверка прервалась. Можно запустить её заново.'})
    for ident in ValidationTask.objects.filter(status='queued', origin='manual').values_list('id', flat=True)[:100]:
        dispatch_validation(ident)


def cancel_validation(job):
    ValidationTask.objects.filter(pk=job.pk, status__in=ValidationTask.ACTIVE).update(
        status='cancelled', stage='finished', fence=None, finished_at=timezone.now())
    job.refresh_from_db()
    return job


def execute_validation(job, *, validate=None, outer_cancel=None, capture_visual=False):
    from validation.service import validate as browser_validate

    from .tasks import check_identity

    validate = validate or browser_validate
    with transaction.atomic():
        job = ValidationTask.objects.select_for_update().select_related('revision').get(pk=job.pk)
        if job.status != 'queued':
            return job.report
        if job.run_id and not Run.objects.filter(pk=job.run_id, fence=job.run_fence, status__in=Run.ACTIVE,
                                                cancel_requested=False).exists():
            cancel_validation(job)
            return None
        if job.snapshot != snapshot(job.revision):
            job.status, job.stage = 'infrastructure_error', 'finished'
            job.error = {'code': 'policy_changed', 'message': 'Правила проверки изменились. Запустите проверку заново.'}
            job.finished_at = timezone.now()
            job.save()
            return None
        job.status, job.stage, job.fence = 'checking', 'queued', uuid.uuid4()
        job.lease_until = timezone.now() + timedelta(seconds=60)
        job.save()
    revision = job.revision
    owned = ValidationTask.objects.filter(pk=job.pk, fence=job.fence, status='checking')
    last_poll = 0.0
    stopped = False

    def finish_cancelled():
        # A stale worker may observe that its lease was replaced. It must not
        # cancel the successor now executing this same durable task.
        owned.update(status='cancelled', stage='finished', fence=None, finished_at=timezone.now())

    def cancelled(force=False):
        nonlocal last_poll, stopped
        if force or time.monotonic() - last_poll >= 0.5:
            last_poll = time.monotonic()
            stopped = not owned.exists() or bool(outer_cancel and outer_cancel())
            if not stopped and (not Chat.objects.filter(pk=revision.chat_id, deleted_at__isnull=True).exists() or (
                job.run_id and Run.objects.filter(pk=job.run_id).filter(
                    Q(cancel_requested=True) | ~Q(status__in=Run.ACTIVE)).exists()
            )):
                stopped = True
            if not stopped:
                owned.update(lease_until=timezone.now() + timedelta(seconds=60))
        return stopped

    def progress(event):
        update: dict = {'stage': 'queued' if event['event'] == 'queued' else 'checking'}
        if event['event'] == 'started' and job.started_at is None:
            job.started_at = timezone.now()
            update['started_at'] = job.started_at
        if event['event'] == 'scenario':
            update['progress'] = {'batch': len(batches) + 1, 'batches': len(plan(checks)),
                                  'completed': sum(len(b.get('facts', [])) for b in batches) + event['completed'],
                                  'total': len(checks), 'check_id': event['check_id'], 'phase': event.get('phase')}
        owned.update(**update)

    checks, corrections = job.snapshot['checks'], job.snapshot['corrections']
    batches = list(job.batches)
    elapsed = sum(b.get('timings', {}).get('execution_seconds', b.get('elapsed_seconds', 0)) for b in batches)
    started = time.monotonic()
    try:
        options = {'capture_visual': True} if capture_visual else {}
        if revision.generation_profile == 'compact':
            from generation.compact import validation_contract
            options['contract'] = validation_contract(revision.compact_manifest, revision.files)
        groups = plan(checks)
        for index, group in enumerate(groups):
            if index < len(batches):
                continue
            if cancelled(True) or index and elapsed >= BUDGET_SECONDS[job.origin]:
                break
            owned.update(progress={'batch': index + 1, 'batches': len(groups),
                                   'completed': sum(len(b.get('facts', [])) for b in batches),
                                   'total': len(checks), 'scenario_ids': [c['id'] for c in group]})
            result = validate(revision.html, group, artifact_hash=revision.artifact_hash,
                              job_id=f'{job.id}:{job.fence}:{index}', cancelled=cancelled, progress=progress, **options)
            if result['status'] == 'cancelled' or cancelled(True):
                finish_cancelled()
                return None
            batches.append(result)
            elapsed += result.get('timings', {}).get('execution_seconds', result.get('elapsed_seconds', 0))
            owned.update(batches=batches)
            if result['status'] == 'infrastructure_error':
                break
        if cancelled(True):
            finish_cancelled()
            return None
        result = combine(checks, batches, artifact_hash=revision.artifact_hash)
        # Simple Lite has no media marker in its HTML. Its frozen input promise
        # still applies to automatic and manual checks, including later edits.
        if job.snapshot['requirement_manifest'].get('require_keyboard'):
            keyboard = [f for f in suite_findings(checks, require_keyboard=True)
                        if f['code'] == 'missing_keyboard_control']
            existing = {f.get('code') for f in result.get('findings', [])}
            result.setdefault('findings', []).extend(f for f in keyboard if f['code'] not in existing)
            if keyboard and result['status'] == 'passed':
                result['status'] = 'unverified'
        result['findings'] = locate_findings(result.get('findings', []), files=revision.files, html=revision.html)
        if job.snapshot['checks_review_required'] and result['status'] == 'passed':
            result['status'] = 'unverified'
            result['findings'].append({'code': 'check_suite_revised',
                'message': 'Модель восстановила сценарии. Проверьте исходные игровые условия лично.'})
        promises = coverage(checks, job.snapshot['requirement_manifest'])
        result['requirement_coverage'] = promises
        if promises['uncovered']:
            if result['status'] == 'passed':
                result['status'] = 'unverified'
            result['findings'].append({'code': 'requirement_manifest_mismatch', 'requirements': promises['uncovered'],
                                      'message': 'Сценарии не покрывают сохранённые обещания замысла.'})
        assessment = assess(result, checks, corrections)
        if assessment['action'] == 'review' and result['status'] == 'failed':
            result['status'] = 'unverified'
        timings = {'total_seconds': round(time.monotonic() - started, 3),
                   'queue_seconds': sum(b.get('timings', {}).get('queue_seconds', 0) for b in batches),
                   'execution_seconds': round(elapsed, 3)}
        assessment['timings'] = timings
        assessment['not_run'] = [f['id'] for f in result.get('facts', []) if f.get('status') == 'not_run']
        with transaction.atomic():
            chat = Chat.objects.select_for_update().filter(pk=revision.chat_id, deleted_at__isnull=True).first()
            if chat is None:
                finish_cancelled()
                return None
            if job.run_id:
                parent = Run.objects.select_for_update().get(pk=job.run_id)
                if parent.fence != job.run_fence or parent.cancel_requested or parent.status not in Run.ACTIVE or (outer_cancel and outer_cancel()):
                    finish_cancelled()
                    return None
            current = owned.select_for_update().first()
            revision.refresh_from_db()
            if current is None:
                return None
            if snapshot(revision) != job.snapshot:
                raise ValueError('validation target changed during execution')
            report = CheckReport.objects.create(
                validation_run=job.run, revision=revision, status=result['status'],
                findings=result.get('findings', []), facts=result.get('facts', []), stages=result.get('stages', []),
                elapsed_seconds=result.get('elapsed_seconds', elapsed), environment=result.get('environment', ''),
                visual_evidence=result.get('visual_evidence') or {}, screenshot_base64=result.get('screenshot_base64') or '',
                screenshot_mime=result.get('screenshot_mime', 'image/png'),
                identity=check_identity(revision, result.get('environment', '')), checks=checks, assessment=assessment)
            current.report, current.status, current.stage = report, result['status'], 'finished'
            current.timings, current.finished_at = timings, timezone.now()
            current.progress = {**current.progress, 'completed': len(checks) - len(assessment['not_run'])}
            current.fence, current.lease_until = None, None
            current.save()
            return report
    except Exception as exc:
        logging.getLogger(__name__).warning('validation_failed job=%s type=%s', job.id, type(exc).__name__)
        owned.update(status='infrastructure_error', stage='finished', fence=None, finished_at=timezone.now(),
                     error={'code': 'validation_failed', 'message': 'Не удалось выполнить проверку. Игра сохранена.'})
        return None


@shared_task(acks_late=False)
def process_validation(ident):
    job = ValidationTask.objects.filter(pk=ident, origin='manual').first()
    if job:
        execute_validation(job)


def automatic_validation(run, revision, *, validate, cancelled):
    key = 'automatic:' + str(run.id) + ':' + fingerprint(snapshot(revision))[:24]
    job = create_validation(revision, {'artifact_hash': revision.artifact_hash,
        'idempotency_key': key},
        run=run, enqueue=False)
    if job.run_id != run.id:
        # Join an existing check without taking over its cancellation or granting
        # it generation powers. Only the caller's Run can accept/repair later.
        if job.status == 'queued':
            execute_validation(job, validate=validate, capture_visual=run.visual_review_enabled)
            job.refresh_from_db()
        deadline = time.monotonic() + 1800
        while job.status in ValidationTask.ACTIVE and time.monotonic() < deadline:
            if cancelled():
                return None
            time.sleep(0.25)
            job.refresh_from_db()
        if not run.visual_review_enabled or job.report is None or job.report.visual_evidence or cancelled():
            return job.report
        # A concurrent manual check may have started without the experimental
        # Pro captures. Its receipt cannot silently replace that stronger run.
        job = create_validation(revision, {'artifact_hash': revision.artifact_hash,
            'idempotency_key': key + ':visual'}, run=run, enqueue=False)
    with transaction.atomic():
        job = ValidationTask.objects.select_for_update().get(pk=job.pk)
        if job.run_fence != run.fence and job.status in ValidationTask.ACTIVE and Run.objects.filter(
            pk=run.pk, fence=run.fence, status__in=Run.ACTIVE, cancel_requested=False
        ).exists():
            # The generation lease was reclaimed after a worker crash. Keep
            # completed batches and fence the previous browser receipt.
            job.status, job.stage, job.fence, job.lease_until = 'queued', 'queued', None, None
            job.run_fence = run.fence
            job.save()
    return execute_validation(job, validate=validate, outer_cancel=cancelled, capture_visual=run.visual_review_enabled)
