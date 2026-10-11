"""Contract boundaries preserve optional mechanics and declared dependency scope."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from prompt2play.contracts import BuildPlan, ContractError, GameSpec, split_legacy_plan
from prompt2play.paths import LEGACY_ROOT, RESOURCE_ROOT


def example(name: str = "dom") -> tuple[dict[str, Any], dict[str, Any]]:
    root = RESOURCE_ROOT / "runtime" / "examples" / name
    return json.loads((root / "spec.json").read_text()), json.loads(
        (root / "plan.json").read_text()
    )


def test_optional_capabilities_and_unique_observable_contracts() -> None:
    spec, _ = example()
    assert GameSpec(spec).data["capabilities"] == ["input", "lifecycle"]
    missing = copy.deepcopy(spec)
    missing["capabilities"] = ["audio"]
    with pytest.raises(ContractError, match="input and lifecycle"):
        GameSpec(missing)
    duplicate = copy.deepcopy(spec)
    duplicate["state_fields"].append(duplicate["state_fields"][0])
    with pytest.raises(ContractError, match="unique JSON-pointer"):
        GameSpec(duplicate)


def test_file_dependencies_expand_transitively_and_reject_unknown_references() -> None:
    _, plan = example()
    plan["files"] += [{"path": "style.css", "purpose": "Style", "dependencies": ["game.js"]}]
    assert BuildPlan(plan).expand_dependencies({"game.js"}) == {"game.js", "style.css"}
    plan["files"][1]["dependencies"] = ["outside.js"]
    with pytest.raises(ContractError, match="Dependencies"):
        BuildPlan(plan)


def test_acceptance_cannot_be_wait_only() -> None:
    _, plan = example()
    plan["input_acceptance"]["desktop"]["steps"] = [
        {"kind": "wait", "key": "", "selector": "", "x": 0, "y": 0, "ms": 10}
    ]
    with pytest.raises(ContractError, match="actual input"):
        BuildPlan(plan)


def test_drag_acceptance_has_real_distinct_coordinates() -> None:
    _, plan = example()
    step = {
        "kind": "drag",
        "key": "",
        "selector": "",
        "x": 0,
        "y": 0,
        "ms": 0,
        "from": {"x": 80, "y": 100},
        "to": {"x": 200, "y": 100},
    }
    plan["input_acceptance"]["desktop"]["steps"] = [step]
    assert BuildPlan(plan).data["input_acceptance"]["desktop"]["steps"][0]["kind"] == "drag"
    step["to"] = step["from"]
    with pytest.raises(ContractError, match="distinct"):
        BuildPlan(plan)


def test_legacy_plan_conversion_preserves_mechanics_without_inventing_optional_caps() -> None:
    legacy = json.loads((LEGACY_ROOT / "reference" / "corpus" / "lamps" / "spec.json").read_text())
    original = copy.deepcopy(legacy)
    spec, plan = split_legacy_plan(legacy)
    assert legacy == original
    assert spec.data["rules"] == legacy["rules"]
    assert plan.data["format"] == "legacy-four-module-v1"
    assert len(plan.data["files"]) == 4
