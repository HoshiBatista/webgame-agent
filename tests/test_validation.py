"""Security and eligibility regressions for the mandatory container boundary."""

from __future__ import annotations

import copy
import hashlib
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from prompt2play.validation import REQUIRED_CHECKS, IsolatedValidator, validate_acceptance
from prompt2play.validation.runner import MAX_EVIDENCE_BYTES, evidence_payload


def acceptance() -> dict[str, Any]:
    return {
        "start_selector": "#start",
        "restart_selector": "#restart",
        "desktop": {
            "steps": [{"kind": "key", "key": "ArrowRight"}],
            "completion": {"path": "/phase", "one_of": ["won", "lost"]},
        },
        "touch": {
            "steps": [{"kind": "tap", "selector": "#move"}],
            "completion": {"path": "/phase", "one_of": ["won", "lost"]},
        },
    }


def test_acceptance_rejects_executable_data_keyboard_as_touch_and_unbounded_work() -> None:
    assert validate_acceptance(acceptance())["desktop"]["steps"][0]["repeat"] == 1
    for altered in (
        {**acceptance(), "code": "fetch('/secret')"},
        {**acceptance(), "touch": acceptance()["desktop"]},
        {
            **acceptance(),
            "desktop": {
                "steps": [{"kind": "key", "key": "x", "repeat": 999}],
                "completion": {"path": "/phase", "one_of": ["won"]},
            },
        },
        {
            **acceptance(),
            "desktop": {
                "steps": [{"kind": "wait", "ms": 900}],
                "completion": {"path": "/phase", "one_of": ["won"]},
            },
        },
    ):
        with pytest.raises(ValueError):
            validate_acceptance(altered)


def test_missing_acceptance_cannot_describe_a_game_as_passed(tmp_path: Path) -> None:
    report = IsolatedValidator().validate(
        {"game.js": "function createGame(){}"}, "<html></html>", {}, threading.Event(), tmp_path
    )
    assert report["status"] == "unverified"
    assert report["scope"]["real_input"] is False


def test_no_docker_has_no_runtime_success_or_preview_eligibility(tmp_path: Path) -> None:
    validator = IsolatedValidator()
    static: dict[str, Any] = {"checks": [], "errors": [], "warnings": []}
    with (
        patch.object(validator, "_static", return_value=static),
        patch("prompt2play.validation.runner.shutil.which", return_value=None),
    ):
        report = validator.validate(
            {"game.js": "reviewed authored test source"},
            "authored bytes",
            {"independent_acceptance": acceptance()},
            threading.Event(),
            tmp_path,
        )
    assert report["status"] == "unverified"
    assert report["checks"][0]["status"] == "skipped"


