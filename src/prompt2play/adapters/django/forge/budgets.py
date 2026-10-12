"""User-authorized budget extensions resume the same job and accounting ledger."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import services
from .drafts import load_draft
from .errors import Conflict
from .models import Job, Project

LEGACY_BUDGET_ERRORS = {
    "GenerationStopped: Недостаточно бюджета для следующего запроса. Учтены незавершённые вызовы.",
    "GenerationStopped: Следующий запрос не помещается в оставшийся долларовый бюджет",
    "GenerationStopped: Расчётный долларовый бюджет исчерпан",
    "GenerationStopped: Run token budget exceeded",
    "GenerationStopped: No author invocation fits remaining run budget",
}


def budget_stopped(job):
    return (
        job.status == "failed"
        and job.stage in ("plan", "repair")
        and (
            job.error.startswith("BudgetExhausted: ")
            or job.error in LEGACY_BUDGET_ERRORS
            or job.error.startswith("GenerationStopped: Cannot reserve ")
        )
    )


def extend_budget(job_id, values):
    with transaction.atomic():
        original = Job.objects.get(pk=job_id)
        # Same project -> job lock order as creation; prevents a concurrent successor.
        Project.objects.filter(pk=original.project_id).update(updated_at=F("updated_at"))
        Job.objects.filter(pk=job_id).update(updated_at=F("updated_at"))
        job = Job.objects.get(pk=job_id)
        field = "budget_usd" if job.budget_usd is not None else "budget_tokens"
        if values["stage_fence"] != job.stage_fence:
            raise Conflict("Данные задания изменились. Обновите страницу.", code="stale_budget")
        if not budget_stopped(job):
            raise Conflict("Продолжение доступно после остановки по бюджету.", code="not_resumable")
        if field not in values or values[field] <= getattr(job, field):
            raise Conflict("Укажите новый общий лимит больше прежнего.", code="invalid_budget")
        if Job.objects.filter(
            project_id=job.project_id, status__in=["queued", "running", "waiting"]
        ).exists():
            raise Conflict("В проекте уже есть активное задание.", code="active_job")
        last = job.invocations.order_by("-created_at", "-id").first()
        if last and (last.state == "reserved" or last.actual_usage is None):
            raise Conflict(
                "Результат последнего вызова ещё не подтверждён. Сначала восстановите его учёт.",
                code="unreconciled_invocation",
            )
        # Validate an existing checkpoint before queuing, never discard an unreadable draft.
        draft = load_draft(job)
        if job.checkpoint.get("authoring_draft") and not draft:
            raise Conflict("Черновик не соответствует этапу задания.", code="draft_conflict")
        previous = getattr(job, field)
        Job.objects.filter(pk=job.pk).update(
            **{field: values[field]},
            playthrough_mode=values.get("playthrough_mode", job.playthrough_mode),
            status="queued",
            error="",
            resume_count=F("resume_count") + 1,
            stage_fence=F("stage_fence") + 1,
            lease_hash="",
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
        services.event(
            job,
            "Бюджет увеличен. Продолжаем с сохранённого места; предыдущие расходы учтены.",
            data={
                "budget_field": field,
                "previous": str(previous),
                "new": str(values[field]),
                "previous_error": job.error,
                "draft_turn": draft.get("turn"),
                "playthrough_mode": values.get("playthrough_mode", job.playthrough_mode),
            },
        )
        job.refresh_from_db()
        return job
