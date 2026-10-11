"""Closed, bounded acceptance-test data language. No executable model test code."""

from __future__ import annotations

import copy
import json
import re

from .evidence import canonical_json

MAX_SCENARIOS = 8
MAX_STEPS = 64
MAX_FRAMES = 120_000
MAX_ACTIONS = 1_200
MAX_SAVES = 8
MAX_PERSISTENCE_OPERATIONS = 64
MAX_LIFECYCLE_OPERATIONS = 24
MAX_RELOADS = 8
FILES = {"engine.js", "renderer.js", "audio.js", "ui.js"}
CATEGORIES = {"progress", "lifecycle", "accounting", "strategy", "integration", "persistence"}
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")
DOM_PROPERTIES = {"focused", "text", "value", "disabled", "hidden", "count"}


def _keys(value, required, optional=()):
    if (
        not isinstance(value, dict)
        or not set(required).issubset(value)
        or set(value) - set(required) - set(optional)
    ):
        raise ValueError("QA object has missing or unsupported fields")


def _string(value, limit, label, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
        or "\x00" in value
    ):
        raise ValueError(f"QA {label} must be a bounded string")


def _identifier(value, label):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"QA {label} must be an identifier of 1–48 characters")


def _integer(value, lo, hi, label):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"QA {label} must be an integer from {lo} through {hi}")


def _json(value, *, max_bytes=8192):
    try:
        raw = canonical_json(value)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("QA values must contain finite JSON data") from exc
    if len(raw.encode("utf-8")) > max_bytes:
        raise ValueError("QA JSON value exceeds its byte bound")
    return value


def _pointer(value):
    _string(value, 256, "JSON pointer", empty=True)
    if value and not value.startswith("/"):
        raise ValueError("QA paths use JSON Pointer, for example /resources/gold")
    if re.search(r"~(?![01])", value):
        raise ValueError("QA JSON Pointer contains an invalid escape")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in value.split("/")[1:]]
    if any(p in {"__proto__", "prototype", "constructor"} for p in parts):
        raise ValueError("QA paths cannot address prototype properties")


def _operand(value, captures, depth=0):
    if depth > 4 or not isinstance(value, dict):
        raise ValueError("QA operand nesting exceeds the bound")
    keys = set(value)
    if keys == {"path"} or keys == {"saved", "path"}:
        _pointer(value["path"])
        if "saved" in value:
            _identifier(value["saved"], "capture reference")
            if value["saved"] not in captures:
                raise ValueError("QA assertion refers to a snapshot that has not been captured")
    elif keys == {"value"}:
        _json(value["value"])
    elif keys == {"sum"}:
        if not isinstance(value["sum"], list) or not 1 <= len(value["sum"]) <= 12:
            raise ValueError("QA sum requires 1–12 operands")
        for item in value["sum"]:
            _operand(item, captures, depth + 1)
    elif keys == {"count"}:
        _operand(value["count"], captures, depth + 1)
    elif keys == {"element", "property"}:
        _string(value["element"], 256, "selector")
        if not isinstance(value["property"], str) or value["property"] not in DOM_PROPERTIES:
            raise ValueError("QA DOM property is not supported")
    else:
        raise ValueError(
            "QA operand must be path, saved+path, value, sum, count, or element+property"
        )


def _observes_state(operand):
    """Literal arithmetic alone is not evidence of a game's behavior."""
    if "path" in operand or "element" in operand:
        return True
    if "sum" in operand:
        return any(_observes_state(value) for value in operand["sum"])
    if "count" in operand:
        return _observes_state(operand["count"])
    return False


def _observes_live_state(operand):
    """A prior capture is a baseline, not an observation after a transition."""
    if "value" in operand:
        return False
    if "element" in operand or ("path" in operand and "saved" not in operand):
        return True
    if "sum" in operand:
        return any(_observes_live_state(value) for value in operand["sum"])
    if "count" in operand:
        return _observes_live_state(operand["count"])
    return False


