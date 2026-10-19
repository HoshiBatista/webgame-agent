"""Immutable artifact store tests."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest

from prompt2play.adapters.artifacts import MAX_HTML_BYTES, ArtifactIntegrityError, ArtifactStore
from prompt2play.contracts import GameSpec, Rubric


def make_spec() -> GameSpec:
    return GameSpec(
        title="Пчелиный рывок",
        genre="arcade",
        audience="дети",
        player_goal="Собрать мёд",
        core_loop="Летать, собирать соты и избегать птиц",
        controls=["pointer", "keyboard"],
        visual_direction="Яркие крупные формы",
        accessibility=["высокий контраст"],
        win_condition="Собрано десять сот",
        lose_condition="Закончились три жизни",
        rubrics=[
            Rubric(id=f"r{index}", description="Наблюдаемое действие", verification="snapshot")
            for index in range(3)
        ],
    )


def test_commit_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    evidence_root = tmp_path / "separate-evidence"
    store = ArtifactStore(tmp_path / "artifacts", evidence_root)
    html = "<!doctype html><title>game</title>"
    first = store.commit(html, make_spec(), uuid4())
    second = store.commit(html, make_spec(), uuid4())
    assert first == second
    assert store.read_html(first.digest) == html

    revision_id = uuid4()
    store.write_validation(revision_id, {"passed": True})
    assert (evidence_root / str(revision_id) / "validation" / "report.json").is_file()
    with pytest.raises(ValueError):
        store.read_html("../escape")


def test_commit_rejects_oversized_games(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="artifact limit"):
        store.commit("x" * (MAX_HTML_BYTES + 1), make_spec(), uuid4())


def test_concurrent_identical_commits_accept_the_verified_winner(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    barrier = Barrier(2)
    original_rename = os.rename
    html = "<!doctype html><title>concurrent game</title>"

    def synchronized_rename(source: Path, target: Path) -> None:
        barrier.wait(timeout=5)
        original_rename(source, target)

    with (
        patch("prompt2play.adapters.artifacts.os.rename", side_effect=synchronized_rename),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        first = pool.submit(store.commit, html, make_spec(), uuid4())
        second = pool.submit(store.commit, html, make_spec(), uuid4())
        assert first.result() == second.result()
    assert store.read_html(first.result().digest) == html
    assert list(store.staging.iterdir()) == []


def test_changed_artifact_is_rejected_by_read_browser_path_and_reuse(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    html = "<!doctype html><title>original</title>"
    saved = store.commit(html, make_spec(), uuid4())
    store.entrypoint_path(saved.digest).write_text("<!doctype html><title>tampered</title>")
    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        store.read_html(saved.digest)
    with pytest.raises(ArtifactIntegrityError):
        store.entrypoint_path(saved.digest)
    with pytest.raises(ArtifactIntegrityError):
        store.commit(html, make_spec(), uuid4())
