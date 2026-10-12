"""Versioned requirements, protected expectations and evidence-backed work items."""

from __future__ import annotations

import copy
from typing import Any

from .mechanics import assertion_identity, preserve_mechanics, validate_mechanics
from .models import BuildPlan, GameSpec, digest

PIPELINE_VERSION = "adaptive-v1"


def version(kind: str, payload: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
    value = {"kind": kind, "payload": copy.deepcopy(payload), "parent": parent}
    return {**value, "id": digest(value)}


def initial_contracts(
    prompt: str,
    spec: dict[str, Any],
    plan: dict[str, Any],
    *,
    user_feedback: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    requirements = version(
        "Requirements",
        {
            "request": prompt,
            "items": [{"id": "request", "text": prompt}]
            + [{"id": "action:" + a["type"], "text": a["effect"]} for a in spec["actions"]]
            + [{"id": f"rule:{i}", "text": r} for i, r in enumerate(spec["rules"])]
            + [
                {"id": f"feedback:{i}", "text": item["text"]}
                for i, item in enumerate(user_feedback or [])
            ],
            "spec": spec,
            **({"user_feedback": copy.deepcopy(user_feedback)} if user_feedback else {}),
        },
    )
    acceptance = version(
        "AcceptanceContract",
        {
            "requirements_id": requirements["id"],
            "cases": [
                {
                    "id": c["id"],
                    "requirements": ["action:" + a for a in c["actions"]],
                    "devices": {
                        d: [assertion_identity(q) for q in c[d]["assertions"]]
                        for d in ("desktop", "touch")
                    },
                }
                for c in plan["mechanics"]
            ],
            "mandatory": ["startup", "input", "restart", "mechanics", "visual_review"],
        },
    )
    design = version(
        "DesignPlan", {"requirements_id": requirements["id"], "spec": spec, "plan": plan}
    )
    execution = version(
        "ExecutionPlan",
        {
            "design_id": design["id"],
            "acceptance_id": acceptance["id"],
            "items": [
                {
                    "id": "mechanic:" + c["id"],
                    "label": c["description"],
                    "requirements": ["action:" + a for a in c["actions"]],
                    "checks": [c["id"]],
                    "files": [f["path"] for f in plan["files"]],
                    "dependencies": [],
                    "state": "waiting",
                    "evidence": [],
                }
                for c in plan["mechanics"]
            ]
            + [
                {
                    "id": "coverage:" + item["id"],
                    "label": "Source coverage: " + item["text"],
                    "requirements": [item["id"]],
                    "checks": ["coverage_review"],
                    "files": [f["path"] for f in plan["files"]],
                    "dependencies": [],
                    "state": "waiting",
                    "evidence": [],
                }
                for item in requirements["payload"]["items"]
            ]
            + [
                {
                    "id": "art",
                    "label": "Rendered art and interface review on desktop and touch",
                    "requirements": ["request"],
                    "checks": ["visual_review"],
                    "files": [f["path"] for f in plan["files"]],
                    "dependencies": [],
                    "state": "waiting",
                    "evidence": [],
                }
            ],
        },
    )
    return {
        "version": PIPELINE_VERSION,
        "requirements": requirements,
        "acceptance": acceptance,
        "design": design,
        "execution": execution,
        "versions": [requirements, acceptance, design, execution],
        "observations": [],
        "decisions": [],
        "stall": {},
        "supervisor_due": "",
    }


def revise_design(state: dict[str, Any], spec: dict[str, Any], plan: dict[str, Any]) -> None:
    """Technical revisions cannot change user requirements or their acceptance oracle."""
    GameSpec(spec)
    BuildPlan(plan)
    if spec != state["requirements"]["payload"]["spec"]:
        raise ValueError("Changing game requirements needs an explicit user decision")
    previous = state["design"]["payload"]["plan"]
    if plan.get("mechanics_changes", []) != previous.get("mechanics_changes", []):
        raise ValueError(
            "Technical plan changes cannot introduce user-authorized mechanics changes"
        )
    validate_mechanics(plan["mechanics"], [a["type"] for a in spec["actions"]])
    preserve_mechanics(previous["mechanics"], plan["mechanics"])
    design = version(
        "DesignPlan",
        {"requirements_id": state["requirements"]["id"], "spec": spec, "plan": plan},
        state["design"]["id"],
    )
    if design["payload"] == state["design"]["payload"]:
        raise ValueError("Plan revision must change the proposed method")
    state["design"] = design
    state["versions"].append(design)
    revise_execution(state, {})


def revise_execution(state: dict[str, Any], verified: dict[str, list[str]]) -> None:
    old = state["execution"]
    payload = copy.deepcopy(old["payload"])
    payload["design_id"] = state["design"]["id"]
    for item in payload["items"]:
        item["state"] = "verified" if verified.get(item["id"]) else "waiting"
        item["evidence"] = verified.get(item["id"], [])
    if payload == old["payload"]:
        return
    current = version("ExecutionPlan", payload, old["id"])
    state["execution"] = current
    state["versions"].append(current)


def validate_adaptive(state: dict[str, Any], spec: dict[str, Any], plan: dict[str, Any]) -> None:
    if state.get("version") != PIPELINE_VERSION:
        raise ValueError("Unsupported adaptive checkpoint version")
    versions = state.get("versions", [])
    seen: set[str] = set()
    for entry in versions:
        if entry.get("id") != digest({k: entry[k] for k in ("kind", "payload", "parent")}):
            raise ValueError("Modified immutable contract version")
        if entry["parent"] is not None and entry["parent"] not in seen:
            raise ValueError("Contract version has a missing parent")
        seen.add(entry["id"])
    for name in ("requirements", "acceptance", "design", "execution"):
        if state[name]["id"] not in seen or state[name] not in versions:
            raise ValueError("Active contract is missing from version history")
    if state["design"]["payload"]["spec"] != spec or state["design"]["payload"]["plan"] != plan:
        raise ValueError("Draft is not bound to its active design version")
    if state["requirements"]["payload"]["spec"] != spec:
        raise ValueError("Game requirements changed without user approval")
    first_plan = next(v["payload"]["plan"] for v in versions if v["kind"] == "DesignPlan")
    expected = initial_contracts(
        state["requirements"]["payload"]["request"],
        spec,
        first_plan,
        user_feedback=state["requirements"]["payload"].get("user_feedback"),
    )
    if (
        state["requirements"] != expected["requirements"]
        or state["acceptance"] != expected["acceptance"]
    ):
        raise ValueError("Requirements or protected acceptance differ from their original design")
    preserve_mechanics(first_plan["mechanics"], plan["mechanics"])
    if plan.get("mechanics_changes", []) != first_plan.get("mechanics_changes", []):
        raise ValueError("User-authorized mechanics changes differ from the original revision")
    if (
        state["execution"]["payload"]["design_id"] != state["design"]["id"]
        or state["execution"]["payload"]["acceptance_id"] != state["acceptance"]["id"]
    ):
        raise ValueError("Execution plan is bound to obsolete contracts")
    observations = {o["id"]: o for o in state["observations"]}
    for o in observations.values():
        if o["id"] != digest({k: v for k, v in o.items() if k != "id"}):
            raise ValueError("Modified observation evidence")
    requirements = {r["id"] for r in state["requirements"]["payload"]["items"]}
    covered: set[str] = set()
    for item in state["execution"]["payload"]["items"]:
        if not item["checks"] or not set(item["requirements"]) <= requirements:
            raise ValueError("Execution item lacks requirement or acceptance traceability")
        covered.update(item["requirements"])
        if item["state"] not in ("waiting", "running", "verified", "blocked", "replaced"):
            raise ValueError("Invalid execution item state")
        if item["state"] == "verified" and not item["evidence"]:
            raise ValueError("Verified work requires evidence")
        if item["state"] == "verified" and any(
            e not in observations
            or observations[e]["plan_id"] != state["design"]["id"]
            or observations[e]["action"]
            not in ("browser_check", "coverage_review", "rendered_review")
            for e in item["evidence"]
        ):
            raise ValueError("Verified work references unavailable or obsolete evidence")
    if covered != requirements:
        raise ValueError("Execution plan omits requirements")
