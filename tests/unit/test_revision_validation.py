"""Targeted revision invariants."""

from prompt2play.contracts import GameSpec, Rubric
from prompt2play.validation.revision import (
    is_targeted_revision,
    preserve_revision_invariants,
    validate_revision_invariants,
)


def make_spec(**changes: object) -> GameSpec:
    values: dict[str, object] = {
        "title": "Змейка",
        "genre": "arcade",
        "audience": "все",
        "player_goal": "Собрать десять яблок",
        "core_loop": "Двигаться по сетке и собирать яблоки",
        "controls": ["keyboard", "pointer", "touch"],
        "visual_direction": "Зелёная змейка на тёмном поле",
        "accessibility": ["крупные кнопки"],
        "win_condition": "Собрано десять яблок",
        "lose_condition": "Столкновение со стеной",
        "rubrics": [
            Rubric(id=str(index), description="Проверяемое действие", verification="bridge")
            for index in range(3)
        ],
    }
    values.update(changes)
    return GameSpec.model_validate(values)


def test_targeted_revision_preserves_mechanics_but_allows_visual_change() -> None:
    parent = make_spec()
    candidate = make_spec(
        genre="runner",
        core_loop="Бежать и прыгать",
        controls=["touch"],
        visual_direction="Красная змейка на светлом поле",
    )

    preserved = preserve_revision_invariants(parent, candidate, "Сделай змейку красной")

    assert preserved.genre == parent.genre
    assert preserved.core_loop == parent.core_loop
    assert preserved.controls == parent.controls
    assert preserved.visual_direction == candidate.visual_direction
    findings, checks = validate_revision_invariants(parent, preserved, "Сделай змейку красной")
    assert findings == []
    assert checks == ["revision_invariants: mechanics preserved"]


def test_targeted_revision_reports_unexpected_mechanics_drift() -> None:
    parent = make_spec()
    changed = make_spec(win_condition="Дойти до финиша")

    findings, checks = validate_revision_invariants(parent, changed, "Увеличь кнопки")

    assert checks == []
    assert [finding.code for finding in findings] == ["REVISION_MECHANICS_DRIFT"]
    assert "win_condition" in findings[0].message


def test_structural_revision_may_change_mechanics() -> None:
    assert is_targeted_revision("Сделай кнопки крупнее")
    assert not is_targeted_revision("Добавь второй уровень и сделай кнопки крупнее")
    parent = make_spec()
    changed = make_spec(core_loop="Два уровня с разными препятствиями")
    assert preserve_revision_invariants(parent, changed, "Добавь второй уровень") is changed
    assert validate_revision_invariants(parent, changed, "Добавь второй уровень") == (
        [],
        ["revision_invariants: structural change allowed"],
    )


def test_presentation_verbs_do_not_disable_mechanic_protection() -> None:
    assert is_targeted_revision("Добавь музыку")
    assert is_targeted_revision("Замени цвет змейки на жёлтый")
    assert is_targeted_revision("Убери звук")
    assert not is_targeted_revision("Добавь уровни и музыку")
