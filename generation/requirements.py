"""Frozen promises and provenance. Model interpretations are not independent oracles."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

VERSION = 1
PLANNING_VERSION = 2


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def manifest(request, plan=None, *, previous=None, amendment=""):
    result = {
        "version": VERSION,
        "request": request,
        "request_hash": digest(request),
        "scope": "planned_proposals" if plan else "user_request_unmapped",
        "requirements": deepcopy((plan or {}).get("requirements", [])),
    }
    if amendment:
        result.update(
            amendments=[*(previous or {}).get("amendments", []), amendment],
            supersedes=digest(previous or {}),
            scope="user_amendment_unmapped",
        )
    return result


def coverage(checks, frozen):
    expected = frozen.get("requirements", [])
    actual = {c["id"]: c for c in checks}
    missing = [
        r
        for r in expected
        if any(actual.get(r["id"], {}).get(k) != r[k] for k in ("id", "category", "requirement", "viewport"))
    ]
    return {
        "manifest_hash": digest(frozen),
        "scope": frozen.get("scope", "unmapped"),
        "uncovered": [r["id"] for r in missing],
        "requirements": deepcopy(expected),
        "independent_semantic_verification": False,
    }


def policy_snapshot():
    root = Path(__file__).parent
    paths = [
        "planning.py",
        "requirements.py",
        "schema.py",
        "prompts.py",
        "presentation.py",
        "compact.py",
        "helpers.py",
        "visual.py",
        "feedback_image.py",
        "../studio/visual.py",
        "runtime/motion-v1.js",
        "runtime/compact-v2.js",
        "runtime/compact-v2.css",
        "artifacts.py",
        "source_policy.py",
        "check_repair.py",
        "code_repair.py",
        "feedback.py",
        "../studio/tasks.py",
        "../studio/check_repair.py",
        "../studio/checks_create.py",
        "../studio/acceptance.py",
        "../validation/checks.py",
        "../validation/check_program.py",
    ]
    return {
        "pipeline": 9,
        "planning": PLANNING_VERSION,
        "runtime": 2,
        "source_hashes": {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
    }
