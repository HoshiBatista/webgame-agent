"""An image mismatch must fail before any paid model dispatch."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from prompt2play.validation import IsolatedValidator, runner


def test_inventory_check_rejects_stale_image_and_has_no_game_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner._preflight_image.cache_clear()
    monkeypatch.setattr(
        "prompt2play.validation.runner.shutil.which", lambda _name: "/fixture/docker"
    )
    commands = []

    def execute(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(
            args, 0, "sha256:" + "a" * 64 if args[1] == "image" else "{}"
        )

    monkeypatch.setattr("prompt2play.validation.runner.subprocess.run", execute)
    with pytest.raises(ValueError, match="does not match trusted checking code"):
        IsolatedValidator("fixture:stale").preflight()
    assert len(commands) == 2
    assert "--network=none" in commands[1] and "--read-only" in commands[1]
    assert not any(a in ("--mount", "-v") for a in commands[1])


def test_successful_preflight_cache_is_bound_to_image_and_current_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner._preflight_image.cache_clear()
    source = tmp_path / "release_runtime.mjs"
    source.write_text("trusted fixture")
    monkeypatch.setattr(IsolatedValidator, "runtime_path", source)
    monkeypatch.setattr(
        "prompt2play.validation.runner.shutil.which", lambda _name: "/fixture/docker"
    )
    inspected = []

    def execute(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[1] == "image":
            data = "sha256:" + "b" * 64
        else:
            inspected.append(args)
            data = json.dumps({source.name: hashlib.sha256(source.read_bytes()).hexdigest()})
        return subprocess.CompletedProcess(args, 0, data)

    monkeypatch.setattr("prompt2play.validation.runner.subprocess.run", execute)
    validator = IsolatedValidator("fixture:current")
    validator.preflight()
    validator.preflight()
    assert len(inspected) == 1
    source.write_text("updated trusted fixture")
    validator.preflight()
    assert len(inspected) == 2


def test_missing_environment_prevents_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("prompt2play.validation.runner.shutil.which", lambda _name: None)
    with pytest.raises(ValueError, match="no model call made"):
        IsolatedValidator("fixture:missing").preflight()
