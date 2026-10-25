"""Deterministic chat labels; no model calls or generated game changes."""

DEFAULT_CHAT_TITLE = "Новая игра"


def title_from_prompt(prompt: str) -> str:
    text = " ".join(prompt.split())
    if len(text) <= 60:
        return text or DEFAULT_CHAT_TITLE
    prefix = text[:59]
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return prefix.rstrip(" ,.;:!?—-") + "…"
