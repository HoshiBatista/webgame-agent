"""Deterministic policy for preserving mechanics during targeted revisions."""

from __future__ import annotations

from prompt2play.contracts import Finding, GameSpec

MECHANIC_FIELDS = (
    "genre",
    "player_goal",
    "core_loop",
    "controls",
    "win_condition",
    "lose_condition",
)
TARGETED_TERMS = (
    "цвет",
    "красн",
    "зелен",
    "зелён",
    "син",
    "желт",
    "жёлт",
    "черн",
    "чёрн",
    "бел",
    "фон",
    "кноп",
    "размер",
    "крупн",
    "мелк",
    "скорост",
    "темп",
    "контраст",
    "звук",
    "музык",
    "громк",
    "шрифт",
    "текст",
)
STRUCTURAL_TERMS = (
    "жанр",
    "механик",
    "правил",
    "управлен",
    "цель",
    "побед",
    "поражен",
    "уров",
)


def is_targeted_revision(instruction: str | None) -> bool:
    """Return whether an instruction is a bounded presentation or tuning change."""

    normalized = (instruction or "").casefold()
    return (
        bool(normalized)
        and any(term in normalized for term in TARGETED_TERMS)
        and not any(term in normalized for term in STRUCTURAL_TERMS)
    )


def preserve_revision_invariants(
    parent: GameSpec, candidate: GameSpec, instruction: str | None
) -> GameSpec:
    """Keep mechanics stable when the user requested only a targeted change."""

    if not is_targeted_revision(instruction):
        return candidate
    return candidate.model_copy(
        update={field: getattr(parent, field) for field in MECHANIC_FIELDS}, deep=True
    )


def validate_revision_invariants(
    parent: GameSpec, candidate: GameSpec, instruction: str | None
) -> tuple[list[Finding], list[str]]:
    """Report unexpected mechanic drift in a targeted child revision."""

    if not is_targeted_revision(instruction):
        return [], ["revision_invariants: structural change allowed"]
    changed = [
        field for field in MECHANIC_FIELDS if getattr(parent, field) != getattr(candidate, field)
    ]
    if not changed:
        return [], ["revision_invariants: mechanics preserved"]
    return (
        [
            Finding(
                code="REVISION_MECHANICS_DRIFT",
                severity="error",
                message="Точечная правка неожиданно изменила: " + ", ".join(changed),
                repair_hint="Сохранить механику родительской игры и изменить только запрошенные свойства.",
            )
        ],
        [],
    )
