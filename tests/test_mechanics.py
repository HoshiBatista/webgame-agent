"""Coverage and declarative assertions cannot be replaced by a launch smoke test."""

from __future__ import annotations

import copy
import json
from typing import Any, cast

import pytest

from prompt2play.adapters.django.forge.artifacts import artifact_manifest, require_report_binding
from prompt2play.contracts.mechanics import validate_mechanics
from prompt2play.paths import RESOURCE_ROOT


def matrix() -> list[dict[str, Any]]:
    return json.loads((RESOURCE_ROOT / "runtime/examples/dom/plan.json").read_text())["mechanics"]  # type: ignore[no-any-return]


def test_mechanics_cover_actions_and_keep_gameplay_assertions() -> None:
    assert validate_mechanics(matrix(), ["MOVE", "START", "RESTART"])[0]["id"] == "move"
    with pytest.raises(ValueError, match="Untested gameplay actions"):
        validate_mechanics(matrix(), ["SHOOT"])
    changed = matrix()
    changed[0]["desktop"]["assertions"][0]["path"] = "/phase"
    with pytest.raises(ValueError, match="gameplay"):
        validate_mechanics(changed, ["MOVE"])
    changed = matrix()
    changed[0]["continuous"] = True
    with pytest.raises(ValueError, match="hold, release"):
        validate_mechanics(changed, ["MOVE"])
    changed = matrix()
    changed[0]["desktop"]["steps"] = changed[0]["desktop"]["steps"][:1]
    changed[0]["desktop"]["assertions"] = changed[0]["desktop"]["assertions"][:1]
    with pytest.raises(ValueError, match="repeated"):
        validate_mechanics(changed, ["MOVE"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("after_step", 100),
        ("before_step", 20),
        ("op", "execute"),
        ("tolerance", float("nan")),
        ("path", "bad"),
        ("value_json", 0),
    ],
)
def test_malformed_assertions_rejected(field: str, value: Any) -> None:
    cases = matrix()
    cases[0]["desktop"]["assertions"][0][field] = value
    with pytest.raises(ValueError):
        validate_mechanics(cases, ["MOVE"])


def test_coordinator_refuses_missing_mechanics_in_passing_report() -> None:
    spec = {
        "mechanics_required": True,
        "mechanics_required_actions": ["MOVE"],
        "mechanics_acceptance": matrix(),
    }
    manifest = cast(Any, artifact_manifest)({}, "fixture", spec)
    report: dict[str, Any] = {
        "schema_version": 2,
        "status": "passed",
        "artifact": manifest,
        "checks": [],
    }
    with pytest.raises(ValueError, match="Missing required"):
        cast(Any, require_report_binding)({}, "fixture", spec, report)
    for width in (1280, 390):
        report["checks"].append(
            {
                "name": f"mechanics:{width}",
                "status": "passed",
                "artifact_sha256": manifest["html_sha256"],
                "evidence": {
                    "actual_input": True,
                    "cases": [
                        {"id": "move", "actions": ["MOVE"], "passed": True, "visible_changed": True}
                    ],
                },
            }
        )
    assert cast(Any, require_report_binding)({}, "fixture", spec, report) == manifest
    bad = copy.deepcopy(report)
    bad["checks"][0]["evidence"]["cases"][0]["actions"] = ["OTHER"]
    with pytest.raises(ValueError, match="Incomplete"):
        cast(Any, require_report_binding)({}, "fixture", spec, bad)


def test_continuous_controls_need_assertions_not_just_an_input_sequence() -> None:
    cases = matrix()
    case = cases[0]
    case["continuous"] = True
    case["keyboard_keys"] = ["ArrowRight"]
    case["desktop"]["steps"] = [
        {"kind": "key_down", "key": "ArrowRight"},
        {"kind": "wait", "ms": 100},
        {"kind": "key_up", "key": "ArrowRight"},
        {"kind": "wait", "ms": 100},
        {"kind": "key_down", "key": "ArrowRight"},
        {"kind": "wait", "ms": 100},
        {"kind": "key_up", "key": "ArrowRight"},
    ]
    check = {
        "after_step": 2,
        "before_step": 1,
        "path": "/x",
        "op": "greater",
        "value_json": "",
        "tolerance": 0,
    }
    case["desktop"]["assertions"] = [check]
    with pytest.raises(ValueError, match="Assertions must verify"):
        validate_mechanics(cases, ["MOVE"])
    case["desktop"]["assertions"] += [
        dict(check, after_step=4, before_step=3, op="equal"),
        dict(check, after_step=6, before_step=5),
    ]
    assert validate_mechanics(cases, ["MOVE"])


def test_revision_cannot_drop_previously_tested_mechanic_or_key() -> None:
    from prompt2play.contracts.mechanics import preserve_mechanics

    old = matrix()
    new = matrix()
    preserve_mechanics(old, new)
    new[0]["keyboard_keys"].pop()
    with pytest.raises(ValueError, match="Cannot drop"):
        preserve_mechanics(old, new)
