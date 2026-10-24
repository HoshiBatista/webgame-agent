"""Independent, hash-bound receipts for artifact gates, never a gameplay oracle."""

from .contracts import VIEWPORTS

VERSION = 1


def receipt(artifact_hash, environment, syntax, measurements):
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
        })
    return {"version": VERSION, "artifact_hash": artifact_hash, "environment": environment,
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
    return {"syntax": syntax, "runtime": runtime, "surface": surface}


def proven_defects(evidence):
    codes = set()
    if evidence["syntax"]["status"] == "failed":
        codes.add("javascript_syntax")
    for view in evidence["viewports"]:
        if view["errors"] or view["requests"]:
            codes.add("runtime_or_network")
        if view["viewport"] == "mobile" and any(s.get("overflow") is True for s in view["surfaces"]):
            codes.add("mobile_overflow")
    return codes
