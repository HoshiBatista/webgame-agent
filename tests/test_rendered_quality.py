"""Image review contracts; fixtures never count as an AI visual judgement."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from prompt2play.contracts.adaptive import version
from prompt2play.generation.coverage import validate_coverage
from prompt2play.generation.rendered_quality import AREAS, validate_rendered


def rendered() -> dict[str, Any]:
    return {
        "criteria": {
            area: {
                "status": "ready",
                "observation": "Authored contract fixture",
                "frame": "start-1280.png",
                "element": "game board",
                "required_change": "",
            }
            for area in AREAS
        },
        "unverified_states": [],
    }


def test_material_defect_blocks_art_and_unobserved_states_require_human() -> None:
    value = rendered()
    assert validate_rendered(value, {"start-1280.png"}) == "rendered_ready"
    value["unverified_states"] = ["Upgrade menu"]
    assert validate_rendered(value, {"start-1280.png"}) == "human_required"
    value["criteria"]["composition"].update(
        status="needs_revision", required_change="Separate foreground units from background"
    )
    assert validate_rendered(value, {"start-1280.png"}) == "needs_revision"
    for changed in ("frame", "required_change"):
        invalid = copy.deepcopy(value)
        invalid["criteria"]["composition"][changed] = "missing.png" if changed == "frame" else ""
        with pytest.raises(ValueError):
            validate_rendered(invalid, {"start-1280.png"})


def test_requirement_coverage_cannot_cite_nonexistent_source_or_hide_missing_rules() -> None:
    requirements = version(
        "Requirements",
        {
            "items": [
                {"id": "request", "text": "Detailed game"},
                {"id": "rule:0", "text": "Weapons target enemies automatically"},
            ]
        },
    )
    value = {
        "requirements": {
            key: {
                "status": "implemented",
                "file": "game.js",
                "excerpt": "function attack()",
                "explanation": "Authored fixture",
            }
            for key in ("request", "rule:0")
        }
    }
    assert validate_coverage(value, requirements, {"game.js": "function attack(){}"}) == "covered"
    value["requirements"]["rule:0"]["status"] = "missing"
    assert (
        validate_coverage(value, requirements, {"game.js": "function attack(){}"})
        == "needs_revision"
    )
    value["requirements"]["rule:0"]["status"] = "unverified"
    assert (
        validate_coverage(value, requirements, {"game.js": "function attack(){}"})
        == "human_required"
    )
    value["requirements"]["request"]["excerpt"] = "invented implementation"
    with pytest.raises(ValueError):
        validate_coverage(value, requirements, {"game.js": "function attack(){}"})
