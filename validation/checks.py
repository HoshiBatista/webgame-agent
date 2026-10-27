"""Application-owned check interpretation; no game execution or model verdicts."""

import math
import re
from copy import deepcopy

VERSION = 3
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
    from .check_program import compile_check

    issue = compile_check(check).issue
    return issue.message if issue else None


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
