"""Queue mutations use conditional writes, including on SQLite without row locks."""

import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from prompt2play.pricing import snapshot

from .authentication import secret_hash
from .errors import Conflict
from .models import Candidate, Event, Job, Project, Runner, Version, empty_usage
from .queries import public_jobs


def event(job, message, stage=None, level="info", data=None):
    return Event.objects.create(
        job=job, stage=stage or job.stage, level=level, message=message, data=data or {}
    )


def scrub_log(value):
    """Defense in depth; workers must send operational metadata, not credentials/reasoning."""
    if isinstance(value, dict):
        counters = {
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "total_tokens",
            "budget_tokens",
        }
        return {
            key: (
                item
                if key in counters and type(item) is int and 0 <= item <= 10**12
                else "[redacted]"
                if re.search(
                    r"(token|password|secret|api.?key|authorization|reasoning|chain.of.thought)",
                    key,
                    re.I,
                )
                else scrub_log(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_log(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", value)
    return value


def create_job(project, user, values):
    values = dict(values)
    if values.get("budget_usd") is not None:
        model = values.get("model", "")
        if not model:
            defaults = {
                runner.capabilities.get("model", "")
                for runner in Runner.objects.filter(
                    role="generator",
                    revoked=False,
                    last_seen__gte=timezone.now() - timedelta(seconds=settings.FORGE_LEASE_SECONDS),
                )
                if values["provider"] in runner.capabilities.get("providers", [])
            }
            if len(defaults) != 1 or not next(iter(defaults)):
                raise ValidationError(
                    "Для расчёта бюджета выберите модель явно или подключите исполнителя с моделью по умолчанию.",
                    code="pricing_model_required",
                )
            model = next(iter(defaults))
        try:
            values["pricing"] = snapshot(model, values["provider"])
        except ValueError as exc:
            raise ValidationError(str(exc), code="pricing_unavailable") from exc
        values["model"] = model
    try:
        with transaction.atomic():
            # First database operation is a write: serializes SQLite writers too.
            Project.objects.filter(pk=project.pk).update(updated_at=timezone.now())
            if Job.objects.filter(
                project=project, status__in=["queued", "running", "waiting"]
            ).exists():
                raise Conflict("У проекта уже есть активное задание.", code="active_job")
            # A previous completion may have advanced latest_version since the
            # view loaded Project. Resolve the default only after serialization.
            project = Project.objects.get(pk=project.pk)
            base_id = values.pop(
                "base_version_id", project.latest_version_id if values["kind"] == "revise" else None
            )
            base = None
            if base_id is not None:
                base = (
                    Version.objects.only("id", "is_reference")
                    .filter(pk=base_id, project=project)
                    .first()
                )
                if base is None:
                    raise ValidationError(
                        "Базовая версия должна принадлежать этому проекту.",
                        code="invalid_base_version",
                    )
            if values["kind"] == "revise" and base is None:
                raise ValidationError(
                    "Для правки нужна базовая версия.", code="missing_base_version"
                )
            if base is not None and base.is_reference:
                raise ValidationError(
                    "Эталон доступен для просмотра. Создайте новый проект, чтобы генерировать и редактировать игры.",
                    code="reference_readonly",
                )
            job = Job.objects.create(project=project, created_by=user, base_version=base, **values)
            event(job, "Задание добавлено в очередь. Ожидаем совместимого исполнителя.")
    except IntegrityError as exc:
        raise Conflict("У проекта уже есть активное задание.", code="active_job") from exc
    return job


def cancel_job(job_id):
    with transaction.atomic():
        changed = Job.objects.filter(pk=job_id, status__in=["queued", "running", "waiting"]).update(
            status="cancelled",
            lease_expires_at=None,
            stage_fence=F("stage_fence") + 1,
            updated_at=timezone.now(),
        )
        job = public_jobs().filter(pk=job_id).first()
        if job is None:
            raise NotFound("Задание не найдено.")
        if changed:
            event(job, "Задание отменено пользователем.", level="warning")
    return job


def expire_jobs():
    """Stop expired runs independently of the transaction that rejects a write."""
    now = timezone.now()
    return Job.objects.filter(
        status__in=["queued", "running"], execution_expires_at__lte=now
    ).update(
        status="failed",
        stage="deadline",
        error="Run deadline exceeded.",
        stage_fence=F("stage_fence") + 1,
        lease_hash="",
        lease_expires_at=None,
        updated_at=now,
    )


def remaining_seconds(job):
    return (
        max(0.0, (job.execution_expires_at - timezone.now()).total_seconds())
        if job.execution_expires_at
        else float(job.budget_seconds)
        if job.budget_seconds is not None
        else None
    )


def require_deadline(job):
    if job.execution_expires_at and job.execution_expires_at <= timezone.now():
        raise Conflict("Run deadline exceeded.", code="run_deadline")


def claim_job(runner, capabilities, name=None):
    expire_jobs()
    now = timezone.now()
    runner_changes = dict(last_seen=now, capabilities=capabilities)
    if name:
        runner_changes["name"] = name
    if not Runner.objects.filter(pk=runner.pk, revoked=False).update(**runner_changes):
        raise AuthenticationFailed("Исполнитель отозван.", code="invalid_runner_token")
    eligible = (Q(status="queued") | Q(status="running", lease_expires_at__lte=now)) & (
        Q(execution_expires_at__isnull=True) | Q(execution_expires_at__gt=now)
    )
    compatible = Q(provider__in=capabilities["providers"]) & ~Q(
        provider__in=capabilities.get("requires_job_model", []), model=""
    )
    if runner.role == "validator":
        compatible = Q(
            stage="validate",
            active_candidate_id__in=Candidate.objects.filter(committed=True).values("id"),
        )
    else:
        compatible &= ~Q(stage__in=["validate", "commit"])
        if capabilities.get("continuable_authoring_v1") is not True:
            compatible &= ~Q(checkpoint__has_key="authoring_draft")
        if capabilities.get("interactive_plan_v1") is not True:
            compatible &= Q(creation_mode="lite")
    candidates = list(
        Job.objects.filter(eligible, compatible).values_list("id", "budget_seconds")[:50]
    )
    for job_id, seconds in candidates:
        raw = secrets.token_urlsafe(32)
        with transaction.atomic():
            # Recheck eligibility in the update, never rely on a prior SELECT.
            changed = Job.objects.filter(eligible, compatible, pk=job_id).update(
                status="running",
                runner=runner,
                lease_hash=secret_hash(raw),
                lease_expires_at=now + timedelta(seconds=settings.FORGE_LEASE_SECONDS),
                stage_fence=F("stage_fence") + 1,
                execution_expires_at=Coalesce(
                    F("execution_expires_at"),
                    Value(
                        now + timedelta(seconds=seconds) if seconds is not None else None,
                        output_field=Job._meta.get_field("execution_expires_at"),
                    ),
                ),
                updated_at=now,
            )
            if not changed:
                continue
            if not Runner.objects.filter(pk=runner.pk, revoked=False).exists():
                raise AuthenticationFailed("Исполнитель отозван.", code="invalid_runner_token")
            job = Job.objects.select_related("project__latest_version", "base_version").get(
                pk=job_id
            )
            event(job, "Исполнитель получил задание.", data={"runner_id": str(runner.pk)})
            return job, raw
    return None, None


def require_monotonic_usage(previous, incoming):
    """Known cumulative provider counters cannot be replaced by an older write.

    A timed-out request can still reach the coordinator after a later request.
    Call this only after taking the job's write fence, so the comparison and the
    checkpoint/terminal mutation share one serialized database transaction.
    Unknown reservations live in the checkpoint, not in these counters.
    """
    if any(incoming.get(name, 0) < previous.get(name, 0) for name in empty_usage()):
        raise Conflict(
            "Учёт токенов в запросе устарел. Уже сохранённый расход не может уменьшаться.",
            code="stale_usage",
        )


def fence(job_id, runner, raw_lease, **changes):
    """Call inside atomic(). Conditional UPDATE owns the fence until commit."""
    now = timezone.now()
    digest = secret_hash(raw_lease)
    expected_fence = changes.pop("stage_fence", None)
    condition = {"stage_fence": expected_fence} if expected_fence is not None else {}
    # When usage is supplied, take the same conditional write lock first but do
    # not replace the old checkpoint/status until its counters are compared.
    compare_usage = "usage" in changes
    # Keep status, lease and fence predicates on the UPDATE itself. A related
    # runner filter makes Django move them into an id subquery; PostgreSQL can
    # then retain stale qualifying ids after waiting on another writer's lock.
    # Runner revocation is checked with its own conditional write below, still
    # within the same transaction, so rejection rolls back the job write.
    changed = Job.objects.filter(
        Q(execution_expires_at__isnull=True) | Q(execution_expires_at__gt=now),
        pk=job_id,
        runner_id=runner.pk,
        status="running",
        lease_hash=digest,
        lease_expires_at__gt=now,
        **condition,
    ).update(updated_at=now, **({} if compare_usage else changes))
    if not changed:
        latest = Job.objects.filter(pk=job_id).first()
        if latest is None:
            raise NotFound("Задание не найдено.")
        require_deadline(latest)
        raise Conflict(
            "Аренда истекла, задание отменено или уже передано другому исполнителю.",
            code="lease_conflict",
        )
    if not Runner.objects.filter(pk=runner.pk, revoked=False).update(last_seen=now):
        raise AuthenticationFailed("Исполнитель отозван.", code="invalid_runner_token")
    job = public_jobs().get(pk=job_id)
    if compare_usage:
        require_monotonic_usage(job.usage, changes["usage"])
        Job.objects.filter(pk=job_id).update(**changes)
        for name, value in changes.items():
            setattr(job, name, value)
    return job


def heartbeat(job_id, runner, raw_lease):
    try:
        with transaction.atomic():
            fence(
                job_id,
                runner,
                raw_lease,
                lease_expires_at=timezone.now() + timedelta(seconds=settings.FORGE_LEASE_SECONDS),
            )
    except Conflict:
        # A cancelled lease may read its cancellation, but cannot extend or mutate it.
        cancelled = (
            Job.objects.filter(pk=job_id, status="cancelled", runner_id=runner.pk)
            .values("lease_hash")
            .first()
        )
        if cancelled and hmac.compare_digest(cancelled["lease_hash"], secret_hash(raw_lease)):
            return {"cancelled": True, "lease_seconds": 0}
        raise
    job = Job.objects.get(pk=job_id)
    return {
        "cancelled": False,
        "lease_seconds": settings.FORGE_LEASE_SECONDS,
        "stage_fence": job.stage_fence,
        "stage": job.stage,
        "remaining_seconds": remaining_seconds(job),
        "execution_expires_at": job.execution_expires_at.isoformat()
        if job.execution_expires_at
        else None,
    }


def complete_job(job_id, runner, values):
    raise Conflict(
        "Отправьте кандидата для независимой браузерной проверки.", code="validation_required"
    )
