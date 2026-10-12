"""User-initiated continuation; old invocations and uncertain spend are immutable."""

from copy import deepcopy

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import services
from .budgets import budget_stopped
from .drafts import load_draft
from .errors import Conflict
from .models import Job, Project


def resumable(job):
    return job.status == "failed" and job.stage in (
        "plan",
        "repair",
        "commit",
        "validate",
        "validation",
    )


def continuation_checkpoint(job):
    checkpoint = deepcopy(job.checkpoint)
    retries = checkpoint.setdefault("user_retry_keys", {})
    invocations = {call.invocation_key: call for call in job.invocations.all()}
    for invocation in invocations.values():
        logical = invocation.invocation_key.split(":user-resume:", 1)[0]
        effective = invocations.get(retries.get(logical, logical))
        # An old ambiguous receipt must not shadow its successful continuation
        # when the user later resumes a different failed call.
        if effective is not None and effective.state == "completed":
            continue
        retries[logical] = f"{logical}:user-resume:{job.resume_count + 1}"
    return checkpoint


def resume_job(job_id, values):
    with transaction.atomic():
        original = Job.objects.get(pk=job_id)
        Project.objects.filter(pk=original.project_id).update(updated_at=F("updated_at"))
        Job.objects.filter(pk=job_id).update(updated_at=F("updated_at"))
        job = Job.objects.get(pk=job_id)
        if values["stage_fence"] != job.stage_fence:
            raise Conflict("Задание изменилось. Обновите страницу.", code="stale_resume")
        if not resumable(job) or budget_stopped(job):
            raise Conflict(
                "Для этого задания продолжение недоступно; проверьте бюджет.", code="not_resumable"
            )
        if Job.objects.filter(
            project_id=job.project_id, status__in=["queued", "running", "waiting"]
        ).exists():
            raise Conflict("В проекте уже есть активное задание.", code="active_job")
        draft = load_draft(job) if job.stage in ("plan", "repair") else {}
        if job.stage in ("plan", "repair") and job.checkpoint.get("authoring_draft") and not draft:
            raise Conflict("Сохранённый черновик не соответствует этапу.", code="draft_conflict")
        checkpoint = continuation_checkpoint(job)
        stage = job.stage
        if stage == "commit":
            if not job.active_candidate_id:
                raise Conflict("Нет сохранённого кандидата.", code="not_resumable")
            from .workflow import finalize_intent

            finalize_intent(job.active_candidate)
            stage = "validate"
        if stage == "validation":
            if not job.active_candidate_id:
                raise Conflict("Нет кандидата для повторной проверки.", code="not_resumable")
            stage = "repair"
            # The failed candidate/report is immutable. Author a new candidate;
            # never overwrite or revalidate the existing accepted/rejected row.
            previous_draft = checkpoint.pop("authoring_draft", None)
            if previous_draft:
                checkpoint.setdefault("previous_authoring_drafts", []).append(previous_draft)
            checkpoint["strategy"] = "structural"
        Job.objects.filter(pk=job.pk).update(
            checkpoint=checkpoint,
            status="queued",
            stage=stage,
            error="",
            resume_count=F("resume_count") + 1,
            stage_fence=F("stage_fence") + 1,
            lease_hash="",
            lease_expires_at=None,
            execution_expires_at=None,
            updated_at=timezone.now(),
        )
        services.event(
            job,
            "Продолжение запущено пользователем. Черновик, готовые ответы и резерв неизвестного расхода сохранены.",
            data={
                "previous_error": job.error,
                "resume_count": job.resume_count + 1,
                "draft_turn": draft.get("turn"),
            },
        )
        job.refresh_from_db()
        return job
