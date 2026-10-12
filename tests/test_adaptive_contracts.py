"""Verified effects, durable history and constrained supervisor decisions."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from prompt2play.application.progress import defect_ids, failure_category, observe
from prompt2play.contracts.adaptive import (
    initial_contracts,
    revise_design,
    revise_execution,
    validate_adaptive,
)
from prompt2play.generation.supervisor import validate_decision
from prompt2play.paths import RESOURCE_ROOT


def contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = RESOURCE_ROOT / "runtime/examples/dom"
    spec = json.loads((root / "spec.json").read_text())
    plan = {
        **json.loads((root / "plan.json").read_text()),
        **json.loads((Path(__file__).parent / "fixtures/design-contract.json").read_text()),
    }
    return initial_contracts("Make a detailed game", spec, plan), spec, plan


def report(case: str = "move", *, passed: bool = False) -> dict[str, Any]:
    return {
        "status": "passed" if passed else "failed",
        "checks": [
            {
                "name": "mechanics:1280",
                "status": "passed" if passed else "failed",
                "evidence": {
                    "cases": [
                        {
                            "id": case,
                            "actions": ["MOVE"],
                            "passed": passed,
                            "failed_assertions": []
                            if passed
                            else [{"path": "/moves", "op": "greater", "passed": False}],
                        }
                    ]
                },
            }
        ],
    }


def test_progress_requires_same_test_and_verified_effect_not_source_edits() -> None:
    state, _, _ = contracts()
    a = observe(state, "browser", report(), source_id="old", suite_id="one", cost={})
    assert a["progress"] == "unknown"
    b = observe(state, "browser", report(), source_id="changed", suite_id="one", cost={})
    assert b["progress"] == "neutral" and not b["resolved"]
    c = observe(
        state, "browser", report(passed=True), source_id="changed", suite_id="other", cost={}
    )
    assert c["progress"] == "unknown", "A changed test is not evidence of repairing the old defect"
    d = observe(state, "browser", report(passed=True), source_id="changed", suite_id="one", cost={})
    assert d["progress"] == "measured" and d["resolved"] == a["defects"]
    cached = observe(
        state,
        "browser",
        {**report(passed=True), "cached": True},
        source_id="changed",
        suite_id="one",
        cost={},
    )
    assert cached["progress"] == "neutral"


def test_different_failed_mechanics_are_visible_and_regression_is_not_progress() -> None:
    state, _, _ = contracts()
    a = observe(state, "browser", report(), source_id="a", suite_id="one", cost={})
    b = observe(state, "browser", report("weapon"), source_id="b", suite_id="one", cost={})
    assert b["new"] and b["resolved"] == a["defects"]
    # Partial verified improvements remain identifiable despite a new defect.
    assert b["progress"] == "measured"


def test_same_defect_requests_diagnosis_without_a_global_operation_limit() -> None:
    state, _, _ = contracts()
    for i in range(40):
        observe(state, "author", {"status": "applied"}, source_id=str(i), suite_id="", cost={})
    assert state["supervisor_due"] == ""
    for i in range(3):
        observe(state, "browser", report(), source_id=str(i), suite_id="one", cost={})
    assert "without verified progress" in state["supervisor_due"]


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("infrastructure", "infrastructure"),
        ("provider", "provider"),
        ("test_scenario", "scenario_defect"),
        ("plan_conflict", "plan_conflict"),
        ("contract_incompatibility", "contract_incompatibility"),
    ],
)
def test_typed_infrastructure_and_contract_failures(scope: str, expected: str) -> None:
    assert failure_category({"scope": scope}) == expected


def test_game_and_precondition_failures_have_separate_diagnoses() -> None:
    assert failure_category(report()) == "game_defect"
    value = report()
    value["checks"][0]["evidence"]["cases"][0]["error"] = "Selector #level is not reachable"
    assert failure_category(value) == "scenario_defect"
    assert failure_category({}) == "unknown"
    assert defect_ids({"checks": "bad", "review": None}) == []


def test_versions_are_immutable_and_requirements_and_oracles_cannot_be_changed() -> None:
    state, spec, plan = contracts()
    validate_adaptive(state, spec, plan)
    before = copy.deepcopy(state["versions"])
    changed = copy.deepcopy(plan)
    changed["visual_design"]["composition"]["mobile"] += " Larger touch targets."
    revise_design(state, spec, changed)
    validate_adaptive(state, spec, changed)
    assert state["versions"][: len(before)] == before
    assert state["design"]["parent"] == before[2]["id"]
    with pytest.raises(ValueError, match="must change"):
        revise_design(state, spec, changed)
    with pytest.raises(ValueError, match="user decision"):
        revise_design(state, {**spec, "rules": ["Win immediately"]}, changed)
    weakened = copy.deepcopy(changed)
    weakened["mechanics"][0]["desktop"]["assertions"][0]["path"] = "/score"
    with pytest.raises(ValueError, match="protected"):
        revise_design(state, spec, weakened)
    state["versions"][0]["payload"]["request"] = "Changed afterwards"
    with pytest.raises(ValueError, match="Modified immutable"):
        validate_adaptive(state, spec, changed)


def test_execution_verification_cites_evidence_and_invalidates_when_source_changes() -> None:
    state, spec, plan = contracts()
    task = state["execution"]["payload"]["items"][0]["id"]
    evidence = observe(
        state, "browser_check", report(passed=True), source_id="source", suite_id="suite", cost={}
    )
    revise_execution(state, {task: [evidence["id"]]})
    validate_adaptive(state, spec, plan)
    assert state["execution"]["payload"]["items"][0]["state"] == "verified"
    revise_execution(state, {})
    assert state["execution"]["payload"]["items"][0]["state"] == "waiting"


@pytest.mark.parametrize("violation", ["observations", "files", "task", "plan", "publish"])
def test_supervisor_cannot_invent_evidence_exceed_scope_or_publish(violation: str) -> None:
    state, _, _ = contracts()
    o = observe(state, "browser", report(), source_id="source", suite_id="suite", cost={})
    value = {
        "action": "repair_code",
        "reason": "Fix held movement",
        "observation_ids": [o["id"]],
        "affected_files": ["game.js"],
        "task_ids": ["mechanic:move"],
        "plan_json": "",
    }
    validate_decision(value, state, {"game.js"})
    if violation == "observations":
        value["observation_ids"] = ["invented"]
    elif violation == "files":
        value["affected_files"] = ["../../server.py"]
    elif violation == "task":
        value["task_ids"] = ["change-budget"]
    elif violation == "plan":
        value["plan_json"] = "{}"
    else:
        value["action"] = "publish"
    with pytest.raises(ValueError):
        validate_decision(value, state, {"game.js"})
