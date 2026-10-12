"""Draft browser evidence is durable and fenced, but can never promote a version."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import services, workflow
from .artifacts import require_report_binding
from .errors import Conflict
from .models import Job


def read_diagnostic(job_id, runner, values):
    from prompt2play.validation.diagnostic_read import read_evidence

    workflow.require_role(runner, "generator")
    with transaction.atomic():
        job = services.fence(
            job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
        )
        if job.stage not in ("plan", "repair"):
            raise Conflict("Draft diagnostics require the generation stage.", code="stage_conflict")
        key = job.checkpoint.get("browser_diagnostic")
        if not key:
            return {"available": False, "reason": "No saved browser diagnostic yet"}
        if values.get("diagnostic_key") and values["diagnostic_key"] != key:
            # A stale report is an operation error, not lease revocation.
            return {
                "available": False,
                "diagnostic_key": key,
                "reason": "Diagnostic changed; read the current inventory first",
            }
        artifact_store = workflow.store()
        report = artifact_store.read_json(key)["report"]
        try:
            result = read_evidence(
                report,
                artifact_store.read,
                **{k: values[k] for k in ("path", "pointer", "offset", "limit")},
            )
        except (ValueError, KeyError, UnicodeError) as exc:
            return {"available": False, "diagnostic_key": key, "reason": str(exc)}
        return {"available": True, "diagnostic_key": key, **result}


def record_diagnostic(job_id, runner, values):
    workflow.require_role(runner, "generator")
    with transaction.atomic():
        job = services.fence(
            job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
        )
        if job.stage not in ("plan", "repair"):
            raise Conflict("Draft diagnostics require the generation stage.", code="stage_conflict")
        report = values["report"]
        try:
            require_report_binding(values["files"], values["html"], values["spec"], report)
        except (ValueError, TypeError) as exc:
            raise ValidationError(str(exc)) from exc
        report["evidence_files"] = workflow.store_evidence(report, values["evidence_files"])
        payload = {key: values[key] for key in ("files", "html", "spec", "report")}
        intent, key = workflow.store().prepare(payload)
        workflow.store().commit(intent, key)
        Job.objects.filter(pk=job.pk).update(
            checkpoint={**job.checkpoint, "browser_diagnostic": key}, updated_at=timezone.now()
        )
        services.event(
            job,
            "Черновик проверен в изолированном браузере. Отчёт и наблюдения сохранены.",
            stage="browser_check",
            data={
                "diagnostic_key": key,
                "status": report.get("status"),
                "failed_checks": [
                    c["name"] for c in report.get("checks", []) if c["status"] != "passed"
                ],
            },
        )
        return {"key": key, "release_eligible": False}
