"""Coordinator-owned candidate, validation, invocation and recovery use cases.

The Django adapter serializes every transition through the donor write fence.
Generators cannot supply validation or advance publication state.
"""

import base64
import binascii
from copy import deepcopy
import hashlib
from pathlib import PurePosixPath

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from prompt2play.adapters.artifacts.store import ArtifactStore, canonical
from prompt2play.application.policy import decide, repair_route
from prompt2play.generation.retries import CODEX_TIMEOUT_RECEIPT, TIMEOUT_RETRY_SUFFIX

from . import services
from .artifacts import artifact_manifest, require_report_binding
from .errors import Conflict
from .models import Candidate, Job, ModelInvocation, Project, ValidationResult, Version


def store():
    return ArtifactStore(settings.ARTIFACT_ROOT)


def require_role(runner, role):
    if runner.role != role:
        raise PermissionDenied(f"Operation requires a {role} runner.", code="runner_role")


def candidate_payload(candidate):
    if not candidate.committed:
        raise Conflict("Commit recovery is pending.", code="candidate_pending")
    try:
        payload = store().read_json(candidate.artifact_key)
        if (
            artifact_manifest(payload["files"], payload["html"], payload["spec"])
            != candidate.artifact
        ):
            raise ValueError("Candidate identity mismatch.")
        return payload
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Conflict("Artifact unavailable or corrupted.", code="artifact_mismatch") from exc


def candidate_data(candidate, detail=False):
    result = {
        "id": str(candidate.pk),
        "job_id": str(candidate.job_id),
        "parent_version_id": str(candidate.parent_id) if candidate.parent_id else None,
        "attempt": candidate.attempt,
        "artifact_key": candidate.artifact_key,
        "artifact": candidate.artifact,
        "committed": candidate.committed,
        "stage_fence": candidate.stage_fence,
    }
    if hasattr(candidate, "result"):
        result["validation"] = candidate.result.report
        result["outcome"] = candidate.result.outcome
    if detail:
        result.update(candidate_payload(candidate))
    return result


def version_eligible(version):
    """Recheck stored policy on reads; a flipped eligibility flag is insufficient."""
    return bool(
        version.eligible
        and version.candidate_id
        and version.candidate.committed
        and hasattr(version.candidate, "result")
        and version.candidate.result.report == version.validation
        and decide(version.validation, version.candidate.attempt, 0).action == "promote"
    )


