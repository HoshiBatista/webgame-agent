from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .queries import public_jobs
from .artifacts import report_for_read, require_report_binding
from . import workflow


def ident(value):
    return str(value) if value is not None else None


def dated(value):
    return value.isoformat() if value is not None else None


def job_data(job):
    from .budgets import budget_stopped

    result = {
        name: getattr(job, name)
        for name in (
            "kind",
            "prompt",
            "provider",
            "model",
            "status",
            "stage",
            "progress",
            "error",
            "max_repairs",
            "playthrough_mode",
            "budget_tokens",
            "budget_seconds",
            "usage",
            "stage_fence",
            "resume_count",
            "creation_mode",
            "pause_requested",
            "attempts",
        )
    }
    result.update(
        {
            name: ident(getattr(job, name))
            for name in (
                "id",
                "project_id",
                "base_version_id",
                "result_version_id",
                "runner_id",
                "active_candidate_id",
            )
        }
    )
    result.update(
        {
            name: dated(getattr(job, name))
            for name in ("created_at", "updated_at", "execution_expires_at")
        }
    )
    from .services import remaining_seconds

    result["remaining_seconds"] = remaining_seconds(job)
    result["approval"] = job.stage.removeprefix("review_") if job.status == "waiting" else None
    result["pipeline_version"] = job.checkpoint.get("pipeline_version", "legacy-v1")
    result["project_format"] = job.checkpoint.get("project_format", "runtime-v1")
    result["budget_usd"] = str(job.budget_usd) if job.budget_usd is not None else None
    result["pricing"] = job.pricing
    result["cost"] = workflow.cost_summary(job)
    result["budget_stopped"] = budget_stopped(job)
    from .recovery import resumable

    result["can_resume"] = resumable(job) and not budget_stopped(job)
    result["activity"] = {
        "worker_contact_at": dated(
            job.lease_expires_at - timedelta(seconds=settings.FORGE_LEASE_SECONDS)
        )
        if job.status == "running" and job.lease_expires_at
        else None,
        "worker_connected": bool(
            job.status == "running"
            and job.lease_expires_at
            and job.lease_expires_at > timezone.now()
        ),
        "calls": [
            {
                "id": str(call["id"]),
                "operation": call["operation"],
                "state": call["state"],
                "started_at": dated(call["created_at"]),
                "finished_at": dated(call["settled_at"]),
                "usage_known": call["actual_usage"] is not None,
                "stage_fence": call["stage_fence"],
            }
            for call in reversed(
                list(
                    job.invocations.order_by("-created_at", "-id").values(
                        "id",
                        "operation",
                        "state",
                        "created_at",
                        "settled_at",
                        "actual_usage",
                        "stage_fence",
                    )[:100]
                )
            )
        ],
    }
    return result


def project_data(project):
    if hasattr(project, "_recent_jobs"):
        latest = next(iter(project._recent_jobs), None)
        active = (
            latest
            if latest and latest.status in ["queued", "running", "waiting", "paused"]
            else None
        )
    else:
        jobs = public_jobs().filter(project_id=project.pk)
        active = jobs.filter(status__in=["queued", "running", "waiting", "paused"]).first()
        latest = active or jobs.order_by("-created_at", "-id").first()
    return {
        "id": ident(project.id),
        "title": project.title,
        "prompt": project.prompt,
        "created_at": dated(project.created_at),
        "updated_at": dated(project.updated_at),
        "latest_version_id": ident(project.latest_version_id),
        "latest_version_number": project.latest_version.number
        if project.latest_version_id
        else None,
        "active_job": job_data(active) if active else None,
        "latest_job": job_data(latest) if latest else None,
    }


def version_data(version, detail=False):
    result = {
        name: getattr(version, name)
        for name in ("number", "prompt", "summary", "is_reference", "validation", "usage", "spec")
    }
    result.update(
        id=ident(version.id),
        project_id=ident(version.project_id),
        created_at=dated(version.created_at),
        download_url=f"/api/versions/{version.id}/download/",
        source_url=f"/api/versions/{version.id}/source/",
    )
    result["validation"] = report_for_read(version.validation)
    result["eligible"] = workflow.version_eligible(version)
    result["visual_review_pending"] = workflow.version_reviewable(version)
    result["candidate_id"] = ident(version.candidate_id)
    result["preview_url"] = None
    if result["eligible"] or result["visual_review_pending"]:
        from .preview import preview_url

        result["preview_url"] = preview_url(version)
    if detail:
        payload = (
            workflow.candidate_payload(version.candidate)
            if version.candidate_id
            else {"files": version.files, "html": version.html}
        )
        result.update(files=payload["files"], html=payload["html"])
        result.update({name: payload.get(name, {}) for name in ("plan", "provenance")})
        result["format"] = payload.get("format", "legacy-four-module-v1")
        if result["validation"].get("schema_version") == 2:
            try:
                require_report_binding(
                    payload["files"], payload["html"], version.spec, version.validation
                )
                result["validation"]["binding_status"] = "verified"
            except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
                result["validation"]["binding_status"] = "mismatch"
                result["validation"]["status"] = "failed"
                result["eligible"] = False
                result["preview_url"] = None
                result["validation"].setdefault("errors", []).append(
                    "Сохранённые файлы не соответствуют отчёту. Скачивание этой версии заблокировано."
                )
    return result


def event_data(event):
    return dict(
        id=event.id,
        job_id=ident(event.job_id),
        stage=event.stage,
        level=event.level,
        message=event.message,
        data=event.data,
        created_at=dated(event.created_at),
    )


def runner_data(runner):
    online = bool(
        not runner.revoked
        and runner.last_seen
        and runner.last_seen > timezone.now() - timedelta(seconds=settings.FORGE_LEASE_SECONDS)
    )
    return dict(
        id=ident(runner.id),
        name=runner.name,
        created_at=dated(runner.created_at),
        last_seen=dated(runner.last_seen),
        online=online,
        revoked=runner.revoked,
        capabilities=runner.capabilities,
        role=runner.role,
    )
