"""Pure promotion and bounded repair policy, independent of model assertions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

Outcome = Literal["passed", "failed", "unverified"]
Action = Literal["promote", "repair", "stop"]


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    action: Action
    reason: str


def decide(report: Mapping[str, object], attempt: int, max_repairs: int) -> Decision:
    raw_checks = report.get("checks", [])
    checks: Sequence[Mapping[str, object]] = (
        [item for item in raw_checks if isinstance(item, dict)]
        if isinstance(raw_checks, list)
        else []
    )
    # Only completion may be explicitly optional. Every other skipped check
    # still blocks release; manual playthrough is never presented as passed.
    if report.get("completion_required", True) is False:
        checks = [
            check
            for check in checks
            if not (
                check.get("name") in {"completion:1280", "completion:390"}
                and check.get("status") == "skipped"
            )
        ]
    if report.get("errors") or any(check.get("status") == "failed" for check in checks):
        action: Action = "repair" if attempt <= max_repairs else "stop"
        return Decision("failed", action, "Validation found blocking defects.")
    if (
        report.get("status") != "passed"
        or not checks
        or any(check.get("status") != "passed" for check in checks)
    ):
        return Decision("unverified", "stop", "A required validation check is missing or skipped.")
    names = {check.get("name") for check in checks}
    required = {
        f"{name}:{width}"
        for width in (1280, 390)
        for name in (
            "startup",
            "surface",
            "input",
            "completion",
            "restart",
            "javascript_errors",
            "external_requests",
            "evidence",
            "independent_acceptance",
        )
    } | {"mobile_layout:390"}
    if report.get("completion_required", True) is False:
        required -= {"completion:1280", "completion:390"}
    if not required.issubset(names):
        return Decision(
            "unverified", "stop", "Independent playability criteria have not all passed."
        )
    scope = report.get("scope", {})
    if (
        not isinstance(scope, dict)
        or scope.get("isolated") is not True
        or scope.get("real_input") is not True
    ):
        return Decision("unverified", "stop", "Isolated execution with real input is required.")
    if not report.get("suite_sha256") or not report.get("validator_image_sha256"):
        return Decision("unverified", "stop", "Validation suite and runner identity are required.")
    return Decision("passed", "promote", "Exact candidate passed all required checks.")


RepairStrategy = Literal["local", "structural", "replan", "regenerate", "stop"]


@dataclass(frozen=True)
class RepairRoute:
    strategy: RepairStrategy
    files: tuple[str, ...]
    fingerprint: str
    reason: str


def repair_route(
    report: Mapping[str, object],
    available_files: Sequence[str],
    previous_fingerprint: str | None = None,
) -> RepairRoute:
    """Route defects by scope; identical failed fixes cannot repeat indefinitely."""
    import hashlib
    import json

    checks_value = report.get("checks", [])
    checks = (
        [item for item in checks_value if isinstance(item, dict) and item.get("status") == "failed"]
        if isinstance(checks_value, list)
        else []
    )
    review = report.get("review", {})
    issues_value = review.get("issues", []) if isinstance(review, dict) else []
    issues = (
        [item for item in issues_value if isinstance(item, dict)]
        if isinstance(issues_value, list)
        else []
    )
    defects = checks + issues
    signature = {
        "errors": report.get("errors", []),
        "defects": [
            {
                key: defect.get(key)
                for key in ("name", "message", "scope", "affected_files", "contract_ids")
            }
            for defect in defects
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(signature, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    allowed = set(available_files)
    affected: set[str] = set()
    for defect in defects:
        raw_files = defect.get("affected_files", [])
        if isinstance(raw_files, list):
            affected.update(name for name in raw_files if isinstance(name, str) and name in allowed)
        single = defect.get("file")
        if isinstance(single, str) and single in allowed:
            affected.add(single)
    files = tuple(sorted(affected or allowed))
    if fingerprint == previous_fingerprint:
        return RepairRoute(
            "regenerate",
            tuple(sorted(allowed)),
            fingerprint,
            "The same failure survived a repair; regenerate a fresh candidate.",
        )
    scopes = {defect.get("scope") for defect in defects if isinstance(defect.get("scope"), str)}
    if "contract" in scopes or any(defect.get("contract_ids") for defect in defects):
        return RepairRoute(
            "replan",
            tuple(sorted(allowed)),
            fingerprint,
            "Contract or state ownership needs a revised build plan.",
        )
    if "integration" in scopes or len(files) > 1:
        return RepairRoute(
            "structural", files, fingerprint, "Repair the affected dependencies together."
        )
    return RepairRoute("local", files, fingerprint, "Repair the isolated generated module.")
