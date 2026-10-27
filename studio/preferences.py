"""Bound user-authored context without limiting its number of paragraphs."""

from .services import DomainError

NOTES_LIMIT = 2500


def validate_notes(notes):
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        raise DomainError("invalid_preferences", "Пожелания должны быть текстом.")
    text = "\n".join(notes)
    if len(text) > NOTES_LIMIT:
        raise DomainError("invalid_preferences", f"Пожелания не должны превышать {NOTES_LIMIT} символов.")
    return text.strip().split("\n") if text.strip() else []


def add_feedback_notes(notes, reasons):
    """Keep existing text; never truncate a wish or silently remove older ones."""
    result = list(notes)
    skipped = False
    for reason in dict.fromkeys(s.strip() for s in reasons if s.strip()):
        if reason in result:
            continue
        if len("\n".join([*result, reason])) <= NOTES_LIMIT:
            result.append(reason)
        else:
            skipped = True
    return result, skipped
