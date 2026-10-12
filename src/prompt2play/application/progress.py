"""Evidence identities and deterministic progress; source edits alone prove nothing."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from prompt2play.contracts.models import digest


def defect_ids(report: Mapping[str, Any]) -> list[str]:
    result: set[str] = set()
    checks = report.get("checks", report.get("findings", []))
    review = report.get("review", {})
    issues = (review.get("issues") or []) if isinstance(review, dict) else []
    structured_criteria = False
    for container in (report, review):
        if not isinstance(container, dict):
            continue
        for group in ("criteria", "requirements"):
            criteria = container.get(group, {})
            if not isinstance(criteria, dict):
                continue
            for name, item in criteria.items():
                if not isinstance(item, dict) or item.get("status") not in (
                    "ready",
                    "implemented",
                    "needs_revision",
                    "missing",
                    "unverified",
                ):
                    continue
                structured_criteria = True
                if item["status"] not in ("ready", "implemented"):
                    # Review prose, source excerpts and frame hashes change after an edit.
                    # Only resolving the same criterion establishes review progress.
                    result.add(digest({"review_group": group, "criterion": name}))
    for check in [*(checks if isinstance(checks, list) else []), *issues]:
        if not isinstance(check, dict) or check.get("status") in ("passed", "skipped"):
            continue
        base = {k: check.get(k) for k in ("name", "scope", "affected_files", "contract_ids")}
        evidence = check.get("evidence") or {}
        cases = evidence.get("cases", []) if isinstance(evidence, dict) else []
        failed = [c for c in cases if isinstance(c, dict) and c.get("passed") is not True]
        if failed:
            for case in failed:
                assertions = [
                    {k: q.get(k) for k in ("path", "op", "after_step", "before_step")}
                    for q in (case.get("observations") or case.get("failed_assertions") or [])
                    if isinstance(q, dict) and q.get("passed") is not True
                ]
                result.add(
                    digest(
                        {
                            **base,
                            "case": case.get("id"),
                            "actions": case.get("actions"),
                            "assertions": assertions,
                            "error": stable_error(case.get("error", "")),
                        }
                    )
                )
        else:
            result.add(digest({**base, "message": stable_error(check.get("message", ""))}))
    if not structured_criteria:
        for error in report.get("errors", []):
            result.add(digest({"error": stable_error(error)}))
    return sorted(result)


def supervisor_problem(state: Mapping[str, Any]) -> str:
    relevant = {
        "browser_check",
        "independent_validation",
        "visual_review",
        "coverage_review",
        "rendered_review",
    }
    latest = {}
    progress_epoch = 0
    for observation in state["observations"]:
        if observation["action"] in relevant:
            latest[observation["action"]] = observation
            if observation["progress"] == "measured":
                progress_epoch = observation["sequence"]
    return digest(
        {
            "trigger": state["supervisor_due"],
            "defects": sorted({f for o in latest.values() for f in o["defects"]}),
            "progress_epoch": progress_epoch,
        }
    )


def stable_error(value: Any) -> str:
    # Observed numbers, durations and stack line numbers are evidence, not identities.
    return re.sub(r"\b\d+(?:\.\d+)?\b", "#", str(value).split("\n")[0])[:1000]


def incomplete_report(report: Mapping[str, Any]) -> bool:
    """Recognize new metadata and saved reports from before it was propagated."""
    if report.get("incomplete") is True or report.get("scope") == "infrastructure":
        return True
    checks = report.get("checks", report.get("findings", []))
    if not isinstance(checks, list):
        return False
    return any(
        isinstance(check, dict)
        and (
            check.get("name") in ("browser_progress_stalled", "isolated_browser_runtime")
            or (
                isinstance(check.get("evidence"), dict)
                and check["evidence"].get("incomplete") is True
            )
        )
        for check in checks
    )


def failure_category(report: Mapping[str, Any]) -> str:
    scope = report.get("scope")
    if scope in ("infrastructure", "provider", "contract_incompatibility", "plan_conflict"):
        return str(scope)
    if scope == "test_scenario":
        return "scenario_defect"
    findings = report.get("findings", report.get("checks", []))
    for finding in findings if isinstance(findings, list) else []:
        evidence = finding.get("evidence") or {}
        for case in evidence.get("cases", []) if isinstance(evidence, dict) else []:
            if case.get("error") and "selector" in case["error"].lower():
                return "scenario_defect"
            if any(
                q.get("passed") is False
                for q in case.get("observations", case.get("failed_assertions", []))
            ):
                return "game_defect"
    return "unknown"


def observe(
    state: dict[str, Any],
    action: str,
    report: dict[str, Any],
    *,
    source_id: str,
    suite_id: str,
    cost: dict[str, Any],
) -> dict[str, Any]:
    observations = state["observations"]
    prior = next(
        (o for o in reversed(observations) if o["action"] == action and o["suite_id"] == suite_id),
        None,
    )
    # An interrupted run cannot replace the comparison baseline. Otherwise a
    # later unchanged full report would "resolve" only the interruption itself.
    baseline = next(
        (
            o
            for o in reversed(observations)
            if o["action"] == action
            and o["suite_id"] == suite_id
            and not o.get("incomplete", incomplete_report(o.get("evidence", {})))
        ),
        None,
    )
    incomplete = incomplete_report(report)
    defects = defect_ids(report)
    comparable = prior is not None
    if incomplete and prior:
        # Untested prior defects remain open; absence is not a passing observation.
        defects = sorted(set(prior["defects"]) | set(defects))
    resolved = (
        sorted(set(baseline["defects"]) - set(defects)) if baseline and not incomplete else []
    )
    added = sorted(set(defects) - set(prior["defects"])) if prior else defects
    successful = ("passed", "rendered_ready", "source_ready", "covered")
    reference = baseline or prior
    terminal = report.get("status") in (*successful, "failed", "needs_revision")
    # A changed test, a source hash, or a cached report cannot be counted as improvement.
    measured = (
        terminal
        and not incomplete
        and not report.get("cached")
        and (
            bool(resolved)
            or (
                reference is not None
                and reference["status"] not in successful
                and report["status"] in successful
            )
        )
    )
    value = {
        "sequence": len(observations) + 1,
        "action": action,
        "plan_id": state["design"]["id"],
        "execution_id": state["execution"]["id"],
        "draft_id": source_id,
        "suite_id": suite_id,
        "status": report.get("status", "unknown"),
        "incomplete": incomplete,
        "category": failure_category(report),
        "defects": defects,
        "resolved": resolved,
        "new": added,
        "progress": "measured"
        if measured
        else "regressed"
        if comparable and added
        else "unknown"
        if not comparable
        else "neutral",
        "evidence": {
            k: copy.deepcopy(report[k])
            for k in (
                "diagnostic_key",
                "artifact",
                "findings",
                "checks",
                "frames",
                "review",
                "errors",
                "message",
                "passed_checks",
                "criteria",
                "error",
                "incomplete",
            )
            if k in report
        },
        "cost": copy.deepcopy(cost),
    }
    value["id"] = digest(value)
    observations.append(value)
    stall = state["stall"].get(action, {})
    fingerprint = digest(
        {"defects": defects, "error": stable_error(report.get("error", "")), "suite": suite_id}
    )
    unsuccessful = bool(
        incomplete
        or defects
        or report.get("error")
        or report.get("status") in ("failed", "unverified", "rejected", "needs_revision")
    )
    repeats = (
        (
            stall.get("repeats", 0) + 1
            if (
                stall.get("fingerprint") == fingerprint
                or (
                    prior is not None
                    and stall.get("suite_id") == suite_id
                    and (incomplete or prior.get("incomplete", False))
                )
            )
            else 1
        )
        if unsuccessful and not measured
        else 0
    )
    state["stall"][action] = {"fingerprint": fingerprint, "repeats": repeats, "suite_id": suite_id}
    if repeats >= 3:
        state["supervisor_due"] = "Repeated " + action + " failure without verified progress"
    return value
