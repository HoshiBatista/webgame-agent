"""Declarative, real-input checks for named gameplay actions."""

from __future__ import annotations

import json
import math
import re
from typing import Any


def validate_mechanics(value: Any, required_actions: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 24:
        raise ValueError("Basic mechanics require one to 24 named real-input cases")
    result, errors, seen = [], [], set()
    for index, case in enumerate(value):
        name = case.get("id", index) if isinstance(case, dict) else index
        try:
            checked = _validate_mechanics([case], [])
            if checked[0]["id"] in seen:
                raise ValueError("Mechanics case IDs must be unique bounded names")
            seen.add(checked[0]["id"])
            result.extend(checked)
        except (ValueError, TypeError) as exc:
            errors.append(f"mechanics[{name}]: {exc}")
    if errors:
        raise ValueError("; ".join(errors[:8]))
    covered = {action for case in result for action in case["actions"]}
    missing = set(required_actions) - {"START", "RESTART"} - covered
    if missing:
        raise ValueError("Untested gameplay actions: " + ", ".join(sorted(missing)))
    return result


def _validate_mechanics(value: Any, required_actions: list[str]) -> list[dict[str, Any]]:
    # Import here to keep input normalization shared with the legacy smoke suite.
    from prompt2play.validation.runner import validate_acceptance

    if not isinstance(value, list) or not 1 <= len(value) <= 24:
        raise ValueError("Basic mechanics require one to 24 named real-input cases")
    result, seen, covered = [], set(), set()
    for case in value:
        if not isinstance(case, dict) or set(case) != {
            "id",
            "description",
            "actions",
            "keyboard_keys",
            "continuous",
            "desktop",
            "touch",
        }:
            raise ValueError("Invalid mechanics case fields")
        name = case["id"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name)
            or name in seen
        ):
            raise ValueError("Mechanics case IDs must be unique bounded names")
        seen.add(name)
        if not isinstance(case["description"], str) or not 1 <= len(case["description"]) <= 4000:
            raise ValueError("Mechanics case requires a description")
        actions, keys = case["actions"], case["keyboard_keys"]
        if (
            not isinstance(actions, list)
            or not actions
            or any(not isinstance(a, str) or not a for a in actions)
        ):
            raise ValueError("Mechanics case must identify its gameplay actions")
        if (
            not isinstance(keys, list)
            or len(keys) > 16
            or any(not isinstance(k, str) or not 1 <= len(k) <= 40 for k in keys)
            or type(case["continuous"]) is not bool
        ):
            raise ValueError("Invalid declared keyboard controls")
        covered.update(actions)
        normalized: dict[str, Any] = {
            k: case[k] for k in ("id", "description", "actions", "keyboard_keys", "continuous")
        }
        for device in ("desktop", "touch"):
            scenario = case[device]
            if not isinstance(scenario, dict) or set(scenario) != {"steps", "assertions"}:
                raise ValueError("Mechanics scenarios require steps and assertions")
            simple = {
                "steps": scenario["steps"],
                "completion": {"path": "/phase", "one_of": ["playing"]},
            }
            # Normalize with both devices so touch cannot substitute key presses.
            other = {
                "steps": [{"kind": "tap", "selector": "#fixture"}],
                "completion": simple["completion"],
            }
            acceptance = {
                "start_selector": "#p2p-start",
                "restart_selector": "#p2p-restart",
                "desktop": other,
                "touch": other,
                device: simple,
            }
            try:
                steps = validate_acceptance(acceptance, allow_passive=True)[device]["steps"]
            except ValueError as exc:
                raise ValueError(f"mechanics[{name}].{device}: {exc}") from exc
            if any(s["repeat"] != 1 for s in steps):
                raise ValueError("Mechanics cases use explicit steps, not repeat")
            assertions = scenario["assertions"]
            if not isinstance(assertions, list) or not 1 <= len(assertions) <= 32:
                raise ValueError("Each mechanic requires observable assertions")
            for assertion_index, check in enumerate(assertions):
                if not isinstance(check, dict) or set(check) != {
                    "after_step",
                    "before_step",
                    "path",
                    "op",
                    "value_json",
                    "tolerance",
                }:
                    raise ValueError("Invalid mechanics assertion")
                after, before = check["after_step"], check["before_step"]
                if (
                    type(after) is not int
                    or not 1 <= after <= len(steps)
                    or type(before) is not int
                    or not -1 <= before < after
                ):
                    raise ValueError(
                        "Assertions must compare an observed step with an earlier step or literal"
                    )
                path = check["path"]
                if (
                    not isinstance(path, str)
                    or not path.startswith("/")
                    or len(path) > 200
                    or re.search(r"~(?![01])", path)
                    or path in ("/phase", "/tick", "/simulationTime")
                ):
                    raise ValueError(
                        "Mechanics assertions must observe gameplay, not just lifecycle or elapsed time"
                    )
                if check["op"] not in ("equal", "not_equal", "greater", "less"):
                    raise ValueError("Unsupported mechanics comparison")
                tolerance = check["tolerance"]
                if (
                    type(tolerance) not in (int, float)
                    or not math.isfinite(tolerance)
                    or not 0 <= tolerance <= 1000
                ):
                    raise ValueError("Invalid mechanics tolerance")
                if not isinstance(check["value_json"], str) or len(check["value_json"]) > 1000:
                    raise ValueError("Invalid assertion literal")
                if before == -1:
                    literal = json.loads(check["value_json"])
                    try:
                        json.dumps(literal, allow_nan=False)
                    except (ValueError, TypeError) as exc:
                        raise ValueError(
                            f"{device}.assertions[{assertion_index}].value_json must contain finite JSON"
                        ) from exc
                    if check["op"] in ("greater", "less") and type(literal) not in (int, float):
                        raise ValueError(
                            f"{device}.assertions[{assertion_index}]: {check['op']} needs a numeric value_json; use equal/not_equal for arrays or objects"
                        )
            if device == "desktop":
                for key in keys:
                    down = [
                        i
                        for i, s in enumerate(steps)
                        if s.get("key") == key and s["kind"] in ("key", "key_down")
                    ]
                    if len(down) < 2:
                        raise ValueError(f"Test repeated use of declared control {key}")
                    if case["continuous"]:
                        ups = [
                            i
                            for i, s in enumerate(steps)
                            if s.get("key") == key and s["kind"] == "key_up"
                        ]
                        if not any(a < b < c for a in down for b in ups for c in down):
                            raise ValueError(f"Test hold, release and re-press of {key}")
                        triples = [(a, b, c) for a in down for b in ups for c in down if a < b < c]

                        def exercised(
                            a: int,
                            b: int,
                            c: int,
                            assertions: list[dict[str, Any]],
                            steps: list[dict[str, Any]],
                        ) -> bool:
                            hold = any(
                                q["before_step"] >= a + 1
                                and q["before_step"] < q["after_step"] <= b
                                and q["op"] in ("greater", "less", "not_equal")
                                for q in assertions
                            )
                            released = any(b + 1 <= q["after_step"] <= c for q in assertions)
                            repeated = any(
                                q["after_step"] >= c + 1
                                and q["op"] in ("greater", "less", "not_equal")
                                for q in assertions
                            )
                            return (
                                hold
                                and released
                                and repeated
                                and any(s["kind"] == "wait" for s in steps[a + 1 : b])
                            )

                        if not any(exercised(a, b, c, assertions, steps) for a, b, c in triples):
                            raise ValueError(
                                f"Assertions must verify sustained movement, release and re-press of {key}"
                            )
            normalized[device] = {"steps": steps, "assertions": assertions}
        result.append(normalized)
    missing = set(required_actions) - {"START", "RESTART"} - covered
    if missing:
        raise ValueError("Untested gameplay actions: " + ", ".join(sorted(missing)))
    return result


def preserve_mechanics(previous: list[dict[str, Any]], updated: list[dict[str, Any]]) -> None:
    indexed = {case["id"]: case for case in updated}
    for case in previous:
        fresh = indexed.get(case["id"])
        if (
            fresh is None
            or not set(case["actions"]) <= set(fresh["actions"])
            or not set(case["keyboard_keys"]) <= set(fresh["keyboard_keys"])
            or (case["continuous"] and not fresh["continuous"])
        ):
            raise ValueError("Cannot drop planned mechanics or controls: " + case["id"])
