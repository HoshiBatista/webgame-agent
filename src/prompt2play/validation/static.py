"""Deterministic release checks for generated single-file games."""

from __future__ import annotations

import re

from prompt2play.contracts import Finding

RULES: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    (
        "REMOTE_RESOURCE",
        re.compile(
            r"https?://|(?:src|href)\s*=\s*[\"']//|url\(\s*//|"
            r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(",
            re.I,
        ),
        "Игра пытается обратиться к сети.",
        "Удалить внешние URL и сетевые API; встроить всё в HTML.",
    ),
    (
        "DANGEROUS_EXECUTION",
        re.compile(r"\beval\s*\(|\bnew\s+Function\s*\(|document\.write\s*\(", re.I),
        "Обнаружено динамическое выполнение кода.",
        "Заменить динамическое выполнение обычными функциями.",
    ),
    (
        "ESCAPE_NAVIGATION",
        re.compile(r"window\.open\s*\(|location\.(?:href|assign|replace)\s*[=(]", re.I),
        "Игра может покинуть preview-контекст.",
        "Удалить навигацию, pop-up и скачивания.",
    ),
    (
        "BLOCKING_DIALOG",
        re.compile(r"\b(?:alert|confirm|prompt)\s*\(", re.I),
        "Используется блокирующий диалог браузера.",
        "Показывать сообщения внутри игрового интерфейса.",
    ),
)


def validate_html(html: str) -> tuple[list[Finding], list[str]]:
    """Return release findings and names of checks that passed."""

    findings: list[Finding] = []
    checks: list[str] = []
    normalized = html.lstrip().lower()
    if not normalized.startswith("<!doctype html>"):
        findings.append(
            Finding(
                code="DOCTYPE_MISSING",
                severity="error",
                message="Документ не начинается с HTML5 doctype.",
                repair_hint="Начать html с <!doctype html>.",
            )
        )
    else:
        checks.append("html5_doctype")

    required = {
        "CANVAS_OR_GAME_UI_MISSING": (r"<canvas\b|id=[\"'][^\"']*(?:game|board)", "игровая сцена"),
        "START_CONTROL_MISSING": (r"старт|начать|играть|start", "видимая кнопка старта"),
        "RESTART_CONTROL_MISSING": (r"заново|рестарт|ещ[её] раз|restart", "действие рестарта"),
        "TOUCH_INPUT_MISSING": (r"pointer(?:down|up|move)|touchstart", "touch/pointer управление"),
        "KEYBOARD_INPUT_MISSING": (r"key(?:down|up)", "keyboard управление"),
        "RESPONSIVE_MISSING": (r"devicepixelratio|resize", "адаптивный resize/DPR"),
        "TEST_BRIDGE_MISSING": (r"__prompt2play", "тестовый bridge"),
        "WIN_SCENARIO_MISSING": (r"force_win", "детерминированный сценарий победы"),
        "LOSE_SCENARIO_MISSING": (r"force_lose", "детерминированный сценарий поражения"),
        "GAME_LOOP_MISSING": (r"requestanimationframe|setinterval", "игровой цикл"),
    }
    for code, (required_pattern, label) in required.items():
        if re.search(required_pattern, html, re.I):
            checks.append(label)
        else:
            findings.append(
                Finding(
                    code=code,
                    severity="error",
                    message=f"Не найдено обязательное требование: {label}.",
                    repair_hint=f"Добавить {label} и связать его с игровым состоянием.",
                )
            )

    for code, rule_pattern, message, hint in RULES:
        if rule_pattern.search(html):
            findings.append(Finding(code=code, severity="error", message=message, repair_hint=hint))
        else:
            checks.append(code.lower())
    return findings, checks
