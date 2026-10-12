"""Task-specific golden evaluation tests."""

import json
from pathlib import Path

import pytest

from prompt2play.contracts import GameSpec, Rubric
from prompt2play.evaluation import GoldenCase, load_golden_cases, score_candidate

pytestmark = pytest.mark.ai_contract

ROOT = Path(__file__).parents[2]


def representative_spec() -> GameSpec:
    return GameSpec(
        title="Змейка",
        genre="arcade",
        audience="бабушка и пожилые игроки",
        player_goal="Собрать десять яблок",
        core_loop="Двигаться по сетке и собирать яблоки",
        controls=["keyboard", "pointer", "touch"],
        visual_direction="Высокий контраст и крупные формы",
        accessibility=["крупные кнопки", "медленный темп"],
        win_condition="Собрано десять яблок",
        lose_condition="Столкновение со стеной",
        rubrics=[
            Rubric(id=f"r{index}", description="Наблюдаемое действие", verification="bridge")
            for index in range(3)
        ],
    )


def test_golden_dataset_has_typical_edge_and_adversarial_cases() -> None:
    cases = load_golden_cases(ROOT / "golden/evals/cases.json")
    assert len(cases) >= 7
    assert len({case.id for case in cases}) == len(cases)
    assert {"snake_grandmother", "minimal_prompt", "prompt_injection"} <= {
        case.id for case in cases
    }


def test_candidate_scorer_accepts_complete_offline_game() -> None:
    case = GoldenCase(
        id="snake",
        prompt="Змейка для бабушки",
        expected_genres=["arcade"],
        audience_terms=["бабуш"],
    )
    html = (ROOT / "golden/smoke-game/index.html").read_text(encoding="utf-8")
    score = score_candidate(case, representative_spec(), html)
    assert score.passed
    assert score.score == 1
    assert all(score.criteria.values())


def test_candidate_scorer_rejects_network_and_missing_analytics() -> None:
    case = GoldenCase(
        id="unsafe",
        prompt="Аркада для бабушки",
        expected_genres=["arcade"],
        audience_terms=["бабуш"],
    )
    html = "<!doctype html><canvas id='game'></canvas>" + "x" * 1200 + "https://evil.test"
    score = score_candidate(case, representative_spec(), html)
    assert not score.passed
    assert "REMOTE_RESOURCE" in score.finding_codes
    assert not score.criteria["host_analytics"]


def test_golden_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    item = {
        "id": "duplicate",
        "prompt": "Достаточно длинный prompt",
        "expected_genres": ["arcade"],
        "audience_terms": ["все"],
    }
    path.write_text(json.dumps([item, item]), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_golden_cases(path)
