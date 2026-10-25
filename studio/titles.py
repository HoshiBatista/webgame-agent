"""Short automatic chat labels; manual names remain untouched."""

import re

DEFAULT_CHAT_TITLE = "Новая игра"


def short_game_title(title: str) -> str:
    text = " ".join(title.split()).strip(' \"«»“”.,:;!?')
    text = re.sub(r"^(?:название(?: игры)?|мини-игра|игра)\s*[:—–-]\s*", "", text, flags=re.I)
    words = text.split()[:3]
    while words and words[-1].lower().strip(".,:;") in {"и", "в", "на", "с", "для", "про", "по", "of", "the", "and"}:
        words.pop()
    value = " ".join(words)[:48].rstrip(" ,.;:!?—–-")
    return value[:1].upper() + value[1:] if value else DEFAULT_CHAT_TITLE


def title_from_prompt(prompt: str) -> str:
    text = " ".join(prompt.split())
    text = re.sub(r"^(?:пожалуйста[, ]+)?(?:сделай|создай|сгенерируй|разработай|хочу)\s+(?:мне\s+)?", "", text, flags=re.I)
    text = re.sub(r"^(?:простую\s+|небольшую\s+)?(?:мини[ -]игру|игру)\s+(?:про\s+)?", "", text, flags=re.I)
    return short_game_title(text)
