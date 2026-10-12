"""Immutable artifact store tests."""

from pathlib import Path
from uuid import uuid4

import pytest

from prompt2play.adapters.artifacts import MAX_HTML_BYTES, ArtifactStore
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
    store = ArtifactStore(tmp_path)
    html = "<!doctype html><title>game</title>"
    first = store.commit(html, make_spec(), uuid4())
    second = store.commit(html, make_spec(), uuid4())
    assert first == second
    assert store.read_html(first.digest) == html

    store.write_validation(uuid4(), {"passed": True})
    with pytest.raises(ValueError):
        store.read_html("../escape")


def test_commit_rejects_oversized_games(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="artifact limit"):
        store.commit("x" * (MAX_HTML_BYTES + 1), make_spec(), uuid4())
