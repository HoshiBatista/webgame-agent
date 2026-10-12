"""Cooperative pause: durable responses first, no new paid dispatch afterwards."""

from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import services, workflow
from .errors import Conflict
from .models import Job, Project


def finish_pause(job, reason=""):
    """Caller holds the job write lock. Preserve stage, receipts and draft."""
    if job.status not in ("running", "queued", "waiting"):
        return False
    remaining = services.remaining_seconds(job)
    checkpoint = {
        **job.checkpoint,
        "pause": {
            "return_status": "waiting" if job.status == "waiting" else "queued",
            "remaining_seconds": remaining,
            "reason": reason,
        },
    }
    Job.objects.filter(pk=job.pk).update(
        status="paused",
        pause_requested=False,
        checkpoint=checkpoint,
        stage_fence=F("stage_fence") + 1,
        lease_hash="",
        lease_expires_at=None,
        execution_expires_at=None,
        updated_at=timezone.now(),
    )
    services.event(
        job,
        reason or "Задание приостановлено. Ответы, черновик и расход сохранены.",
        data={"paused": True},
    )
    return True


def pause_job(job_id, values):
    with transaction.atomic():
        Job.objects.filter(pk=job_id).update(updated_at=F("updated_at"))
        job = Job.objects.get(pk=job_id)
        if values["stage_fence"] != job.stage_fence:
            raise Conflict("Задание изменилось. Обновите страницу.", code="stale_pause")
        if job.status in ("queued", "waiting") or (
            job.status == "running"
            and (not job.lease_expires_at or job.lease_expires_at <= timezone.now())
        ):
            finish_pause(job)
        elif job.status == "running" and not job.pause_requested:
            Job.objects.filter(pk=job.pk).update(pause_requested=True, updated_at=timezone.now())
            services.event(
                job,
                "Пауза запрошена. Сохраняем результат текущего шага; следующий запрос не начнётся.",
            )
        job.refresh_from_db()
        return job


def pause_boundary(job_id, runner, values):
    with transaction.atomic():
        job = services.fence(
            job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
        )
        if job.pause_requested or values.get("reason"):
            return {"paused": finish_pause(job, values.get("reason", ""))}
        return {"paused": False}


def hold_pending(job_id):
    """Keep a requested pause through a stage handoff or an approval gate."""
    job = Job.objects.get(pk=job_id)
    if job.pause_requested and job.status in ("queued", "waiting"):
        finish_pause(job)


def resume_paused(job_id, values):
    from .recovery import continuation_checkpoint

    with transaction.atomic():
        original = Job.objects.get(pk=job_id)
        Project.objects.filter(pk=original.project_id).update(updated_at=F("updated_at"))
        Job.objects.filter(pk=job_id).update(updated_at=F("updated_at"))
        job = Job.objects.get(pk=job_id)
        if job.status != "paused" or values["stage_fence"] != job.stage_fence:
            raise Conflict("Пауза уже изменена. Обновите страницу.", code="stale_resume")
        if (
            Job.objects.filter(
                project_id=job.project_id, status__in=["queued", "running", "waiting", "paused"]
            )
            .exclude(pk=job.pk)
            .exists()
        ):
            raise Conflict("В проекте уже есть активное задание.", code="active_job")
        stage = job.stage
        if stage == "commit":
            if not job.active_candidate_id:
                raise Conflict("Нет сохранённого кандидата.", code="not_resumable")
            from .workflow import finalize_intent

            finalize_intent(job.active_candidate)
            stage = "validate"
        checkpoint = continuation_checkpoint(job)
        if (
            values.get("upgrade_pipeline")
            and checkpoint.get("pipeline_version", "legacy-v1") != "adaptive-v1"
        ):
            if checkpoint.get("project_format", "runtime-v1") not in (
                "runtime-v1",
                "runtime-modules-v2",
            ):
                raise ValidationError("Эта версия формата требует отдельной дочерней доработки.")
            saved = checkpoint.get("authoring_draft")
            old = workflow.store().read_json(saved["key"]) if saved else {}
            checkpoint.update(
                pipeline_version="adaptive-v1",
                project_format=old.get("plan", {}).get(
                    "format", checkpoint.get("project_format", "runtime-v1")
                ),
            )
            if old:
                checkpoint["pipeline_migration"] = {
                    "from": "legacy-v1",
                    "draft_key": saved["key"],
                    "request_sha256": old["request_sha256"],
                }
            services.event(
                job,
                "Продолжение переведено на новый процесс. Исходный черновик сохранён неизменным; новые проверки выполняются отдельно.",
                data={"pipeline": "adaptive-v1", "original_draft": saved["key"] if saved else None},
            )
        pause = checkpoint.pop("pause", {})
        feedback = values.get("feedback", "").strip()
        if feedback:
            notes = checkpoint.get("continuation_feedback", [])
            if sum(len(note) for note in notes) + len(feedback) > 48000:
                raise ValidationError("История уточнений превышает 48 000 символов.")
            checkpoint["continuation_feedback"] = [*notes, feedback]
        # Resuming is explicit permission for another corrective attempt; the
        # preserved proposal/error is retried, not regenerated from the request.
        if "planning" in checkpoint:
            checkpoint["planning"] = {**checkpoint["planning"], "reset_stall": True}
        seconds = pause.get("remaining_seconds")
        Job.objects.filter(pk=job.pk).update(
            status=pause.get("return_status", "queued"),
            stage=stage,
            checkpoint=checkpoint,
            pause_requested=False,
            stage_fence=F("stage_fence") + 1,
            resume_count=F("resume_count") + 1,
            error="",
            lease_hash="",
            lease_expires_at=None,
            execution_expires_at=timezone.now() + timedelta(seconds=seconds)
            if seconds is not None
            else None,
            updated_at=timezone.now(),
        )
        services.event(
            job, "Продолжаем сохранённое задание после паузы. Учтённый расход не сброшен."
        )
        job.refresh_from_db()
        return job
