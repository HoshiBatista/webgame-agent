import json

import pytest

from generation.prompts import build_messages, system_prompt
from studio.replies import assistant_reply
from studio.titles import short_game_title, title_from_prompt


@pytest.mark.parametrize("title,expected", [
    ("  Звёздный\n сад ", "Звёздный сад"),
    ("Название игры: Космический раннер с уровнями и монетами", "Космический раннер"),
    ("Игра — Найди пару", "Найди пару"),
    ("", "Новая игра"),
])
def test_generated_labels_are_short_without_cutting_at_a_preposition(title, expected):
    assert short_game_title(title) == expected
    assert len(short_game_title(title).split()) <= 3


def test_prompt_label_omits_the_request_verb_and_audience_reaches_the_model():
    assert title_from_prompt("Создай мне простую игру про звёзды") == "Звёзды"
    child = json.loads(build_messages({"audience": "children"})[1]["content"])
    senior = json.loads(build_messages({"audience": "seniors"})[1]["content"])
    assert child["audience"] == "children"
    assert "forgiving difficulty" in child["audience_guidance"]
    assert "Large readable text" in senior["audience_guidance"]
    for profile in ("full", "compact"):
        assert "1-3 words" in system_prompt({"generation_profile": profile})


def test_reply_uses_the_model_text_only_for_a_verified_result():
    assert assistant_reply("succeeded", "Internal", "Соберите пять звёзд.") == "Соберите пять звёзд."
    reply = assistant_reply("unverified", "Подтвердите результат", "Всё проверено!", has_candidate=True)
    assert "сохранена" in reply
    assert "Всё проверено" not in reply
    assert "подтвердите" not in reply.lower()
    assert "ещё раз" in assistant_reply("failed", "Internal syntax details")


def test_unchanged_reply_explains_why_no_edit_was_needed():
    reply = assistant_reply("needs_attention", "Internal", "Игра уже использует стрелки.",
                            response_status="unchanged")
    assert reply == "Изменения не внесены. Игра уже использует стрелки."