def authored_report(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = {
        "html_sha256": "a" * 64,
        "html_bytes": 1,
        "files_sha256": {},
        "spec_sha256": "b" * 64,
    }
    evidence = []
    for width in (1280, 390):
        for kind, extension in (
            ("start", "png"),
            ("final", "png"),
            ("restart", "png"),
            ("console", "json"),
            ("network", "json"),
            ("trace", "zip"),
        ):
            name = f"{kind}-{width}.{extension}"
            data = ("authored transport-test bytes " + name).encode()
            (directory / name).write_bytes(data)
            evidence.append(
                {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            )
    checks = [
        {
            "name": name,
            "status": "passed",
            "check_kind": "scenario" if name.startswith("independent_acceptance") else "browser",
            "artifact_sha256": "a" * 64,
            "evidence": {
                "actual_input": True,
                "causal_control": True,
                "state_changed": True,
                "visible_changed": True,
                "events": 1,
            },
        }
        for name in REQUIRED_CHECKS
    ]
    return {
        "schema_version": 2,
        "browser_contract_version": 3,
        "artifact": manifest,
        "request_sha256": "c" * 64,
        "suite_sha256": "d" * 64,
        "validator_image_sha256": "sha256:" + "e" * 64,
        "checks": checks,
        "errors": [],
        "warnings": [],
        "evidence_files": evidence,
    }, manifest


def test_report_checks_actual_file_bytes_and_real_input_claims(tmp_path: Path) -> None:
    report, manifest = authored_report(tmp_path)

    def validate(data: dict[str, Any]) -> dict[str, Any]:
        return IsolatedValidator.checked_report(
            data, manifest, "c" * 64, "d" * 64, "sha256:" + "e" * 64, tmp_path
        )

    assert validate(copy.deepcopy(report))["status"] == "passed"
    invalid = copy.deepcopy(report)
    next(check for check in invalid["checks"] if check["name"] == "input:390")["evidence"][
        "actual_input"
    ] = False
    with pytest.raises(ValueError, match="Input lacked"):
        validate(invalid)
    invalid = copy.deepcopy(report)
    invalid["checks"] = [check for check in invalid["checks"] if check["name"] != "completion:390"]
    with pytest.raises(ValueError, match="mandatory"):
        validate(invalid)
    (tmp_path / "final-390.png").write_bytes(b"changed afterward")
    with pytest.raises(ValueError, match="bytes"):
        validate(copy.deepcopy(report))
    with pytest.raises(ValueError, match="changed"):
        evidence_payload(tmp_path, report)


def test_failed_required_checks_and_skips_never_become_ready(tmp_path: Path) -> None:
    report, manifest = authored_report(tmp_path)
    report["checks"][0]["status"] = "skipped"
    result = IsolatedValidator.checked_report(
        report, manifest, "c" * 64, "d" * 64, "sha256:" + "e" * 64, tmp_path
    )
    assert result["status"] == "unverified"
    report["checks"][0]["status"] = "failed"
    assert (
        IsolatedValidator.checked_report(
            report, manifest, "c" * 64, "d" * 64, "sha256:" + "e" * 64, tmp_path
        )["status"]
        == "failed"
    )


def test_evidence_traversal_and_symlinks_are_rejected(tmp_path: Path) -> None:
    report, manifest = authored_report(tmp_path)
    report["evidence_files"][0]["path"] = "../secret.png"
    with pytest.raises(ValueError, match="Unsafe"):
        IsolatedValidator.checked_report(
            report, manifest, "c" * 64, "d" * 64, "sha256:" + "e" * 64, tmp_path
        )
    report, manifest = authored_report(tmp_path)
    item = report["evidence_files"][0]
    path = tmp_path / item["path"]
    path.unlink()
    path.symlink_to(tmp_path / "final-390.png")
    with pytest.raises(ValueError, match="Invalid evidence"):
        IsolatedValidator.checked_report(
            report, manifest, "c" * 64, "d" * 64, "sha256:" + "e" * 64, tmp_path
        )


def test_trace_fix_does_not_waive_evidence_size_or_byte_binding(tmp_path: Path) -> None:
    report, manifest = authored_report(tmp_path)
    next(item for item in report["evidence_files"] if item["path"] == "trace-1280.zip")["bytes"] = (
        MAX_EVIDENCE_BYTES + 1
    )
    with pytest.raises(ValueError, match="Invalid evidence file"):
        IsolatedValidator.checked_report(
            report, manifest, "c" * 64, "d" * 64, "sha256:" + "e" * 64, tmp_path
        )


def test_responsive_drag_selector_pair_and_model_defaults() -> None:
    scenario = acceptance()
    scenario["touch"]["steps"] = [
        {
            "kind": "drag",
            "from_selector": "#parcel-1",
            "to_selector": "#basket-red",
            "from": {"x": 0, "y": 0},
            "to": {"x": 0, "y": 0},
            "key": "",
            "selector": "",
            "x": 0,
            "y": 0,
            "ms": 0,
        }
    ]
    step = validate_acceptance(scenario)["touch"]["steps"][0]
    assert step == {
        "kind": "drag",
        "repeat": 1,
        "from_selector": "#parcel-1",
        "to_selector": "#basket-red",
    }
    scenario["touch"]["steps"][0]["to_selector"] = ""
    with pytest.raises(ValueError):
        validate_acceptance(scenario)


def test_native_static_policy_rejects_direct_test_bridge_and_runtime_controls() -> None:
    from prompt2play.generation.runtime import RUNTIME_VERSION, assemble_runtime, runtime_digest

    spec = {
        "title": "Reviewed static boundary",
        "format": "runtime-v1",
        "runtime": {"version": RUNTIME_VERSION, "sha256": runtime_digest()},
        "capabilities": ["input"],
    }
    for source in (
        "function createGame(ctx) { window.__GAME_TEST__ = {}; }",
        'function createGame(ctx) { document.querySelector("#p2p-status").textContent = "Completed"; }',
        "function createGame(ctx) { setInterval(() => {}, 10); }",
    ):
        files = {"game.js": source}
        report = IsolatedValidator._static(
            files, assemble_runtime(files, spec), spec, threading.Event()
        )
        assert report["status"] == "failed"
        assert any(
            check["name"] == "offline:game.js" and check["status"] == "failed"
            for check in report["checks"]
        )


def test_native_smoke_scenario_is_rejected_without_rewriting_it(tmp_path: Path) -> None:
    from prompt2play.validation.runner import validate_native_acceptance

    scenario = acceptance()
    scenario.update(start_selector="#p2p-start", restart_selector="#p2p-restart")
    for device in ("desktop", "touch"):
        scenario[device]["completion"] = {"path": "/lastCommand/type", "one_of": ["TRAIN"]}
    original = copy.deepcopy(scenario)
    with pytest.raises(ValueError, match="smoke test"):
        validate_native_acceptance(scenario)
    report = IsolatedValidator().validate(
        {"game.js": "// no execution"},
        "x",
        {"input_acceptance": scenario},
        threading.Event(),
        tmp_path,
    )
    assert report["status"] == "unverified" and "set_test_scenario" in report["warnings"][0]
    assert scenario == original


def test_long_strategy_simulation_waits_have_a_separate_work_quota() -> None:
    scenario = acceptance()
    scenario["desktop"]["steps"].append({"kind": "wait", "ms": 600000})
    assert validate_acceptance(scenario)["desktop"]["steps"][-1]["ms"] == 600000
    scenario["desktop"]["steps"] += [{"kind": "wait", "ms": 600000}] * 3
    with pytest.raises(ValueError, match="thirty simulated"):
        validate_acceptance(scenario)