def finalize_intent(candidate):
    """Recover a durable DB intent without replaying model calls."""
    services.expire_jobs()
    store().commit(candidate.intent, candidate.artifact_key)
    with transaction.atomic():
        Candidate.objects.filter(pk=candidate.pk, committed=False).update(committed=True)
        # A cancelled or replaced run may keep its bytes, but may never advance.
        Job.objects.filter(
            pk=candidate.job_id,
            status="running",
            active_candidate=candidate,
            stage_fence=candidate.stage_fence,
        ).update(
            status="queued",
            stage="validate",
            progress=65,
            stage_fence=F("stage_fence") + 1,
            lease_hash="",
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
    candidate.committed = True
    return candidate


def submit_candidate(job_id, runner, values):
    require_role(runner, "generator")
    values = dict(values)
    lease, expected = values.pop("lease_token"), values.pop("stage_fence")
    key = values.pop("idempotency_key")
    usage = values.pop("usage", None)
    invocation_id = values.pop("invocation_id", None)
    payload = {name: values[name] for name in ("html", "files", "spec", "plan", "provenance")}
    payload["format"] = values.get("format", "legacy-four-module-v1")
    if payload["format"] == "runtime-v1":
        from prompt2play.generation.runtime import assemble_runtime

        try:
            requested_runtime = payload["spec"].get("runtime", {}).get("sha256")
            if not isinstance(requested_runtime, str):
                raise ValidationError("Trusted runtime digest is required.")
            assembled = assemble_runtime(
                payload["files"], payload["spec"], expected_runtime_digest=requested_runtime
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValidationError(str(exc)) from exc
        if assembled != payload["html"]:
            raise ValidationError("Submitted HTML differs from the trusted runtime assembly.")
    artifact = artifact_manifest(payload["files"], payload["html"], payload["spec"])
    content_key = hashlib.sha256(canonical(payload)).hexdigest()
    previous = Candidate.objects.filter(job_id=job_id, submission_key=key).first()
    if previous:
        if previous.artifact_key != content_key or previous.generator_id != runner.pk:
            raise Conflict(
                "Submission key was already used for different bytes.", code="submission_conflict"
            )
        # Repeated delivery is read-only. Recovery command owns pending commits.
        return previous
    intent, content_key = store().prepare(payload)
    with transaction.atomic():
        try:
            job = services.fence(job_id, runner, lease, stage_fence=expected)
        except Conflict:
            previous = Candidate.objects.filter(
                job_id=job_id, submission_key=key, generator=runner
            ).first()
            if previous and previous.artifact_key == content_key:
                return previous
            raise
        previous = Candidate.objects.filter(job=job, submission_key=key).first()
        if previous:
            if previous.artifact_key != content_key:
                raise Conflict("Submission key conflict.", code="submission_conflict")
            return previous
        if job.stage in ("commit", "validate"):
            raise Conflict("Candidate delivery is already pending.", code="stage_conflict")
        if (
            invocation_id
            and not ModelInvocation.objects.filter(
                pk=invocation_id, job=job, state="completed"
            ).exists()
        ):
            raise Conflict("Model invocation has not settled.", code="invocation_pending")
        usage = usage or job.usage
        services.require_monotonic_usage(job.usage, usage)
        candidate = Candidate.objects.create(
            job=job,
            generator=runner,
            parent=job.base_version,
            attempt=job.attempts + 1,
            submission_key=key,
            stage_fence=expected,
            artifact_key=content_key,
            intent=intent,
            artifact=artifact,
            summary=values.get("summary", ""),
            usage=usage,
        )
        Job.objects.filter(pk=job.pk).update(
            active_candidate=candidate,
            attempts=candidate.attempt,
            usage=usage,
            stage="commit",
            updated_at=timezone.now(),
        )
        services.event(
            job,
            "Candidate committed; isolated validation is required.",
            stage="validate",
            data={"candidate_id": str(candidate.pk), "artifact": artifact},
        )
    return finalize_intent(candidate)


def cost_summary(job):
    from prompt2play.pricing import usd, nano_usd

    if job.budget_usd is None:
        return None
    held = (
        job.invocations.filter(actual_usage__isnull=True).aggregate(
            value=Sum("reserved_cost_nano")
        )["value"]
        or 0
    )
    return {
        "estimated_usd": usd(job.cost_nano),
        "upper_usd": usd(job.cost_upper_nano),
        "reserved_usd": usd(held),
        "remaining_usd": usd(max(0, nano_usd(job.budget_usd) - job.cost_upper_nano - held)),
        "over_budget": job.cost_upper_nano > nano_usd(job.budget_usd),
    }


def reserve_invocation(job_id, runner, values):
    require_role(runner, "generator")
    with transaction.atomic():
        job = services.fence(
            job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
        )
        if job.stage in ("commit", "validate"):
            raise Conflict("Generation is not the current stage.", code="stage_conflict")
        invocation = ModelInvocation.objects.filter(
            job=job, invocation_key=values["invocation_key"]
        ).first()
        if invocation:
            if (
                invocation.prompt_sha256 != values["prompt_sha256"]
                or invocation.operation != values["operation"]
            ):
                raise Conflict(
                    "Invocation key reused for another request.", code="invocation_conflict"
                )
            return invocation
        reserved_cost = 0
        if job.budget_usd is not None:
            from prompt2play.pricing import cost_bounds, nano_usd

            if not {"reservation_input_tokens", "reservation_output_tokens"} <= values.keys():
                raise Conflict(
                    "Исполнитель не поддерживает долларовый бюджет. Обновите его.",
                    code="pricing_required",
                )
            estimate = {
                "input_tokens": values["reservation_input_tokens"],
                "cached_input_tokens": 0,
                "output_tokens": values["reservation_output_tokens"],
            }
            reserved_cost = cost_bounds(estimate, job.pricing)[1]
            held = (
                job.invocations.filter(actual_usage__isnull=True).aggregate(
                    value=Sum("reserved_cost_nano")
                )["value"]
                or 0
            )
            if job.cost_upper_nano + held + reserved_cost > nano_usd(job.budget_usd):
                raise Conflict(
                    "Недостаточно долларового бюджета для следующего запроса; учтены незавершённые вызовы.",
                    code="budget_exhausted",
                )
        else:
            reserved = (
                ModelInvocation.objects.filter(job=job, actual_usage__isnull=True)
                .exclude(state="completed")
                .aggregate(value=Sum("reserved_tokens"))["value"]
                or 0
            )
            if (
                job.usage.get("total_tokens", 0) + reserved + values["reserved_tokens"]
                > job.budget_tokens
            ):
                raise Conflict(
                    "Token budget exhausted or held by uncertain calls.", code="budget_exhausted"
                )
        if values["invocation_key"].endswith(TIMEOUT_RETRY_SUFFIX):
            services.event(
                job,
                "Автопродолжение после тайм-аута: повторяем только оборванный запрос. "
                "Неизвестный расход предыдущего вызова остаётся в резерве.",
                level="warning",
                data={"operation": values["operation"], "retry": 1},
            )
        return ModelInvocation.objects.create(
            job=job,
            generator=runner,
            invocation_key=values["invocation_key"],
            operation=values["operation"],
            prompt_sha256=values["prompt_sha256"],
            stage_fence=job.stage_fence,
            reserved_tokens=values["reserved_tokens"],
            reserved_cost_nano=reserved_cost,
        )


def invocation_data(invocation):
    result = {
        "id": str(invocation.pk),
        "state": invocation.state,
        "stage_fence": invocation.stage_fence,
        "reserved_tokens": invocation.reserved_tokens,
        "reserved_cost_nano": invocation.reserved_cost_nano,
        "cost_nano": invocation.cost_nano,
        "cost_upper_nano": invocation.cost_upper_nano,
        "actual_usage": invocation.actual_usage,
        "response": None,
    }
    if invocation.response_key:
        result["response"] = store().read_json(invocation.response_key)
    return result


def settle_invocation(job_id, runner, values):
    require_role(runner, "generator")
    with transaction.atomic():
        job = services.fence(
            job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
        )
        if job.stage in ("commit", "validate"):
            raise Conflict("Generation is not the current stage.", code="stage_conflict")
        invocation = ModelInvocation.objects.filter(pk=values["invocation_id"], job=job).first()
        if invocation is None:
            raise Conflict("Invocation does not belong to this job.", code="invocation_conflict")
        if invocation.state == "completed":
            return invocation
        if invocation.stage_fence != job.stage_fence:
            raise Conflict(
                "Unsettled call belongs to an expired fence; do not replay it.",
                code="ambiguous_invocation",
            )
        state = values["state"]
        response_key = ""
        if state != "completed" and values.get("response") not in ({}, CODEX_TIMEOUT_RECEIPT):
            raise ValidationError("Only a local timeout marker may accompany an interrupted call.")
        if state == "completed" or values.get("response") == CODEX_TIMEOUT_RECEIPT:
            intent, response_key = store().prepare(values["response"])
            store().commit(intent, response_key)
        if "usage" in values:
            services.require_monotonic_usage(job.usage, values["usage"])
            Job.objects.filter(pk=job.pk).update(usage=values["usage"])
        if "invocation_usage" in values:
            account_invocation(
                job.pk,
                runner,
                {"invocation_id": invocation.pk, "invocation_usage": values["invocation_usage"]},
            )
        ModelInvocation.objects.filter(pk=invocation.pk).update(
            state=state, response_key=response_key, settled_at=timezone.now()
        )
        if values.get("response") == CODEX_TIMEOUT_RECEIPT and not invocation.response_key:
            services.event(
                job,
                "Запрос Codex превысил время ожидания; локальный процесс остановлен. "
                "Продолжение возможно в пределах оставшихся времени и бюджета.",
                level="warning",
                data={"operation": invocation.operation, "interruption": "codex_wall_timeout"},
            )
        invocation.refresh_from_db()
        return invocation


def account_invocation(job_id, runner, values):
    """Account an owned paid call after cancellation, without accepting its output."""
    require_role(runner, "generator")
    with transaction.atomic():
        # Accounting is allowed after lease loss. This lock never advances stages.
        if not Job.objects.filter(pk=job_id).update(updated_at=timezone.now()):
            raise Conflict("Unknown invocation job.", code="invocation_conflict")
        job = Job.objects.get(pk=job_id)
        invocation = ModelInvocation.objects.filter(
            pk=values["invocation_id"], job=job, generator=runner
        ).first()
        if invocation is None:
            raise PermissionDenied(
                "Only the invocation owner can account for it.", code="invocation_owner"
            )
        usage = values["invocation_usage"]
        if invocation.actual_usage is not None:
            if invocation.actual_usage != usage:
                raise Conflict(
                    "Invocation usage was already recorded differently.", code="accounting_conflict"
                )
            return invocation
        changes = {"actual_usage": usage}
        if job.budget_usd is not None:
            from prompt2play.pricing import cost_bounds

            changes["cost_nano"], changes["cost_upper_nano"] = cost_bounds(usage, job.pricing)
        if invocation.state == "reserved":
            changes["state"] = "ambiguous"
        ModelInvocation.objects.filter(pk=invocation.pk).update(**changes)
        aggregate = {name: 0 for name in job.usage}
        for recorded in ModelInvocation.objects.filter(
            job=job, actual_usage__isnull=False
        ).values_list("actual_usage", flat=True):
            for name in aggregate:
                aggregate[name] += recorded.get(name, 0)
        reconciled = {name: max(job.usage.get(name, 0), value) for name, value in aggregate.items()}
        reconciled["total_tokens"] = reconciled["input_tokens"] + reconciled["output_tokens"]
        cost_changes = {}
        if job.budget_usd is not None:
            totals = job.invocations.aggregate(lower=Sum("cost_nano"), upper=Sum("cost_upper_nano"))
            cost_changes = {
                "cost_nano": totals["lower"] or 0,
                "cost_upper_nano": totals["upper"] or 0,
            }
        Job.objects.filter(pk=job.pk).update(usage=reconciled, **cost_changes)
        invocation.refresh_from_db()
        return invocation


def store_evidence(report, supplied):
    declared = report.get("evidence_files", [])
    if not isinstance(declared, list) or len(declared) > 100:
        raise ValidationError("Invalid evidence inventory.")
    references = []
    total = 0
    for entry in declared:
        if not isinstance(entry, dict):
            raise ValidationError("Invalid evidence entry.")
        name = entry.get("path", "")
        path = PurePosixPath(name) if isinstance(name, str) else PurePosixPath("/")
        if path.is_absolute() or ".." in path.parts or not name or "\\" in name:
            raise ValidationError("Unsafe evidence path.")
        encoded = supplied.get(name)
        if not isinstance(encoded, str):
            raise ValidationError("Evidence bytes are missing.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValidationError("Invalid evidence encoding.") from exc
        total += len(data)
        if (
            total > 32_000_000
            or len(data) != entry.get("bytes")
            or hashlib.sha256(data).hexdigest() != entry.get("sha256")
        ):
            raise ValidationError("Evidence bytes differ from inventory.")
        references.append({**entry, "object_key": store().put_bytes(data)})
    if set(supplied) != {entry["path"] for entry in declared}:
        raise ValidationError("Unexpected evidence bytes.")
    return references


def validate_candidate(job_id, runner, values):
    require_role(runner, "validator")
    values = dict(values)
    submission_sha256 = hashlib.sha256(canonical(values["report"])).hexdigest()
    existing = ValidationResult.objects.filter(
        candidate_id=values["candidate_id"], candidate__job_id=job_id
    ).first()
    if existing is not None:
        if (
            existing.validator_id != runner.pk
            or existing.report.get("submission_sha256") != submission_sha256
        ):
            raise Conflict(
                "Candidate already has a different validation result.", code="validation_conflict"
            )
        return Version.objects.get(candidate_id=values["candidate_id"])
    with transaction.atomic():
        try:
            job = services.fence(
                job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
            )
        except Conflict:
            # A concurrent identical delivery may have advanced the fence while
            # this request waited on the serialized job write. It remains a read.
            existing = ValidationResult.objects.filter(
                candidate_id=values["candidate_id"], candidate__job_id=job_id
            ).first()
            if (
                existing is not None
                and existing.validator_id == runner.pk
                and existing.report.get("submission_sha256") == submission_sha256
            ):
                return Version.objects.get(candidate_id=values["candidate_id"])
            raise
        if job.stage != "validate" or str(job.active_candidate_id) != str(values["candidate_id"]):
            raise Conflict("Candidate is not the current validation stage.", code="stage_conflict")
        candidate = Candidate.objects.get(pk=job.active_candidate_id)
        payload = candidate_payload(candidate)
        report = deepcopy(values["report"])
        try:
            require_report_binding(payload["files"], payload["html"], payload["spec"], report)
        except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
            raise ValidationError(str(exc)) from exc
        report["evidence_files"] = store_evidence(report, values.get("evidence_files", {}))
        decision = decide(report, candidate.attempt, job.max_repairs)
        if decision.outcome == "passed" and len(report["evidence_files"]) < 2:
            report["status"] = "unverified"
            report.setdefault("warnings", []).append(
                "Desktop and mobile evidence bytes are required."
            )
            decision = decide(report, candidate.attempt, job.max_repairs)
        report["status"] = decision.outcome
        report["submission_sha256"] = submission_sha256
        services.require_deadline(job)
        ValidationResult.objects.create(
            candidate=candidate, validator=runner, report=report, outcome=decision.outcome
        )
        project = Project.objects.select_for_update().get(pk=job.project_id)
        number = (
            Version.objects.filter(project=project).aggregate(last=Max("number"))["last"] or 0
        ) + 1
        version = Version.objects.create(
            project=project,
            number=number,
            prompt=job.prompt,
            summary=candidate.summary,
            candidate=candidate,
            eligible=decision.action == "promote",
            validation=report,
            usage=candidate.usage,
            spec=payload["spec"],
            files={},
            html="",
        )
        if decision.action == "promote":
            services.require_deadline(job)
            Project.objects.filter(pk=project.pk).update(
                latest_version=version, updated_at=timezone.now()
            )
            changes = {
                "status": "completed",
                "stage": "done",
                "progress": 100,
                "result_version": version,
                "error": "",
            }
        elif decision.action == "repair":
            route = repair_route(
                report, sorted(payload["files"]), job.checkpoint.get("failure_fingerprint")
            )
            changes = {
                "status": "queued",
                "stage": "repair",
                "progress": 30,
                "error": route.reason,
                "checkpoint": {
                    "candidate_id": str(candidate.pk),
                    "report": report,
                    "strategy": route.strategy,
                    "files": list(route.files),
                    "failure_fingerprint": route.fingerprint,
                    "reason": route.reason,
                },
            }
        else:
            changes = {"status": "failed", "stage": "validation", "error": decision.reason}
        services.require_deadline(job)
        Job.objects.filter(pk=job.pk).update(
            **changes,
            stage_fence=F("stage_fence") + 1,
            lease_hash="",
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
        services.event(
            job,
            decision.reason,
            stage=changes["stage"],
            level="info" if decision.action == "promote" else "warning",
            data={
                "candidate_id": str(candidate.pk),
                "version_id": str(version.pk),
                "outcome": decision.outcome,
            },
        )
    return version


def recover_pending():
    recovered, errors = [], []
    for candidate in Candidate.objects.filter(committed=False):
        try:
            finalize_intent(candidate)
            recovered.append(str(candidate.pk))
        except (OSError, ValueError) as exc:
            errors.append({"candidate_id": str(candidate.pk), "error": type(exc).__name__})
    return {"recovered": recovered, "errors": errors}
