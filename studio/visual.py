"""One optional visual review/patch cycle, sharing the Run's existing budget."""

import base64
import hashlib

from django.utils import timezone

from generation.errors import ContractError
from generation.visual import contact_sheet, packet_hash, permitted_issues

from .models import Revision, Run


def save_state(run, **values):
    state = {**run.visual_state, **values}
    changed = Run.objects.filter(
        pk=run.id, fence=run.fence, cancel_requested=False, status__in=Run.ACTIVE
    ).update(visual_state=state)
    if changed:
        run.visual_state = state
    return bool(changed)


def skip(run, reason):
    save_state(run, phase="skipped", reason=reason)


def fallback(run):
    return Revision.objects.filter(pk=run.visual_state.get("base_revision"), chat_id=run.chat_id).first()


def next_step(run, base, report):
    if not run.visual_review_enabled or not run.allow_model_calls:
        return None
    phase = run.visual_state.get("phase")
    if phase in {"skipped", "done", "reverted"}:
        return None
    if phase == "patched":
        save_state(run, phase="done", result_revision=str(base.id))
        return None
    operation = "visual_patch" if phase == "patch_due" else "visual_review"
    needed = 1 if operation == "visual_patch" else 2
    if (
        run.max_model_calls - run.attempts < needed
        or run.model_call_deadline
        and timezone.now() >= run.model_call_deadline
    ):
        skip(run, "insufficient_budget_or_time")
        return None
    if phase not in {"review_due", "patch_due"}:
        from .continuations import lineage_ids
        from .models import Invocation

        if Invocation.objects.filter(
            run_id__in=list(lineage_ids(run)), request__operation="visual_review"
        ).exists():
            skip(run, "review_already_attempted")
            return None
        try:
            contact_sheet(
                report.visual_evidence, artifact_hash=base.artifact_hash, environment=report.environment
            )
        except Exception:
            skip(run, "missing_or_invalid_frames")
            return None
        save_state(
            run,
            phase="review_due",
            base_revision=str(base.id),
            report_id=report.id,
            report_identity=report.identity,
            packet_hash=packet_hash(report.visual_evidence),
        )
    return operation


def request_details(run, base):
    from .tasks import check_identity

    state = run.visual_state
    if base is None:
        raise ContractError("stale_visual_evidence", "Исходная версия больше недоступна.")
    report = base.reports.filter(pk=state.get("report_id")).first()
    if (
        not report
        or base.reports.order_by("-id").values_list("id", flat=True).first() != report.id
        or str(base.id) != state.get("base_revision")
        or report.status != "passed"
        or report.identity != state.get("report_identity")
        or report.identity != check_identity(base, report.environment)
        or state.get("packet_hash") != packet_hash(report.visual_evidence)
    ):
        raise ContractError("stale_visual_evidence", "Нет актуального пакета кадров проверенной игры.")
    sheet = contact_sheet(
        report.visual_evidence, artifact_hash=base.artifact_hash, environment=report.environment
    )
    binding = {
        "base_revision": str(base.id),
        "artifact_hash": base.artifact_hash,
        "report_id": report.id,
        "report_identity": report.identity,
        "packet_hash": sheet["packet_hash"],
        "sheet_hash": hashlib.sha256(base64.b64decode(sheet["data"])).hexdigest(),
        "requirement_ids": [
            "presentation",
            *[r["id"] for r in run.requirement_manifest.get("requirements", [])],
            *[c["id"] for c in base.checks],
        ],
    }
    operation = "visual_patch" if state["phase"] == "patch_due" else "visual_review"
    if operation == "visual_patch":
        binding.update(issues=state["issues"], paths=sorted({i["path"] for i in state["issues"]}))
    metadata = [{k: v for k, v in f.items() if k != "data"} for f in report.visual_evidence["frames"]]
    return {
        "operation": operation,
        operation: {**binding, "frames": metadata},
        "preview_image": {
            **sheet,
            **{
                k: binding[k]
                for k in ("base_revision", "artifact_hash", "report_id", "report_identity", "packet_hash")
            },
        },
        "validation_evidence": {
            "report_id": report.id,
            "artifact_hash": base.artifact_hash,
            "report_identity": report.identity,
            "semantics": report.visual_evidence["semantics"],
        },
    }


def accept_review(run, base, response, request):
    from generation.schema import response_schema, validate_response

    validate_response(response, operation="visual_review", schema=response_schema(request))
    current = request_details(run, base)["visual_review"]
    if current != request["visual_review"]:
        raise ContractError("stale_visual_evidence", "Пакет кадров изменился.")
    editable = {"game.js": base.files["game.js"]} if base.generation_profile == "compact" else base.files
    issues = permitted_issues(response, current, editable)
    save_state(
        run,
        phase="patch_due" if issues else "done",
        issues=issues,
        review=response,
        reason="" if issues else "no_admitted_defect",
    )
