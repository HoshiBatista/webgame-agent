"""Application-owned check interpretation; no game execution or model verdicts."""

import math
import re
from copy import deepcopy

VERSION = 2
RELATIVE = {"changed", "unchanged", "increased", "decreased"}
NUMERIC = {"increased", "decreased"}
INPUT = {"click", "tap", "click_fraction", "tap_fraction", "press", "key_down", "key_up"}
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def numeric(value):
    return type(value) in {int, float} and math.isfinite(value)


def comparable(value, expected):
    if numeric(value) or numeric(expected):
        return numeric(value) and numeric(expected)
    return type(value) is type(expected) and type(value) in {str, bool, type(None)}


def parse_number(value):
    if not isinstance(value, str) or not NUMBER.fullmatch(value.strip()):
        raise ValueError("Наблюдение должно содержать только конечное число, без подписи или единиц.")
    result = float(value.strip())
    if not math.isfinite(result):
        raise ValueError("Наблюдение должно содержать конечное число.")
    return result


def review_checks(checks):
    """Only repair an unambiguous representation mismatch; never alter expectations.

    A numeric operator already requests a number. Make that conversion explicit in
    a separate suite snapshot; the original revision and requirement stay intact.
    Ambiguous labels are rejected by the browser, never parsed heuristically.
    """
    result, corrections = deepcopy(checks), []
    for check in result:
        observation, expect = check.get("observation", {}), check.get("expect", {})
        source = observation.get("source")
        if source in {"text", "attribute"} and (
            expect.get("operator") in NUMERIC
            or expect.get("operator") in {"eq", "not_eq"} and numeric(expect.get("value"))
        ):
            observation["source"] = source + "_number"
            corrections.append({"check_id": check.get("id"), "code": "explicit_numeric_observation",
                                "from": source, "to": observation["source"],
                                "reason": "Числовое ожидание требует строгого числового наблюдения."})
    return result, corrections


def check_issue(check):
    observation, expect = check.get("observation", {}), check.get("expect", {})
    source, op, value = observation.get("source"), expect.get("operator"), expect.get("value")
    steps = check.get("steps", [])
    checkpoints = [i for i, step in enumerate(steps) if step.get("action") == "checkpoint"]
    awaits = [i for i, step in enumerate(steps) if step.get("action") == "wait_for"]
    if len(checkpoints) > 1 or checkpoints and op not in RELATIVE:
        return "Одна точка baseline допустима только для changed/increased/decreased."
    if len(awaits) > 1 or awaits and awaits[0] != len(steps) - 1:
        return "wait_for допустим один раз, последним действием сценария."
    if check.get("category") in {"control", "outcome"}:
        if op == 'unchanged':
            return 'Отсутствие изменения относится к регрессии, а не доказывает основное управление или исход.'
        measured = steps[checkpoints[0] + 1:] if checkpoints else steps
        if not any(step.get("action") in INPUT for step in measured):
            return "После подготовки сценарий должен выполнять настоящий игровой ввод."
    if op in NUMERIC and source in {"text", "attribute"}:
        return "Числовое сравнение требует text_number/attribute_number или числовое state."
    if source in {"text_number", "attribute_number"} and op in {"contains", "visible"}:
        return "Числовое наблюдение несовместимо с contains/visible."
    if source in {"text_number", "attribute_number"} and op in {"eq", "not_eq"} and not numeric(value):
        return "Ожидаемое значение числового наблюдения должно быть числом."
    if source in {"text", "attribute"} and op in {"eq", "not_eq"} and not isinstance(value, str):
        return "Текстовое наблюдение требует строковое ожидание или явное преобразование."
    if op == "contains" and (not isinstance(value, str) or not value.strip()):
        return "Ожидание contains требует непустую строку."
    if op == "visible" and source == "state":
        return "Видимость проверяется по элементу страницы; для state используйте eq."
    return None


def gates_verified(result, checks):
    """Manual acceptance still needs actual syntax/runtime/surface receipts."""
    gates = result.get("gates", {})
    if any(f.get("code") in {"javascript_syntax", "runtime_or_network", "canvas_missing", "mobile_overflow",
                             "browser_error", "surface_unverified", "module_not_registered", "control_obstructed"} for f in result.get("findings", [])):
        return False
    if not all(gates.get(key) is True for key in ("syntax", "runtime", "surface")):
        return False
    if {"stage": "syntax", "status": "passed"} not in [
        {k: s.get(k) for k in ("stage", "status")} for s in result.get("stages", [])
    ]:
        return False
    if "artifact_evidence" in result:
        from .evidence import gates as evidence_gates
        from .evidence import valid

        evidence = result["artifact_evidence"]
        return bool(valid(evidence, result.get("artifact_hash"), result.get("environment"))
                    and all(evidence_gates(evidence).values()))
    facts = result.get("facts", [])
    by_id = {f.get("id"): f for f in facts}
    if not checks or len(by_id) != len(facts) or set(by_id) != {c.get("id") for c in checks}:
        return False
    for check in checks:
        fact = by_id[check["id"]]
        if any(fact.get(k) != check.get(k) for k in ("category", "requirement", "viewport")):
            return False
        surface = fact.get("surface", {})
        if not any(c.get("visible") and c.get("width", 0) > 0 and c.get("height", 0) > 0
                   for c in surface.get("canvases", [])):
            return False
        if check.get("viewport") == "mobile" and surface.get("overflow") is not False:
            return False
    return True
