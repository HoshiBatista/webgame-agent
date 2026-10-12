"""Reporting cannot turn unfinished games or model opinions into a rollout gate."""

import json
import runpy
from pathlib import Path

import pytest


def test_measurement_keeps_failed_and_unfinished_runs_in_denominator(tmp_path: Path) -> None:
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/comparison_report.py"))
    manifest = {
        "version": "test",
        "model": "fixture",
        "budget_usd": "50",
        "cases": [
            {"id": "a", "revision": "revise", "rubric": ["r"] * 5},
            {"id": "b", "revision": "", "rubric": ["r"] * 5},
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    folder = tmp_path / "adaptive-a-new"
    folder.mkdir()
    (folder / "result.json").write_text(
        json.dumps({"outcome": "failed", "visual_status": "rendered_ready"})
    )
    (tmp_path / "budget-ledger.json").write_text(
        json.dumps(
            {
                "adaptive-a-new:paid": {
                    "upper_nano": 500_000_000,
                    "reserved_nano": 0,
                    "usage": {"calls": 1, "input_tokens": 1000, "cached_input_tokens": 800},
                },
                "legacy-a-new:uncertain": {"upper_nano": 0, "reserved_nano": 100_000_000},
            }
        )
    )
    result = module["summarize"](tmp_path)
    assert len(result["runs"]) == 6
    assert result["spent_upper_usd"] == 0.5 and result["reserved_usd"] == 0.1
    assert result["paired_human_art_median_improvement"] is None
    assert result["variants"]["adaptive"]["new_games_accepted"] == 0
    assert not result["default_rollout_eligible"]
    assert result["actual_webview"] == "host_unknown_not_tested"


def test_human_scores_require_attribution_and_valid_rubric(tmp_path: Path) -> None:
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/comparison_report.py"))
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "test",
                "model": "fixture",
                "budget_usd": "50",
                "cases": [{"id": "a", "revision": "", "rubric": ["r"] * 5}],
            }
        )
    )
    with pytest.raises(ValueError, match="Human ratings"):
        module["summarize"](tmp_path, {"runs": {"adaptive-a-new": [5] * 5}})
    with pytest.raises(ValueError, match="Human ratings"):
        module["summarize"](
            tmp_path,
            {
                "reviewer": "tester",
                "reviewed_at": "2026-10-12",
                "runs": {"adaptive-a-new": [6] * 5},
            },
        )
