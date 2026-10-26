"""Plain user-facing replies, separate from internal run diagnostics."""


def assistant_reply(status, message, model_message="", *, has_candidate=False, response_status="",
                    operation="create", error_code="", has_source=False, planning_failed=False,
                    plan_without_game=False):
    if response_status == "scope_refusal":
        return model_message.strip() or message
    if response_status == "unchanged" and model_message.strip():
        return f"Изменения не внесены. {model_message.strip()}"
    if status == "succeeded":
        return model_message.strip() or "Игра готова. Откройте её и попробуйте сыграть. Что хотите изменить?"
    if status == "unknown":
        return "Не удалось получить ответ полностью. Сохранённая игра осталась на месте. Можно отправить новый запрос."
    if status == "cancelled":
        return "Генерация остановлена. Сохранённые версии игры доступны в меню у поля ввода."
    if error_code == "test_only_change":
        return "Модель предложила изменить только проверки, не исправив саму игру. Изменения не применены. Сохранённая версия доступна; можно отдельно повторить её проверку или уточнить правку."
    if planning_failed:
        return "Не удалось завершить подготовку игрового замысла. Сохранённый запрос доступен для продолжения."
    if plan_without_game:
        return "Игровой замысел сохранён, но создание кода ещё не завершено. Можно продолжить с этого плана."
    if has_candidate:
        return "Версия игры сохранена, но её работу пока не удалось полностью проверить. Попробуйте сыграть. Если что-то нужно исправить, напишите об этом."
    if status in {"failed", "needs_attention"}:
        if operation != "create" and has_source:
            return "Не удалось применить доработку. Предыдущая версия игры сохранена и доступна. Попробуйте уточнить правку."
        return "Не удалось завершить создание игры. Попробуйте уточнить запрос и отправить его ещё раз."
    return message
