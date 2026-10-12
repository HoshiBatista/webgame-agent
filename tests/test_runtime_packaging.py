"""Runtime identity and packaging are checked without running untrusted JavaScript."""

from __future__ import annotations

import json
from typing import Any

import pytest

from prompt2play.generation.knowledge import select_lessons
from prompt2play.generation.runtime import (
    assemble_runtime,
    capture_runtime_identity,
    runtime_digest,
    trusted_runtime,
)
from prompt2play.paths import RESOURCE_ROOT


def test_runtime_digest_and_exact_html_are_reproducible() -> None:
    root = RESOURCE_ROOT / "runtime" / "examples" / "dom"
    spec = json.loads((root / "spec.json").read_text())
    files = {"game.js": (root / "game.js").read_text()}
    first = assemble_runtime(files, spec, expected_runtime_digest=runtime_digest())
    assert first == assemble_runtime(files, spec)
    assert trusted_runtime()["runtime-v1.js"] in first
    assert "createGame" in first and "__GAME_TEST__" in first
    with pytest.raises(ValueError, match="changed"):
        assemble_runtime(files, spec, expected_runtime_digest="0" * 64)
    with pytest.raises(ValueError, match=r"only game\.js"):
        assemble_runtime({**files, "runtime-v1.js": "malicious"}, spec)


def test_inline_script_and_title_cannot_escape_html() -> None:
    spec = {"title": "<img src=x onerror=alert(1)>"}
    result = assemble_runtime({"game.js": 'function createGame(){return "</script>";}'}, spec)
    assert "<title>&lt;img" in result
    assert result.count("</script>") == 1


def test_frozen_runtime_preserves_previous_candidate_bytes_after_upgrade() -> None:
    digest = "a8b6ef49ae1377adc60402116bb1deb9a0a3481377c6c84d6772719d0c087803"
    spec = {
        "title": "Historical runtime fixture",
        "runtime": {"version": "runtime-v1.0.0", "sha256": digest},
    }
    first = assemble_runtime(
        {"game.js": "function createGame(){}"}, spec, expected_runtime_digest=digest
    )
    assert 'const VERSION = "runtime-v1.0.0"' in first
    assert runtime_digest() != digest
    assert assemble_runtime({"game.js": "function createGame(){}"}, spec) == first
    with pytest.raises(ValueError, match="Runtime reference"):
        assemble_runtime(
            {"game.js": "function createGame(){}"}, {"title": "Bad metadata", "runtime": True}
        )


def test_correct_digest_cannot_hide_incorrect_runtime_version() -> None:
    identity = capture_runtime_identity()
    spec: dict[str, Any] = {
        "title": "Mismatched runtime declaration",
        "runtime": {"version": "runtime-v0.0.0", "sha256": identity["sha256"]},
    }
    with pytest.raises(ValueError, match="version does not match"):
        assemble_runtime({"game.js": "function createGame(){}"}, spec)
    spec["runtime"]["version"] = identity["version"]
    assert trusted_runtime()["runtime-v1.js"] in assemble_runtime(
        {"game.js": "function createGame(){}"}, spec
    )
    spec["runtime"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest does not match"):
        assemble_runtime(
            {"game.js": "function createGame(){}"}, spec, expected_runtime_digest=identity["sha256"]
        )


def test_scroll_fix_preserves_exact_preceding_candidate_runtime() -> None:
    """An interrupted release remains reproducible after the touch-layout fix."""
    digest = "633ca773368e5a5e82b73f7f853571f83f50cbb7037bf93a6707a9529cf4527f"
    spec = {
        "title": "Interrupted release historical fixture",
        "runtime": {"version": "runtime-v1.0.4", "sha256": digest},
    }
    files = {"game.js": "function createGame(){}"}
    old_html = assemble_runtime(files, spec)
    assert trusted_runtime(digest)["runtime-v1.css"] in old_html
    assert 'const VERSION = "runtime-v1.0.4"' in old_html
    current = capture_runtime_identity()
    assert current["version"] == "runtime-v1.0.6"
    assert current["sha256"] != digest
    new_html = assemble_runtime(files, {**spec, "runtime": current})
    assert old_html != new_html
    assert assemble_runtime(files, spec) == old_html


def test_lessons_are_applicable_and_preserve_source_identity() -> None:
    assert select_lessons({"genre": "grid puzzle", "capabilities": ["input", "lifecycle"]}) == []
    selected = select_lessons({"genre": "card game", "capabilities": ["audio"]})
    assert {item["id"] for item in selected} >= {
        "decision-owner",
        "hidden-information",
        "stale-audio",
    }
    assert all(len(item["source"]["sha256"]) == 64 for item in selected)
