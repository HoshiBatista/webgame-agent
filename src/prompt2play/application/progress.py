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
    for error in report.get("errors", []):
        result.add(digest({"error": stable_error(error)}))
    return sorted(result)


def stable_error(value: Any) -> str:
    # Observed numbers, durations and stack line numbers are evidence, not identities.
    return re.sub(r"\b\d+(?:\.\d+)?\b", "#", str(value).split("\n")[0])[:1000]


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
    defects = defect_ids(report)
    comparable = prior is not None
    resolved = sorted(set(prior["defects"]) - set(defects)) if prior else []
    added = sorted(set(defects) - set(prior["defects"])) if prior else defects
    terminal = report.get("status") in ("passed", "failed")
    # A changed test, a source hash, or a cached report cannot be counted as improvement.
    measured = (
        terminal
        and not report.get("cached")
        and (
            bool(resolved)
            or (prior is not None and prior["status"] != "passed" and report["status"] == "passed")
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
        defects
        or report.get("error")
        or report.get("status") in ("failed", "unverified", "rejected")
    )
    repeats = (
        (stall.get("repeats", 0) + 1 if stall.get("fingerprint") == fingerprint else 1)
        if unsuccessful and not measured
        else 0
    )
    state["stall"][action] = {"fingerprint": fingerprint, "repeats": repeats}
    if repeats >= 3:
        state["supervisor_due"] = "Repeated " + action + " failure without verified progress"
    return value