def validate_scenarios(scenarios):
    """Return a decoded copy; keep the provider's original plan bytes immutable.

    This validates structure and budgets, not whether an assertion is a useful
    test of the requested game. A reviewer still inspects the actual adapter.
    """
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= MAX_SCENARIOS:
        raise ValueError(f"QA requires 1–{MAX_SCENARIOS} scenarios")
    _json(scenarios, max_bytes=128_000)
    result, ids, frames, actions, persistence_operations = [], set(), 0, 0, 0
    lifecycle_operations = reloads = 0
    for original in scenarios:
        _keys(
            original,
            {"id", "purpose", "category", "seed", "steps", "affected_files", "limitations"},
        )
        scenario = copy.deepcopy(original)
        _identifier(scenario["id"], "scenario id")
        if scenario["id"] in ids:
            raise ValueError("QA scenario ids must be unique")
        ids.add(scenario["id"])
        _string(scenario["purpose"], 1200, "purpose")
        _string(scenario["seed"], 120, "seed")
        if not isinstance(scenario["category"], str) or scenario["category"] not in CATEGORIES:
            raise ValueError("QA scenario category is not supported")
        if (
            not isinstance(scenario["affected_files"], list)
            or not scenario["affected_files"]
            or any(
                not isinstance(name, str) or name not in FILES
                for name in scenario["affected_files"]
            )
            or len(set(scenario["affected_files"])) != len(scenario["affected_files"])
        ):
            raise ValueError("QA affected_files must name unique owning source modules")
        if not isinstance(scenario["limitations"], list) or len(scenario["limitations"]) > 8:
            raise ValueError("QA limitations must be a bounded list")
        for limitation in scenario["limitations"]:
            _string(limitation, 500, "limitation")
        if not isinstance(scenario["steps"], list) or not 1 <= len(scenario["steps"]) <= MAX_STEPS:
            raise ValueError(f"QA scenario requires 1–{MAX_STEPS} steps")
        decoded, captures, saves, assertions, observations, operations, fault_changes = (
            [],
            set(),
            set(),
            0,
            0,
            0,
            0,
        )
        scenario_lifecycle = scenario_reloads = 0
        lifecycle_hidden, storage_mode = False, "normal"
        pending_lifecycle_observation = False
        for raw in scenario["steps"]:
            # A normalized list can be validated again at the Docker boundary.
            if isinstance(raw, str):
                _string(raw, 12_000, "step")
                try:
                    step = json.loads(raw)
                except (ValueError, RecursionError) as exc:
                    raise ValueError("QA steps must contain valid JSON objects") from exc
            else:
                step = copy.deepcopy(raw)
            if not isinstance(step, dict):
                raise ValueError("QA step must be an object")
            op = step.get("op")
            if not isinstance(op, str):
                raise ValueError("QA step operation must be a string")
            if op == "act":
                _keys(step, {"op", "action"}, {"repeat"})
                if not isinstance(step["action"], dict):
                    raise ValueError("QA action must be an object")
                _json(step["action"])
                _integer(step.get("repeat", 1), 1, 120, "action repeat")
                actions += step.get("repeat", 1)
                operations += 1
            elif op == "advance":
                _keys(step, {"op", "frames"})
                _integer(step["frames"], 1, 3600, "advance frames")
                frames += step["frames"]
                operations += 1
            elif op == "capture":
                _keys(step, {"op", "key"})
                _identifier(step["key"], "capture key")
                if step["key"] in captures or len(captures) >= 12:
                    raise ValueError("QA capture names must be unique; at most 12 snapshots")
                captures.add(step["key"])
            elif op == "serialize":
                _keys(step, {"op", "key"})
                _identifier(step["key"], "save key")
                if step["key"] in saves or len(saves) >= MAX_SAVES:
                    raise ValueError(
                        f"QA save keys must be unique; at most {MAX_SAVES} serialized saves"
                    )
                saves.add(step["key"])
                operations += 1
                persistence_operations += 1
            elif op == "restore":
                _keys(step, {"op", "expect"}, {"saved", "text"})
                if ("saved" in step) == ("text" in step):
                    raise ValueError("QA restore requires exactly one saved key or literal text")
                if "saved" in step:
                    _identifier(step["saved"], "save reference")
                    if step["saved"] not in saves:
                        raise ValueError("QA restore refers to a save that has not been serialized")
                else:
                    # Empty input must reach the actual importer, not a fallback save.
                    _string(step["text"], 8192, "import text", empty=True)
                if not isinstance(step["expect"], str) or step["expect"] not in {
                    "accepted",
                    "rejected",
                }:
                    raise ValueError("QA restore expect must be accepted or rejected")
                if "text" in step and step["expect"] != "rejected":
                    raise ValueError(
                        "QA literal import text is rejection-only; accepted restore requires a serialized save"
                    )
                operations += 1
                persistence_operations += 1
            elif op == "storage_fault":
                _keys(step, {"op", "mode"})
                if not isinstance(step["mode"], str) or step["mode"] not in {
                    "normal",
                    "quota",
                    "denied",
                }:
                    raise ValueError("QA storage fault mode must be normal, quota or denied")
                operations += 1
                persistence_operations += 1
                fault_changes += 1
                storage_mode = step["mode"]
                if fault_changes > 8:
                    raise ValueError("QA scenario permits at most 8 storage fault changes")
            elif op == "lifecycle":
                if pending_lifecycle_observation:
                    raise ValueError(
                        "QA lifecycle/reload needs a subsequent observable assertion before another lifecycle transition"
                    )
                _keys(step, {"op", "event"})
                if not isinstance(step["event"], str) or step["event"] not in {
                    "hide",
                    "show",
                    "remount",
                }:
                    raise ValueError("QA lifecycle event must be hide, show or remount")
                if step["event"] in {"hide", "show"}:
                    lifecycle_hidden = step["event"] == "hide"
                scenario_lifecycle += 1
                lifecycle_operations += 1
                operations += 1
                pending_lifecycle_observation = True
                if scenario_lifecycle > 8:
                    raise ValueError("QA scenario permits at most 8 lifecycle operations")
            elif op == "reload":
                if pending_lifecycle_observation:
                    raise ValueError(
                        "QA lifecycle/reload needs a subsequent observable assertion before another lifecycle transition"
                    )
                _keys(step, {"op"})
                if storage_mode != "normal" or lifecycle_hidden:
                    raise ValueError(
                        "QA reload requires normal storage and visible lifecycle state first"
                    )
                scenario_reloads += 1
                reloads += 1
                operations += 1
                pending_lifecycle_observation = True
                if scenario_reloads > 2:
                    raise ValueError("QA scenario permits at most 2 reloads")
            elif op == "assert":
                _keys(step, {"op", "left", "cmp"}, {"right"})
                if not isinstance(step["cmp"], str) or step["cmp"] not in {
                    "eq",
                    "ne",
                    "gt",
                    "gte",
                    "lt",
                    "lte",
                    "exists",
                }:
                    raise ValueError("QA comparison is not supported")
                _operand(step["left"], captures)
                if step["cmp"] == "exists":
                    if "right" in step:
                        raise ValueError("QA exists has no right operand")
                else:
                    if "right" not in step:
                        raise ValueError("QA comparison requires a right operand")
                    _operand(step["right"], captures)
                    if step["left"] == step["right"]:
                        raise ValueError("QA self-comparisons do not establish observable behavior")
                assertions += 1
                if _observes_state(step["left"]) or (
                    "right" in step and _observes_state(step["right"])
                ):
                    observations += 1
                if _observes_live_state(step["left"]) or (
                    "right" in step and _observes_live_state(step["right"])
                ):
                    pending_lifecycle_observation = False
            elif op == "reset":
                if pending_lifecycle_observation:
                    raise ValueError(
                        "QA lifecycle/reload needs a subsequent observable assertion before reset"
                    )
                _keys(step, {"op"}, {"seed"})
                if "seed" in step:
                    _string(step["seed"], 120, "reset seed")
                operations += 1
            elif op in {"click", "focus"}:
                _keys(step, {"op", "selector"})
                _string(step["selector"], 256, "selector")
                operations += 1
            elif op == "key":
                _keys(step, {"op", "key"})
                _string(step["key"], 80, "keyboard key")
                operations += 1
            else:
                raise ValueError(
                    "QA step operation is not supported; executable JavaScript is forbidden"
                )
            decoded.append(step)
        if not assertions or not observations or not operations:
            raise ValueError("QA scenario needs both an operation and an observable assertion")
        if pending_lifecycle_observation:
            raise ValueError(
                "QA lifecycle/reload needs a subsequent observable assertion using a live path or DOM"
            )
        scenario["steps"] = decoded
        result.append(scenario)
    if frames > MAX_FRAMES or actions > MAX_ACTIONS:
        raise ValueError(f"QA suite exceeds {MAX_FRAMES} frames or {MAX_ACTIONS} actions")
    if persistence_operations > MAX_PERSISTENCE_OPERATIONS:
        raise ValueError(f"QA suite exceeds {MAX_PERSISTENCE_OPERATIONS} persistence operations")
    if lifecycle_operations > MAX_LIFECYCLE_OPERATIONS or reloads > MAX_RELOADS:
        raise ValueError(
            f"QA suite exceeds {MAX_LIFECYCLE_OPERATIONS} lifecycle operations or {MAX_RELOADS} reloads"
        )
    return result
