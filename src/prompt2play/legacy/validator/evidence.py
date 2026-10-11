"""Byte bindings shared by worker validation; this module never runs game code."""

from __future__ import annotations

import hashlib
import json


def canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def artifact_manifest(files, artifact, spec):
    """Hash exact delivery bytes and the full immutable output specification."""
    if (
        not isinstance(files, dict)
        or not isinstance(artifact, str)
        or not isinstance(spec, dict)
        or any(not isinstance(k, str) or not isinstance(v, str) for k, v in files.items())
    ):
        raise ValueError(
            "Artifact manifest requires source strings, HTML and a specification object"
        )
    payload = artifact.encode("utf-8")
    return {
        "html_sha256": hashlib.sha256(payload).hexdigest(),
        "html_bytes": len(payload),
        "files_sha256": {
            name: hashlib.sha256(files[name].encode("utf-8")).hexdigest() for name in sorted(files)
        },
        "spec_sha256": hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest(),
    }


def report_matches(report, files, artifact, spec):
    """A result from any previous source/spec/artifact must not be reused."""
    try:
        expected = artifact_manifest(files, artifact, spec)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return False
    if (
        not isinstance(report, dict)
        or report.get("schema_version") != 2
        or report.get("artifact") != expected
        or not isinstance(report.get("checks"), list)
    ):
        return False
    if any(
        not isinstance(check, dict) or check.get("artifact_sha256") != expected["html_sha256"]
        for check in report["checks"]
    ):
        return False
    review = report.get("review")
    return review is None or (
        isinstance(review, dict) and review.get("artifact_sha256") == expected["html_sha256"]
    )


def check_record(
    name,
    status,
    message,
    manifest,
    *,
    check_kind="static",
    scenario_id=None,
    affected_files=None,
    command=None,
    limitations=None,
    evidence=None,
):
    result = {
        "name": name,
        "status": status,
        "message": message,
        "check_kind": check_kind,
        "artifact_sha256": manifest["html_sha256"],
        "limitations": list(limitations or []),
        "evidence": dict(evidence or {}),
    }
    if scenario_id is not None:
        result["scenario_id"] = scenario_id
    if affected_files is not None:
        result["affected_files"] = list(affected_files)
    if command is not None:
        result["command"] = command
    return result
