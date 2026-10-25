"""Independent, hash-bound receipts for artifact gates, never a gameplay oracle."""

from .contracts import VIEWPORTS

VERSION = 1


def receipt(artifact_hash, environment, syntax, measurements, *, contract=None):
    views = []
    for name in VIEWPORTS:
        rows = [m for m in measurements if m["viewport"] == name]
        views.append({
            "viewport": name,
            "loaded": bool(rows) and all(m["loaded"] for m in rows),
            "errors": [e for m in rows for e in m["errors"]][:8],
            "requests": [e for m in rows for e in m["requests"]][:8],
            "surfaces": [m["surface"] for m in rows if m.get("surface")],
            "probes": [m["probe"] for m in rows if "probe" in m],
            "lifecycle": {"loaded": bool(rows) and all(m["loaded"] for m in rows),
                          "input_delivered": any(m.get("inputs") for m in rows),
                          "scenario_start_confirmed": any(m.get("scenario_start") for m in rows)},
            "modules": [m["module"] for m in rows if m.get("module") is not None],
        })
    return {"version": VERSION, "artifact_hash": artifact_hash, "environment": environment, "contract": contract or {},
            "syntax": syntax, "viewports": views}


def valid(evidence, artifact_hash, environment):
    if not isinstance(evidence, dict) or (
        evidence.get("version") != VERSION or evidence.get("artifact_hash") != artifact_hash
        or evidence.get("environment") != environment
        or not isinstance(evidence.get("syntax"), dict)
    ):
        return False
    syntax = evidence["syntax"]
    views = evidence.get("viewports")
    contract = evidence.get('contract', {})
    if not isinstance(contract, dict):
        return False
    if contract and (contract.get('runtime_version') != 1 or
                     not isinstance(contract.get('controls'), list) or
                     not isinstance(contract.get('observations'), list) or
                     not isinstance(contract.get('source_hash'), str) or len(contract['source_hash']) != 64 or
                     not isinstance(views, list) or not all(isinstance(v, dict) and
                         isinstance(v.get('modules'), list) and all(isinstance(m, dict) for m in v['modules']) for v in views)):
        return False
    return bool(syntax.get("status") in {"passed", "failed"}
                and type(syntax.get("scripts")) is int and syntax["scripts"] >= 0
                and isinstance(views, list) and len(views) == len(VIEWPORTS)
                and {v.get("viewport") for v in views if isinstance(v, dict)} == set(VIEWPORTS)
                and all(isinstance(v, dict) and type(v.get("loaded")) is bool
                        and all(isinstance(v.get(k), list) for k in ("errors", "requests", "surfaces"))
                        and all(isinstance(s, dict) for s in v["surfaces"]) for v in views))


def gates(evidence):
    syntax = evidence["syntax"]["status"] == "passed"
    runtime = syntax and all(v["loaded"] and not v["errors"] and not v["requests"]
                             for v in evidence["viewports"])
    surface = syntax and all(v["loaded"] for v in evidence["viewports"]) and all(
        any(any(c.get("visible") is True and type(c.get("width")) in {int, float}
                and type(c.get("height")) in {int, float} and c["width"] > 0 and c["height"] > 0
                for c in s.get("canvases", []) if isinstance(c, dict))
            and (v["viewport"] != "mobile" or s.get("overflow") is False) for s in v["surfaces"])
        and not any(s.get("overflow") is True for s in v["surfaces"] if v["viewport"] == "mobile")
        for v in evidence["viewports"]
    )
    result = {"syntax": syntax, "runtime": runtime, "surface": surface}
    if evidence.get('contract'):
        result['startup'] = runtime and all(v['modules'] and all(m.get('ready') is True and
            m.get('failed') is False and m.get('frames', 0) > 0 for m in v['modules']) for v in evidence['viewports'])
        result['controls'] = all(v['modules'] and all(not m.get('unavailable') and
            m.get('blocked_controls') == [] for m in v['modules']) for v in evidence['viewports'])
    return result


def proven_defects(evidence):
    codes = set()
    if evidence["syntax"]["status"] == "failed":
        codes.add("javascript_syntax")
    for view in evidence["viewports"]:
        if view["errors"] or view["requests"]:
            codes.add("runtime_or_network")
        if view["viewport"] == "mobile" and any(s.get("overflow") is True for s in view["surfaces"]):
            codes.add("mobile_overflow")
        if evidence.get('contract'):
            if any(m.get('ready') is False for m in view.get('modules', [])):
                codes.add('module_not_registered')
            if any(m.get('blocked_controls') for m in view.get('modules', [])):
                codes.add('control_obstructed')
    return codes
