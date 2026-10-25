"""Plain user-facing replies, separate from internal run diagnostics."""


def assistant_reply(status, message, model_message="", *, has_candidate=False, response_status=""):
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
    if has_candidate:
        return "Версия игры сохранена, но её работу пока не удалось полностью проверить. Попробуйте сыграть. Если что-то нужно исправить, напишите об этом."
    if status in {"failed", "needs_attention"}:
        return "Не удалось завершить создание игры. Попробуйте уточнить запрос и отправить его ещё раз."
    return message
