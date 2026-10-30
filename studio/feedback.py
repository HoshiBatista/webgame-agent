"""Saved review fields and background-job creation. No provider/broker calls in HTTP."""

from django.conf import settings

from .model_profiles import can_use_pro, configured_profiles
from .models import FeedbackProcessing
from .services import DomainError

REASONS = (
    "Более понятное управление", "Лучше визуальное оформление", "Более интересная механика",
    "Точнее следовать запросу", "Уделить внимание звуку", "Крупнее текст и элементы управления",
)


def fields(feedback):
    if feedback.selected_reasons is not None:
        return feedback.selected_reasons, feedback.custom_reason
    # Older reviews stored checkboxes and free text together. Preserve both on read.
    return ([reason for reason in feedback.reasons if reason in REASONS],
            "\n".join(reason for reason in feedback.reasons if reason not in REASONS))


def parse(data):
    if not isinstance(data, dict):
        raise DomainError("invalid_review", "Проверьте поля отзыва.")
    rating = data.get("rating")
    if type(rating) is not int or not 1 <= rating <= 5:
        raise DomainError("invalid_rating", "Оценка должна быть от 1 до 5.")
    if "selected_reasons" in data or "custom_reason" in data:
        selected = data.get("selected_reasons", [])
        custom = data.get("custom_reason", "")
        if (not isinstance(selected, list) or not all(isinstance(s, str) and s in REASONS for s in selected)
                or len(selected) != len(set(selected)) or not isinstance(custom, str) or len(custom) > 300):
            raise DomainError("invalid_reasons", "Выберите пожелания из списка и добавьте текст до 300 символов.")
        reasons = [*selected, *([custom] if custom.strip() else [])]
    else:
        reasons = data.get("reasons", [])
        if not isinstance(reasons, list) or not all(isinstance(s, str) and len(s) <= 300 for s in reasons):
            raise DomainError("invalid_reasons", "Добавьте до пяти коротких пожеланий.")
        selected, custom = None, ""
    if len(reasons) > 5:
        raise DomainError("invalid_reasons", "Добавьте до пяти коротких пожеланий.")
    return {"rating": rating, "reasons": reasons, "selected_reasons": selected, "custom_reason": custom}


def enqueue(feedback, preference, request):
    selected, custom = fields(feedback)
    if not selected and not custom.strip():
        return
    profile_id = preference.model_profile or "pro"
    profile = configured_profiles()[profile_id]
    provider, model = profile["provider"], profile["model"]
    if settings.GAMEFORGE_PROVIDER == "fake":
        provider, model = "fake", "fixture"
    denied = provider in {"codex", "codex_api"} and (
        not settings.GAMEFORGE_PRO_ENABLED or not can_use_pro(request)
    )
    FeedbackProcessing.objects.create(
        feedback=feedback, user=feedback.user, model_profile=profile_id, provider=provider, model=model,
        status="failed" if denied else "queued",
        error={"code": "model_unavailable"} if denied else {},
    )


def data(feedback):
    if feedback is None:
        return None
    selected, custom = fields(feedback)
    job = getattr(feedback, "processing", None)
    return {"id": feedback.id, "rating": feedback.rating, "selected_reasons": selected,
            "custom_reason": custom, "processing_status": job.status if job else "none"}
