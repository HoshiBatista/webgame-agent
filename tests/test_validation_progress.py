"""Progress renews browser liveness; status chatter and stale evidence cannot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from prompt2play.validation import IsolatedValidator
from prompt2play.validation.progress import ProgressWatchdog, read_object
from prompt2play.validation.runner import evidence_payload


def progress(directory: Path, count: int, **changes: Any) -> None:
    (directory / "progress.json").write_text(
        json.dumps(
            {
                "version": 1,
                "request_sha256": "a" * 64,
                "completed": count,
                "active": {"kind": "game", "phase": "input", "case_id": "trade", "step": 7},
                **changes,
            }
        )
    )


def test_completed_work_keeps_validation_alive_for_hours(tmp_path: Path) -> None:
    watchdog = ProgressWatchdog("a" * 64, 0)
    for count in range(1, 301):
        now = count * 60
        progress(tmp_path, count)
        assert watchdog.observe(tmp_path, now)
        assert not watchdog.stalled(now + 89, 90)
    assert watchdog.stalled(now + 91, 90)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"completed": -1},
        {"completed": True},
        {"completed": "2"},
        {"request_sha256": "b" * 64},
        {"version": 2},
        {"active": {}},
    ],
)
def test_repeated_started_invalid_or_stale_work_does_not_extend_deadline(
    tmp_path: Path,
    changes: dict[str, Any],
) -> None:
    watchdog = ProgressWatchdog("a" * 64, 0)
    progress(tmp_path, 1)
    assert watchdog.observe(tmp_path, 5)
    progress(tmp_path, 1, **changes)
    assert not watchdog.observe(tmp_path, 94)
    assert watchdog.stalled(96, 90)


def test_progress_reader_rejects_symlinks_oversized_and_incomplete_data(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text('{"secret":true}')
    link = tmp_path / "progress.json"
    link.symlink_to(target)
    assert read_object(link, 8192) == {}
    link.unlink()
    for value in ('{"broken":', '"scalar"', "x" * 8193):
        link.write_text(value)
        assert read_object(link, 8192) == {}


@pytest.mark.parametrize(
    "kind,name",
    [
        ("game", "browser_progress_stalled"),
        ("infrastructure", "isolated_browser_runtime"),
    ],
)
def test_stall_preserves_bound_defects_and_never_promotes_partial_checks(
    tmp_path: Path,
    kind: str,
    name: str,
) -> None:
    watchdog = ProgressWatchdog("a" * 64, 0)
    progress(tmp_path, 3, active={"kind": kind, "phase": "input", "case_id": "trade", "step": 7})
    watchdog.observe(tmp_path, 10)
    failed = {
        "name": "mechanic_case:1280:trade",
        "status": "failed",
        "artifact_sha256": "c" * 64,
        "message": "Sell button missing",
        "evidence": {"selector": "#sell"},
    }
    (tmp_path / "partial-results.json").write_text(
        json.dumps(
            {
                "request_sha256": "a" * 64,
                "checks": [
                    failed,
                    {**failed, "status": "passed"},
                    {**failed, "artifact_sha256": "b" * 64},
                ],
            }
        )
    )
    report = IsolatedValidator()._stalled_report(
        {"html_sha256": "c" * 64},
        watchdog,
        tmp_path,
        {
            "suite_sha256": "d" * 64,
            "validator_image_sha256": "sha256:" + "e" * 64,
            "harness_files_sha256": {},
        },
    )
    assert report["status"] == "failed"
    assert report["checks"][0] == failed
    assert report["checks"][1]["name"] == name
    assert report["checks"][1]["evidence"]["active"]["step"] == 7
    assert "Sell button missing" in report["errors"]
    assert len(evidence_payload(tmp_path, report)) == 1
    (tmp_path / "partial-results.json").write_text(
        json.dumps({"request_sha256": "stale", "checks": [failed]})
    )
    assert watchdog.findings(tmp_path, "c" * 64) == []


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_idle_interval_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="configuration"):
        IsolatedValidator(timeout=timeout)
