"""Explicit operator recovery of a failed, locally terminated Codex request.

This does not reconcile uncertain spend or retry network/lease/cancellation
failures. The ordinary gateway owns the single allowed timeout retry.
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from prompt2play.generation.retries import CODEX_TIMEOUT_RECEIPT, TIMEOUT_RETRY_SUFFIX

from . import services, workflow
from .errors import Conflict
from .models import Job, ModelInvocation, Project


def resume_timeout(job_id):
    with transaction.atomic():
        original = Job.objects.get(pk=job_id)
        Project.objects.filter(pk=original.project_id).update(updated_at=timezone.now())
        # A write fences competing cancellation/recovery even on SQLite.
        Job.objects.filter(pk=job_id).update(updated_at=F("updated_at"))
        job = Job.objects.get(pk=job_id)
        if (
            job.status != "failed"
            or job.provider != "codex"
            or job.stage not in ("plan", "repair")
            or job.resume_count
            or job.error
            not in (
                "ProviderError: Codex call exceeded wall timeout",
                "CodexCallTimeout: Codex call exceeded wall timeout",
            )
        ):
            raise Conflict(
                "Only an unrecovered Codex wall timeout may resume.", code="not_resumable"
            )
        if Job.objects.filter(project_id=job.project_id, status__in=["queued", "running"]).exists():
            raise Conflict("The project already has an active job.", code="active_job")
        invocation = job.invocations.order_by("-created_at", "-id").first()
        if (
            invocation is None
            or invocation.state != "ambiguous"
            or invocation.invocation_key.endswith(TIMEOUT_RETRY_SUFFIX)
            or job.invocations.filter(
                invocation_key=invocation.invocation_key + TIMEOUT_RETRY_SUFFIX
            ).exists()
        ):
            raise Conflict("No unused timeout retry remains.", code="not_resumable")
        if invocation.response_key:
            if workflow.store().read_json(invocation.response_key) != CODEX_TIMEOUT_RECEIPT:
                raise Conflict("Timeout receipt mismatch.", code="not_resumable")
        else:
            # The legacy transport raised this exact error only after process
            # cleanup. Preserve its unknown reservation; add eligibility only.
            if job.error != "ProviderError: Codex call exceeded wall timeout":
                raise Conflict("Missing local timeout receipt.", code="not_resumable")
            intent, key = workflow.store().prepare(CODEX_TIMEOUT_RECEIPT)
            workflow.store().commit(intent, key)
            ModelInvocation.objects.filter(pk=invocation.pk).update(response_key=key)
        now = timezone.now()
        Job.objects.filter(pk=job.pk).update(
            status="queued",
            error="",
            resume_count=F("resume_count") + 1,
            stage_fence=F("stage_fence") + 1,
            lease_hash="",
            lease_expires_at=None,
            execution_expires_at=None,
            budget_seconds=None,
            updated_at=now,
        )
        services.event(
            job,
            "Оператор возобновил запуск после тайм-аута. Сохранённые ответы используются повторно; "
            "долларовый лимит и резерв оборванного вызова сохранены. Ограничение по времени снято.",
            level="warning",
            data={
                "reason": "codex_wall_timeout",
                "previous_error": job.error,
                "previous_budget_seconds": job.budget_seconds,
                "previous_execution_expires_at": (
                    job.execution_expires_at.isoformat() if job.execution_expires_at else None
                ),
                "wall_timeout_removed": True,
                "invocation_id": str(invocation.pk),
            },
        )
        job.refresh_from_db()
        return job
