"""Decide what to do with evidence, independently of a model's response/status."""

import re

from validation.checks import VERSION, gates_verified, review_checks
from validation.contracts import implementation_hash

HARD_FAILURES = {"javascript_syntax", "runtime_or_network", "canvas_missing", "mobile_overflow", "module_not_registered", "control_obstructed"}
CHECK_PROBLEMS = {"invalid_check", "check_unverified", "check_timeout", "incomplete_checks", "surface_not_observed", "input_obstructed", "effect_not_causal", "effect_mismatch", "uncovered_requirements", "missing_effects", "missing_mobile_start", "missing_mobile_control"}


def complete_requirements(checks):
    from generation.errors import ContractError
    from generation.schema import validate_checks

    try:
        validate_checks(checks)
    except ContractError:
        return False
    return bool(checks)


def assess(result, checks, corrections):
    findings = result.get("findings", [])
    codes = {f.get("code") for f in findings}
    gates_passed = gates_verified(result, checks)
    # Unknown evidence is not permission to rewrite a saved game.
    action = "review"
    if result["status"] == "infrastructure_error" or codes & {"browser_error"}:
        action = "recheck"
    elif codes & HARD_FAILURES:
        action = "repair"
    elif codes & {"surface_unverified"}:
        action = "recheck"
    elif result["status"] == "passed":
        action = "accept"
    elif result["status"] == "unverified" or codes & CHECK_PROBLEMS:
        # A model-authored assertion does not independently establish a code defect.
        action = "review"
    unresolved = {f.get("check_id") for f in findings if f.get("check_id")}
    if codes & {"scene_visually_unverified", "check_suite_revised"}:
        unresolved.update(c["id"] for c in checks)
    return {
        "version": VERSION, "action": action, "gates_passed": gates_passed,
        "validator_hash": implementation_hash(),
        "requirements": [{key: c[key] for key in ("id", "category", "requirement")} for c in checks],
        "outstanding": [c["requirement"] for c in checks if c["id"] in unresolved]
        or (["Проверьте игровой результат вручную."] if action == "review" else []),
        "corrections": corrections,
        "artifact_evidence": result.get("artifact_evidence"),
        "requirement_coverage": result.get("requirement_coverage", {}),
        "coverage": result.get("coverage") or {"scope": "model_proposals_only", "natural_language_request_verified": False},
    }


def confirmation_report(run):
    """Fast evidence gate for serialization; the POST also checks the live identity."""
    if run.status in (*run.ACTIVE, "cancelled", "unknown", "succeeded") or not run.candidate_revision_id:
        return None
    from .models import Chat

    if (not Chat.objects.filter(pk=run.chat_id, current_revision_id=run.base_revision_id).exists()
            or run.chat.runs.filter(status__in=run.ACTIVE).exists()):
        return None
    report = run.candidate_revision.reports.order_by("-id").first()
    if report is None:
        return None
    evidence = report.assessment
    checks, _ = review_checks(run.candidate_revision.checks)
    if (
        evidence.get("version") != VERSION or evidence.get("validator_hash") != implementation_hash()
        or evidence.get("action") != "review" or evidence.get("gates_passed") is not True
        or not complete_requirements(checks) or not evidence.get("requirements")
        or evidence.get("requirement_coverage", {}).get("uncovered")
        or report.checks != checks or report.status != "unverified"
    ):
        return None
    return report


def repeated_failure(run, report):
    from .services import fingerprint

    reports = list(run.check_reports.order_by("-id")[:2])
    if len(reports) != 2 or reports[0].id != report.id:
        return False

    def signature(item):
        if item.status != "failed" or not item.findings:
            return None
        findings = []
        for finding in item.findings:
            symptom = {k: finding[k] for k in ("code", "check_id", "before", "after", "expected") if k in finding}
            if finding.get("location") == "source":
                # Compilation reports the first blocker. Fixing it can expose an identical
                # error elsewhere; a proven source location distinguishes those defects.
                if finding.get("source_anchor"):
                    symptom["source"] = {"path": finding.get("path"), "anchor": finding["source_anchor"]}
                else:
                    symptom["source"] = {k: finding[k] for k in ("path", "line", "column") if k in finding}
            elif finding.get("code") == "javascript_syntax" and type(finding.get("script_index")) is int:
                # The compiler's script identity is still known when source mapping is unavailable.
                symptom["script"] = {k: finding[k] for k in ("script_index", "script_line", "script_column") if k in finding}
            if finding.get("errors"):
                symptom["errors"] = [str(error).splitlines()[0] for error in finding["errors"]]
            elif finding.get("code") == "javascript_syntax":
                message = str(finding.get("message", ""))
                root = re.search(r"SyntaxError:.*", message)
                symptom["error"] = root.group() if root else message
            findings.append(symptom)
        return fingerprint({"checks": item.checks,
                            "findings": findings,
                            "passed": sorted(f["id"] for f in item.facts if f.get("status") == "passed")})

    first, second = (signature(item) for item in reports)
    return first is not None and first == second


def best_failed_candidate(run, latest):
    """Retain a previous candidate only with a strict, comparable evidence advantage."""
    best = latest
    for report in run.check_reports.select_related("revision").order_by("id"):
        if report.checks != latest.checks or report.status == "infrastructure_error":
            continue
        passed = {f["id"] for f in report.facts if f.get("status") == "passed"}
        best_passed = {f["id"] for f in best.facts if f.get("status") == "passed"}
        hard = bool({f.get("code") for f in report.findings} & HARD_FAILURES)
        best_hard = bool({f.get("code") for f in best.findings} & HARD_FAILURES)
        if (not hard and best_hard) or hard == best_hard and passed > best_passed:
            best = report
    return best.revision
