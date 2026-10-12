"""Authored process/HTTP transports: no Docker, generated code, or model execution."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from pathlib import Path
from typing import Any, BinaryIO

import httpx
import pytest

from prompt2play.validation import REQUIRED_CHECKS, IsolatedValidator
from prompt2play.validation.runner import evidence_payload
from prompt2play.workers.runner import Coordinator, LeaseRejected, StageLease, browser_progress


class ContainerFixture:
    def __init__(self, args: list[str], stdout: BinaryIO, stderr: BinaryIO, mode: str) -> None:
        self.mode, self.polls, self.killed = mode, 0, False
        self.returncode: int | None = None
        mounts = [arg for arg in args if arg.startswith("type=bind,src=")]
        source, target = [Path(m.split("src=")[1].split(",dst=")[0]) for m in mounts]
        raw = (source / "request.json").read_bytes()
        request = json.loads(raw)
        request_hash = hashlib.sha256(raw).hexdigest()
        self.finding = {
            "name": "mechanic_case:1280:trade",
            "status": "failed",
            "check_kind": "browser",
            "artifact_sha256": request["artifact"]["html_sha256"],
            "message": "Trade action broken",
            "evidence": {"case_id": "trade"},
        }
        (target / "progress.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "request_sha256": request_hash,
                    "completed": 3,
                    "active": {"kind": "game", "phase": "input", "step": 4},
                }
            )
        )
        (target / "partial-results.json").write_text(
            json.dumps(
                {
                    "request_sha256": "stale" if mode == "stale" else request_hash,
                    "checks": [self.finding],
                }
            )
        )
        (target / "inputs-390.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "request_sha256": "stale" if mode == "stale" else request_hash,
                    "records": [
                        {
                            "step": 4,
                            "status": "running",
                            "before": {"snapshot": {"ui": {"selected": "ship"}}},
                        }
                    ],
                }
            )
        )
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
                data = b"Authored transport bytes, not browser evidence"
                (target / name).write_bytes(data)
                evidence.append(
                    {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                )
        report = {
            **request,
            "request_sha256": request_hash,
            "errors": [],
            "warnings": [],
            "evidence_files": evidence,
            "checks": [
                {
                    "name": name,
                    "status": "passed",
                    "check_kind": "browser",
                    "artifact_sha256": request["artifact"]["html_sha256"],
                    "evidence": {
                        "actual_input": True,
                        "causal_control": True,
                        "state_changed": True,
                        "visible_changed": True,
                        "events": 1,
                    },
                }
                for name in sorted(REQUIRED_CHECKS)
            ],
        }
        stdout.write(b"malformed" if mode == "malformed" else json.dumps(report).encode())
        stderr.write(b"x" * 256_001 if mode == "output" else b"Authored container diagnostic")

    def poll(self) -> int | None:
        self.polls += 1
        if self.polls > 1:
            self.returncode = 137 if self.mode in ("crash", "stale") else 0
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, **_kwargs: Any) -> int | None:
        return self.returncode


def run_validator(
    monkeypatch: pytest.MonkeyPatch, directory: Path, *, mode: str = "success", callback: Any = None
) -> tuple[dict[str, Any], ContainerFixture]:
    validator = IsolatedValidator("authored-fixture")
    created: list[ContainerFixture] = []

    def start(args: list[str], **kwargs: Any) -> ContainerFixture:
        process = ContainerFixture(args, kwargs["stdout"], kwargs["stderr"], mode)
        created.append(process)
        return process

    monkeypatch.setattr(
        validator, "_static", lambda *_: {"errors": [], "checks": [], "warnings": []}
    )
    monkeypatch.setattr("prompt2play.validation.runner.shutil.which", lambda _: "/fixture/docker")
    monkeypatch.setattr("prompt2play.validation.runner.subprocess.Popen", start)
    monkeypatch.setattr(
        "prompt2play.validation.runner.subprocess.run",
        lambda args, **_: subprocess.CompletedProcess(args, 0, "sha256:" + "f" * 64),
    )
    scenario = {
        "steps": [{"kind": "tap", "selector": "#move"}],
        "completion": {"path": "/phase", "one_of": ["won"]},
    }
    spec = {
        "input_acceptance": {
            "start_selector": "#start",
            "restart_selector": "#restart",
            "desktop": scenario,
            "touch": scenario,
        }
    }
    report = validator.validate(
        {"game.js": "inert authored transport fixture"},
        "inert HTML",
        spec,
        threading.Event(),
        directory,
        require_completion=False,
        on_progress=callback,
    )
    return report, created[0]


def make_lease(transport: httpx.MockTransport) -> StageLease:
    client = httpx.Client(base_url="http://localhost/", transport=transport)
    return StageLease(
        Coordinator("http://localhost", "fixture", client=client),
        {
            "lease_token": "fixture",
            "job": {"id": "fixture", "stage": "plan", "stage_fence": 1},
        },
        threading.Event(),
    )


@pytest.mark.parametrize("failure", ["503", "timeout", "invalid-json"])
def test_progress_delivery_failure_cannot_kill_healthy_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("Authored event timeout", request=request)
        return httpx.Response(503 if failure == "503" else 200, content=b"invalid-json")

    lease = make_lease(httpx.MockTransport(respond))
    try:
        report, process = run_validator(
            monkeypatch, tmp_path, callback=lambda value: browser_progress(lease, value)
        )
        assert report["status"] == "passed" and not report["incomplete"]
        assert not process.killed and lease.alive()
        assert "browser_progress_delivery_failed" in capsys.readouterr().out
    finally:
        lease.coordinator.close()


@pytest.mark.parametrize("status", [401, 403, 409])
def test_progress_delivery_still_honors_revoked_lease(status: int) -> None:
    lease = make_lease(httpx.MockTransport(lambda _: httpx.Response(status)))
    try:
        with pytest.raises(LeaseRejected):
            browser_progress(lease, {"phase": "input"})
        assert lease.cancel.is_set()
    finally:
        lease.coordinator.close()


def test_progress_delivery_does_not_hide_cancellation_during_outage() -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        lease.cancel.set()
        return httpx.Response(503)

    lease = make_lease(httpx.MockTransport(respond))
    try:
        with pytest.raises(LeaseRejected):
            browser_progress(lease, {"phase": "input"})
    finally:
        lease.coordinator.close()


@pytest.mark.parametrize("mode", ["crash", "malformed", "output", "stale"])
def test_abnormal_exit_keeps_only_bound_findings_and_attached_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    report, process = run_validator(monkeypatch, tmp_path, mode=mode)
    assert report["status"] == "failed" and report["incomplete"]
    assert (process.finding in report["checks"]) is (mode != "stale")
    assert report["checks"][-1]["name"] == "isolated_browser_runtime"
    assert report["checks"][-1]["evidence"]["active"]["step"] == 4
    assert len(evidence_payload(tmp_path, report)) == (1 if mode == "stale" else 2)
    saved = json.loads((tmp_path / report["evidence_files"][0]["path"]).read_text())
    assert saved["container_stderr"]
    assert len(saved["container_stderr"]) <= 256_000
    assert saved["report"]["checks"] == report["checks"]
    if mode != "stale":
        entry = report["evidence_files"][1]
        assert entry["path"] != "inputs-390.json", (
            "Interrupted input records must be frozen into host-owned evidence"
        )
        inputs = json.loads((tmp_path / entry["path"]).read_text())
        assert inputs["records"][0]["before"]["snapshot"]["ui"]["selected"] == "ship"
