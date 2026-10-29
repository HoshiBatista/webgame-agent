"""Plain user-facing replies, separate from internal run diagnostics."""

import re

MAX_PLAYER_MESSAGE_LENGTH = 1000

# A conservative fallback for models that ignore the player-facing reply policy.
# Do not partially redact a technical explanation into misleading fragments.
_IMPLEMENTATION = re.compile(
    r"[`{}]|</?[a-z][^>]*>|\b[\w./-]+\.(?:js|ts|tsx|jsx|html|css|json|py)\b"
    r"|\b\w+_\w+\b|(?-i:\b[a-z]+[A-Z][a-zA-Z]*\b)|\b\w+\([^)]*\)"
    r"|\b(?:html5?|css|javascript|typescript|canvas\w*|webgl|dom|json|api|sdk|npm|cdn|fps|"
    r"runtime|patch|diff|selector|function|const|let|var|return|undefined|null|nan|"
    r"syntaxerror|referenceerror|typeerror)\b"
    r"|\b(?:код(?:а|е|ом|у)?|исходник\w*|файл\w*|функци\w*|переменн\w*|"
    r"обработчик\w*|селектор\w*|патч\w*|библиотек\w*|рендер\w*|валидатор\w*|"
    r"компиля\w*|синтакси\w*|рефактор\w*)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_CLAIM = re.compile(
    r"\b(?:провер(?:ил\w*|ен\w*|к\w*)|протест\w*|тест(?:ы|ов|ирование|ирования)|"
    r"безупреч\w*|идеальн\w*|безошибоч\w*|гарантир\w*)\b"
    r"|без\s+(?:ошибок|багов)|на\s+(?:всех|любых)\s+устройствах"
    r"|\b(?:tested|verified|flawless|bug.free)\b",
    re.IGNORECASE,
)


def player_message(value):
    """Keep bounded player prose; original responses remain private on Invocation."""
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    if len(value) > MAX_PLAYER_MESSAGE_LENGTH or _IMPLEMENTATION.search(value) or _UNSUPPORTED_CLAIM.search(value):
        return ""
    return value


def assistant_reply(status, message, model_message="", *, has_candidate=False, response_status="",
                    operation="create", error_code="", has_source=False, planning_failed=False,
                    plan_without_game=False, checks_passed=False, manually_confirmed=False):
    model_message = player_message(model_message)
    if status == "succeeded" and manually_confirmed:
        return "Игра сохранена после вашей проверки. Можно играть и продолжать доработку."
    if (response_status == "scope_refusal" or error_code == "scope_refusal") and error_code in {"", "scope_refusal"} and status not in {"unknown", "cancelled", "unverified"}:
        return model_message or "Этот замысел пока не удаётся воплотить в небольшой игре. Попробуйте упростить запрос."
    if response_status == "unchanged" and not error_code and status not in {"failed", "unknown", "cancelled", "unverified"}:
        return f"Изменения не внесены. {model_message or 'Уточните, что хотите изменить в игре.'}"
    if status == "succeeded":
        if checks_passed:
            result = model_message or ("Проверка игры завершена." if operation == "recheck" else "Игра готова.")
            return f"{result} Выполненные проверки пройдены — можно пробовать играть."
        return "Игра сохранена. Полную проверку подтвердить не удалось; попробуйте сыграть."
    if status == "unknown":
        return "Не удалось получить ответ полностью. Сохранённая игра осталась на месте. Можно отправить новый запрос."
    if status == "cancelled":
        return "Генерация остановлена. Сохранённые версии игры доступны в меню у поля ввода."
    if error_code == "test_only_change":
        return "Доработка пока не изменила саму игру. Сохранённая версия доступна; можно повторить её проверку или уточнить правку."
    if error_code == 'response_output_limit':
        return "Ответ модели оказался слишком длинным и прервался. Полученные части игры и замысел сохранены. Можно продолжить создание."
    if error_code == 'invalid_response_completion':
        return "Не удалось собрать полную игру из полученных частей. Замысел и ответы сохранены; создание ещё не завершено."
    if planning_failed:
        return "Не удалось завершить подготовку игрового замысла. Сохранённый запрос доступен для продолжения."
    if plan_without_game:
        return "Игровой замысел сохранён, но сама игра ещё не готова. Можно продолжить с этого плана."
    if has_candidate and error_code in {"validator_unavailable", "browser_watchdog", "validator_failed"}:
        return "Игра сохранена. Проверка временно недоступна; повторите проверку без изменения игры."
    if has_candidate and error_code in {"repair_exhausted", "no_progress", "repair_regression"}:
        return "Версия игры сохранена, но обнаруженные проблемы не удалось исправить. Можно продолжить доработку." + (" Прежняя рабочая версия сохранена." if has_source else "")
    if has_candidate:
        return "Версия игры сохранена, но её работу пока не удалось полностью проверить. Попробуйте сыграть. Если что-то нужно исправить, напишите об этом."
    if status in {"failed", "needs_attention"}:
        if operation != "create" and has_source:
            return "Не удалось применить доработку. Предыдущая версия игры сохранена и доступна. Попробуйте уточнить правку."
        return "Не удалось завершить создание игры. Попробуйте уточнить запрос и отправить его ещё раз."
    return "Не удалось завершить запрос. Попробуйте ещё раз."


def run_reply(run, model_message="", *, response_status=""):
    """Verification wording comes only from the report for the selected result."""
    revision = run.result_revision if run.result_revision_id else None
    checked = False
    if run.status == "succeeded" and revision and revision.verification == "automatic":
        from validation.checks import review_checks

        report = revision.reports.order_by("-id").first()
        checks, _ = review_checks(revision.checks)
        evidence = (report.assessment.get("artifact_evidence") or {}) if report else {}
        checked = bool(
            report and report.status == "passed" and report.checks == checks
            and evidence.get("artifact_hash") == revision.artifact_hash
            and report.assessment.get("action") == "accept" and report.assessment.get("gates_passed") is True
        )
    return assistant_reply(
        run.status, run.message, model_message, has_candidate=bool(run.candidate_revision_id),
        response_status=response_status, operation=run.operation, error_code=(run.error or {}).get("code", ""),
        has_source=bool(run.source_revision_id or run.base_revision_id),
        planning_failed=run.planning_required and not run.game_plan,
        plan_without_game=bool(run.game_plan) and not (run.candidate_revision_id or run.source_revision_id or run.base_revision_id),
        checks_passed=checked, manually_confirmed=bool(revision and revision.verification == "manual"),
    )
