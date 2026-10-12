"""Offline budget bookkeeping; no model or browser dispatch."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from prompt2play.generation.workspace import GenerationStopped
from prompt2play.pricing import nano_usd, snapshot


def journals(tmp_path: Path) -> tuple[Any, Any]:
    loaded = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/compare_adaptive.py"))
    shared = tmp_path / "budget-ledger.json"
    for name in ("old", "new"):
        (tmp_path / name).mkdir()
    cls = loaded["SharedJournal"]
    return tuple(
        cls(tmp_path / name, shared, nano_usd("1"), snapshot("gpt-6.1-sol", "codex"))
        for name in ("old", "new")
    )


def test_shared_budget_covers_both_variants_and_unknown_reservations(tmp_path: Path) -> None:
    old, new = journals(tmp_path)
    estimate = {"input_tokens": 130_000, "cached_input_tokens": 0, "output_tokens": 20_000}
    old.reserve("first", 120000, "author", "a" * 64, estimate=estimate)
    with pytest.raises(GenerationStopped, match="Shared comparison"):
        new.reserve("second", 120000, "author", "b" * 64, estimate=estimate)
    old.settle("first", data=None, usage=None, status="interrupted_unknown")
    with pytest.raises(GenerationStopped):
        new.reserve("second", 120000, "author", "b" * 64, estimate=estimate)
    assert old.totals()[1] > 0 and old.totals()[0] == 0


def test_completed_replay_does_not_spend_or_reserve_again(tmp_path: Path) -> None:
    old, new = journals(tmp_path)
    estimate = {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 100}
    old.reserve("first", 1100, "plan", "a" * 64, estimate=estimate)
    usage = {
        "input_tokens": 1000,
        "cached_input_tokens": 800,
        "output_tokens": 100,
        "total_tokens": 1100,
        "calls": 1,
    }
    old.settle("first", data={"ok": True}, usage=usage, status="completed")
    before = old.totals()
    assert old.reserve("first", 1100, "plan", "a" * 64, estimate=estimate)["data"] == {"ok": True}
    assert old.totals() == before and before[1] == 0
    new.reserve("next", 1100, "plan", "b" * 64, estimate=estimate)
    new.settle(
        "next",
        data=None,
        usage={
            **usage,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        },
        status="not_started",
    )
    assert old.totals() == before
    assert (
        json.loads((tmp_path / "budget-ledger.json").read_text())["new:next"]["state"]
        == "not_started"
    )
