"""Small native contracts with lossless adoption of the donor's semantic plan."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import jsonschema

JSON = dict[str, Any]


class ContractError(ValueError):
    """A model declaration is unsuitable for further generation."""


def stable(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(stable(value).encode()).hexdigest()


def obj(properties: JSON) -> JSON:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


STRING: JSON = {"type": "string", "minLength": 1, "maxLength": 4000}
STRINGS: JSON = {"type": "array", "items": STRING, "maxItems": 24}
CAPABILITIES = ("input", "lifecycle", "clock", "audio", "storage")
GAME_SPEC_SCHEMA = obj(
    {
        "schema_version": {"type": "integer", "enum": [1]},
        "title": STRING,
        "summary": STRING,
        "genre": STRING,
        "presentation_mode": {"type": "string", "enum": ["canvas", "dom", "hybrid"]},
        "rules": {**STRINGS, "minItems": 1},
        "controls": {**STRINGS, "minItems": 1},
        "win_condition": STRING,
        "lose_condition": {"type": "string", "maxLength": 4000},
        "capabilities": {
            "type": "array",
            "items": {"type": "string", "enum": list(CAPABILITIES)},
            "uniqueItems": True,
        },
        "state_fields": {
            "type": "array",
            "minItems": 1,
            "maxItems": 48,
            "items": obj(
                {
                    "path": STRING,
                    "meaning": STRING,
                    "type": {
                        "type": "string",
                        "enum": ["string", "number", "integer", "boolean", "object", "array"],
                    },
                }
            ),
        },
        "actions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 24,
            "items": obj({"type": STRING, "effect": STRING}),
        },
        "invariants": STRINGS,
    }
)
STEP_SCHEMA = obj(
    {
        "kind": {"type": "string", "enum": ["key", "click", "tap", "drag", "wait"]},
        "key": {"type": "string"},
        "selector": {"type": "string"},
        "from_selector": {"type": "string"},
        "to_selector": {"type": "string"},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "ms": {"type": "integer", "minimum": 0, "maximum": 1000},
        "from": obj(
            {
                "x": {"type": "number", "minimum": 0, "maximum": 4096},
                "y": {"type": "number", "minimum": 0, "maximum": 4096},
            }
        ),
        "to": obj(
            {
                "x": {"type": "number", "minimum": 0, "maximum": 4096},
                "y": {"type": "number", "minimum": 0, "maximum": 4096},
            }
        ),
    }
)
ACCEPTANCE_SCHEMA = obj(
    {
        "start_selector": STRING,
        "restart_selector": STRING,
        "desktop": obj(
            {
                "steps": {"type": "array", "minItems": 1, "maxItems": 64, "items": STEP_SCHEMA},
                "completion": obj({"path": STRING, "one_of": {**STRINGS, "minItems": 1}}),
            }
        ),
        "touch": obj(
            {
                "steps": {"type": "array", "minItems": 1, "maxItems": 64, "items": STEP_SCHEMA},
                "completion": obj({"path": STRING, "one_of": {**STRINGS, "minItems": 1}}),
            }
        ),
    }
)
BUILD_PLAN_SCHEMA = obj(
    {
        "schema_version": {"type": "integer", "enum": [1]},
        "format": {"type": "string", "enum": ["runtime-v1", "legacy-four-module-v1"]},
        "files": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": obj({"path": STRING, "purpose": STRING, "dependencies": STRINGS}),
        },
        "acceptance_criteria": {**STRINGS, "minItems": 1},
        "input_acceptance": ACCEPTANCE_SCHEMA,
        "visual_direction": STRING,
        "audio_direction": {"type": "string", "maxLength": 4000},
    }
)
PLAN_SCHEMA = obj({"game_spec": GAME_SPEC_SCHEMA, "build_plan": BUILD_PLAN_SCHEMA})


def validate(value: JSON, schema: JSON, label: str) -> None:
    try:
        if len(stable(value).encode()) > 100_000:
            raise ContractError(f"{label} exceeds 100 KB")
        jsonschema.validate(value, schema)
    except (jsonschema.ValidationError, TypeError, ValueError, RecursionError) as exc:
        raise ContractError(f"Invalid {label}: {str(exc)[:200]}") from exc


@dataclass(frozen=True)
class GameSpec:
    data: JSON

    def __post_init__(self) -> None:
        validate(self.data, GAME_SPEC_SCHEMA, "GameSpec")
        if not {"input", "lifecycle"}.issubset(self.data["capabilities"]):
            raise ContractError("GameSpec requires input and lifecycle capabilities")
        paths = [field["path"] for field in self.data["state_fields"]]
        if any(not path.startswith("/") for path in paths) or len(set(paths)) != len(paths):
            raise ContractError("State fields need unique JSON-pointer paths")
        actions = [action["type"] for action in self.data["actions"]]
        if len(set(actions)) != len(actions):
            raise ContractError("Action names must be unique")
        object.__setattr__(self, "data", copy.deepcopy(self.data))

    @property
    def sha256(self) -> str:
        return digest(self.data)


@dataclass(frozen=True)
class BuildPlan:
    data: JSON

    def __post_init__(self) -> None:
        normalized = copy.deepcopy(self.data)
        for surface in ("desktop", "touch"):
            for step in normalized.get("input_acceptance", {}).get(surface, {}).get("steps", []):
                # Earlier v1 plans lacked drag fields; preserve their readable
                # identity while normalizing the extended declarative contract.
                step.setdefault("from", {"x": 0, "y": 0})
                step.setdefault("to", {"x": 0, "y": 0})
                step.setdefault("from_selector", "")
                step.setdefault("to_selector", "")
        object.__setattr__(self, "data", normalized)
        validate(self.data, BUILD_PLAN_SCHEMA, "BuildPlan")
        paths = {item["path"] for item in self.data["files"]}
        if len(paths) != len(self.data["files"]):
            raise ContractError("BuildPlan file paths must be unique")
        if any(not set(item["dependencies"]).issubset(paths) for item in self.data["files"]):
            raise ContractError("Dependencies must name planned files")
        if self.data["format"] == "runtime-v1" and "game.js" not in paths:
            raise ContractError("runtime-v1 requires game.js")
        for surface in ("desktop", "touch"):
            acceptance = self.data["input_acceptance"][surface]
            if not any(step["kind"] != "wait" for step in acceptance["steps"]):
                raise ContractError("Acceptance must include actual input")
            for step in acceptance["steps"]:
                if step["kind"] == "key" and not step["key"]:
                    raise ContractError("Key input requires a key")
                if step["kind"] == "click" and not step["selector"]:
                    raise ContractError("Click input requires a selector")
                if step["kind"] == "drag":
                    selectors = (step["from_selector"], step["to_selector"])
                    if any(selectors) and (not all(selectors) or selectors[0] == selectors[1]):
                        raise ContractError("Drag input requires distinct start and end selectors")
                    if not all(selectors) and step["from"] == step["to"]:
                        raise ContractError("Drag input requires distinct start and end points")
        object.__setattr__(self, "data", copy.deepcopy(self.data))

    @property
    def sha256(self) -> str:
        return digest(self.data)

    def expand_dependencies(self, changed: set[str]) -> set[str]:
        """Include all direct and transitive consumers of changed interfaces."""
        expanded = set(changed)
        while True:
            consumers = {
                item["path"] for item in self.data["files"] if set(item["dependencies"]) & expanded
            }
            if consumers.issubset(expanded):
                return expanded
            expanded.update(consumers)


def split_legacy_plan(plan: JSON) -> tuple[GameSpec, BuildPlan]:
    """Keep the semantic declaration unchanged in provenance; split its concerns."""
    from prompt2play.legacy.worker.core import validate_semantic_contract

    legacy_validator: Any = validate_semantic_contract
    contract = legacy_validator(plan["semantic_contract"])
    capabilities = ["input", "lifecycle"]
    if contract["timing"]["mode"] == "fixed_step":
        capabilities.append("clock")
    if contract.get("persistence"):
        capabilities.append("storage")
    if plan.get("audio_direction", "").strip().lower() not in ("", "none", "no audio", "silent"):
        capabilities.append("audio")
    game = GameSpec(
        {
            "schema_version": 1,
            **{
                key: plan[key]
                for key in (
                    "title",
                    "summary",
                    "genre",
                    "rules",
                    "controls",
                    "win_condition",
                    "lose_condition",
                )
            },
            "presentation_mode": plan.get("presentation_mode", "canvas"),
            "capabilities": capabilities,
            "state_fields": [
                {"path": field["path"], "meaning": field["meaning"], "type": field["type"]}
                for field in contract["fields"]
                if field["type"] != "null"
            ],
            "actions": [{"type": "dispatch", "effect": plan["action_schema"]}],
            "invariants": [item["statement"] for item in contract["invariants"]],
        }
    )
    step = {
        "kind": "key",
        "key": "ArrowRight",
        "selector": "",
        "x": 0,
        "y": 0,
        "ms": 0,
        "from": {"x": 0, "y": 0},
        "to": {"x": 0, "y": 0},
    }
    acceptance = {
        "start_selector": '[data-testid="start"]',
        "restart_selector": '[data-testid="restart"]',
        "desktop": {"steps": [step], "completion": {"path": "/phase", "one_of": ["won", "lost"]}},
        "touch": {
            "steps": [{**step, "kind": "tap", "selector": "canvas"}],
            "completion": {"path": "/phase", "one_of": ["won", "lost"]},
        },
    }
    build = BuildPlan(
        {
            "schema_version": 1,
            "format": "legacy-four-module-v1",
            "files": [
                {
                    "path": name,
                    "purpose": name.removesuffix(".js"),
                    "dependencies": [
                        other
                        for other in ("engine.js", "renderer.js", "audio.js", "ui.js")
                        if other != name
                    ],
                }
                for name in ("engine.js", "renderer.js", "audio.js", "ui.js")
            ],
            "acceptance_criteria": plan["acceptance_criteria"],
            "input_acceptance": acceptance,
            "visual_direction": plan["visual_direction"],
            "audio_direction": plan["audio_direction"],
        }
    )
    return game, build
