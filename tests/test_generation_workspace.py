"""Meaningful bounded editing, path capability, stale-result and accounting tests."""

from __future__ import annotations

import time

import pytest

from prompt2play.generation.workspace import (
    DraftWorkspace,
    GenerationControl,
    GenerationStopped,
    WorkspaceLimits,
    normalized_path,
)


@pytest.mark.parametrize(
    "path",
    [
        "/game.js",
        "../game.js",
        "a/../game.js",
        ".hidden.js",
        "runtime-v1.js",
        "runtime/game.js",
        "a\\game.js",
        "a//game.js",
        "game.js.exe",
        "é.js",
    ],
)
def test_forbidden_paths(path: str) -> None:
    with pytest.raises(ValueError):
        normalized_path(path)


def test_local_edit_preserves_unrelated_bytes_and_submitted_snapshot() -> None:
    control = GenerationControl.bounded()
    workspace = DraftWorkspace(
        control, WorkspaceLimits(), {"game.js": "const score=1;", "style.css": "body{color:red}"}
    )
    workspace.allowed_paths = {"style.css"}
    workspace.patch("style.css", "red", "blue")
    with pytest.raises(ValueError, match="capability"):
        workspace.write("game.js", "const score=2;")
    submitted = workspace.submit()
    assert submitted == {"game.js": "const score=1;", "style.css": "body{color:blue}"}
    with pytest.raises(GenerationStopped, match="already submitted"):
        workspace.patch("style.css", "blue", "green")


def test_noop_ambiguous_anchor_and_quota() -> None:
    workspace = DraftWorkspace(
        GenerationControl.bounded(), WorkspaceLimits(max_file_bytes=50), {"game.js": "x+x"}
    )
    with pytest.raises(ValueError, match="exactly once"):
        workspace.patch("game.js", "x", "y")
    with pytest.raises(ValueError, match="No-op"):
        workspace.write("game.js", "x+x")
    with pytest.raises(GenerationStopped, match="no-op"):
        workspace.write("game.js", "x+x")
    with pytest.raises(ValueError, match="per-file"):
        workspace.write("game.js", "x" * 51)


def test_every_operation_checks_deadline_cancel_and_current_fence() -> None:
    current = [True]
    control = GenerationControl.bounded(fence_check=lambda: current[0])
    workspace = DraftWorkspace(control, WorkspaceLimits(), {"game.js": "let x=1"})
    current[0] = False
    with pytest.raises(GenerationStopped, match="fence"):
        workspace.submit()
    current[0] = True
    control.deadline = time.monotonic() - 1
    with pytest.raises(GenerationStopped, match="deadline"):
        workspace.read("game.js")
    control.deadline = time.monotonic() + 100
    control.cancel.set()
    with pytest.raises(GenerationStopped, match="cancelled"):
        workspace.check()


def test_unknown_calls_keep_reservation_and_do_not_reset_run_budget() -> None:
    control = GenerationControl.bounded(token_limit=100)
    control.reserve("a", 60)
    control.settle("a", None)
    assert control.uncertain_tokens == 60
    with pytest.raises(GenerationStopped, match="remaining"):
        control.reserve("retry", 60)
    control.reserve("b", 30)
    control.settle("b", {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9, "calls": 1})
    assert control.usage["total_tokens"] == 9


def test_quick_check_parses_without_executing_source() -> None:
    workspace = DraftWorkspace(
        GenerationControl.bounded(),
        WorkspaceLimits(),
        {"game.js": 'throw new Error("must never execute");'},
    )
    assert workspace.check() == []
    workspace.write("game.js", "const invalid = ;")
    assert any(item["code"] == "javascript_syntax" for item in workspace.check())
    workspace.write("game.js", 'fetch("https://example.com");')
    assert any(item["code"] == "offline_source" for item in workspace.check())
