import json

import pytest

from generation.prompts import build_messages, system_prompt
from generation.schema import response_schema
from studio.replies import assistant_reply, player_message
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
    assert assistant_reply("succeeded", "Internal", "Соберите пять звёзд.", checks_passed=True) == (
        "Соберите пять звёзд. Выполненные проверки пройдены — можно пробовать играть."
    )
    assert "подтвердить не удалось" in assistant_reply("succeeded", "Internal", "Всё проверено!")
    reply = assistant_reply("unverified", "Подтвердите результат", "Всё проверено!", has_candidate=True)
    assert "сохранена" in reply
    assert "Всё проверено" not in reply
    assert "подтвердите" not in reply.lower()
    assert "ещё раз" in assistant_reply("failed", "Internal syntax details")


def test_unchanged_reply_explains_why_no_edit_was_needed():
    reply = assistant_reply("needs_attention", "Internal", "Игра уже использует стрелки.",
                            response_status="unchanged")
    assert reply == "Изменения не внесены. Игра уже использует стрелки."


@pytest.mark.parametrize('model_status', ['', 'ok', 'unchanged', 'scope_refusal'])
def test_server_evidence_has_priority_over_a_models_completion_message(model_status):
    unavailable = assistant_reply('failed', 'Internal', 'Всё готово!', has_candidate=True,
                                   response_status=model_status, error_code='validator_unavailable')
    defect = assistant_reply('needs_attention', 'Internal', 'Всё готово!', has_candidate=True,
                              response_status=model_status, error_code='no_progress')
    uncertain = assistant_reply('unverified', 'Internal', 'Всё готово!', has_candidate=True,
                                 response_status=model_status, error_code='manual_verification')
    assert 'временно недоступна' in unavailable and 'без изменения' in unavailable
    assert 'обнаруженные проблемы' in defect
    assert 'полностью проверить' in uncertain
    assert all('Всё готово' not in reply for reply in [unavailable, defect, uncertain])


@pytest.mark.parametrize("profile", ["full", "compact"])
@pytest.mark.parametrize("operation", ["create", "edit", "repair", "check_repair", "plan"])
def test_every_public_model_reply_uses_player_language_and_source_steps_self_review(profile, operation):
    prompt = system_prompt({"generation_profile": profile, "operation": operation})
    assert "PLAYER-FACING REPLY" in prompt
    assert "no programming knowledge" in prompt
    assert "1-2 short sentences" in prompt
    assert "AFTER checking this exact version" in prompt
    assert ("QUICK FINAL REVIEW" in prompt) == (operation in {"create", "edit", "repair"})


@pytest.mark.parametrize("operation", ["checks_create", "visual_patch"])
def test_optional_stages_follow_the_same_public_reply_policy(operation):
    prompt = system_prompt({"generation_profile": "compact", "operation": operation})
    assert "PLAYER-FACING REPLY" in prompt
    assert ("QUICK FINAL REVIEW" in prompt) == (operation == "visual_patch")


@pytest.mark.parametrize("profile", ["full", "compact"])
@pytest.mark.parametrize("operation", ["create", "edit", "repair", "visual_patch"])
@pytest.mark.parametrize("source_format", ["string", "lines"])
def test_model_receives_the_final_reply_field_after_the_implementation(profile, operation, source_format):
    request = {"generation_profile": profile, "operation": operation, "source_format": source_format}
    schema = response_schema(request)
    assert list(schema["properties"])[-1] == "message"
    assert schema["required"][-1] == "message"
    assert "Return message last" in system_prompt(request)


@pytest.mark.parametrize("text", [
    "Обновил game.js и styles.css.",
    "Исправлена функция движения и обработчик нажатий.",
    "Добавлен requestAnimationFrame и GameForgeMotion.",
    "Теперь player_speed учитывается при движении.",
    "Вызывается resetGame() перед стартом.",
    "Игра использует Canvas и DOM.",
    "Изменил `score`.",
    "<script>alert(1)</script>",
    "Всё проверено, ошибок нет!",
    "Я проверил игру на телефоне.",
    "Проверки пройдены.",
    "Игра идеально работает на всех устройствах.",
    "Игра без ошибок и багов.",
    "Длинное объяснение. " * 50,
])
def test_technical_or_unsubstantiated_model_messages_use_a_plain_fallback(text):
    assert player_message(text) == ""
    assert assistant_reply("succeeded", "Internal syntax details", text, checks_passed=True) == (
        "Игра готова. Выполненные проверки пройдены — можно пробовать играть."
    )
    for response_status in ("scope_refusal", "unchanged"):
        reply = assistant_reply("needs_attention", "Internal syntax details", text, response_status=response_status)
        assert text not in reply and "Internal" not in reply


def test_player_quality_details_are_preserved_without_an_extra_technical_report():
    text = "Собирайте звёзды касанием. Крупные кнопки и постепенное ускорение помогают освоиться."
    assert player_message(text) == text
    assert assistant_reply("succeeded", "Internal", text, checks_passed=True).startswith(text)
    manual = assistant_reply("succeeded", "Internal", "Всё проверено!", manually_confirmed=True)
    assert "вашей проверки" in manual and "пройдены" not in manual
