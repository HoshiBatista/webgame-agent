"""Server-owned model choices. Client input never supplies a provider or credentials."""

import os
from urllib.parse import urlparse

from django.conf import settings

PRO_MODEL = "gpt-6-sol"


def configured_profiles():
    default_api = settings.GAMEFORGE_PROVIDER in {"vllm", "relay"}
    return {
        "pro": {"id": "pro", "name": "Pro", "description": "Codex · GPT-6 Sol",
                "provider": "codex", "model": PRO_MODEL},
        "lite": {"id": "lite", "name": "Lite", "description": "Модель через API",
                 "provider": settings.GAMEFORGE_LITE_PROVIDER or (
                     settings.GAMEFORGE_PROVIDER if default_api else "vllm"),
                 "model": settings.GAMEFORGE_LITE_MODEL or (
                     settings.GAMEFORGE_MODEL if default_api else
                     os.environ.get("GAMEFORGE_VLLM_MODEL") or os.environ.get("LLM_MODEL", ""))},
    }


def local_operator(request):
    return bool(
        settings.GAMEFORGE_LOCAL_ONLY
        and urlparse(settings.GAMEFORGE_APP_ORIGIN).hostname in {"localhost", "127.0.0.1", "::1"}
        and urlparse("//" + request.get_host()).hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
        and request.META.get("REMOTE_ADDR") in {"127.0.0.1", "::1"}
        and request.user is not None
        and request.user.is_authenticated
        and request.user.is_staff
    )


def can_use_pro(request):
    if settings.GAMEFORGE_PRO_ACCESS == "local":
        return local_operator(request)
    origin = urlparse(settings.GAMEFORGE_APP_ORIGIN)
    return bool(
        settings.GAMEFORGE_PRO_ACCESS == "restricted"
        and not settings.GAMEFORGE_LOCAL_ONLY
        and origin.scheme == "https"
        and request.is_secure()
        and request.get_host() == origin.netloc
        and request.user is not None
        and request.user.is_authenticated
        and request.user.is_active
        and request.user.pk in settings.GAMEFORGE_PRO_USER_IDS
    )


def unavailable_reason(profile, request=None):
    if profile["id"] == "pro":
        if not settings.GAMEFORGE_PRO_ENABLED:
            return "Pro не включён на этом сервере."
        if settings.GAMEFORGE_PRO_ACCESS == "local" and not settings.GAMEFORGE_LOCAL_ONLY:
            return "Pro доступен только локальному администратору."
        if request is not None and not can_use_pro(request):
            return "Для вашего аккаунта Pro не разрешён на этом сервере."
        from generation.errors import GenerationError
        from generation.providers.codex import available_models, verify_cli_contract

        if PRO_MODEL not in {item["id"] for item in available_models()}:
            return "В подключённом Codex пока нет GPT-6 Sol."
        try:
            verify_cli_contract()
        except GenerationError as exc:
            return exc.message
    elif profile["provider"] not in {"relay", "vllm"} or not profile["model"]:
        return "Модель API пока не настроена."
    return ""


def profile_options(request):
    # The fixture mode must remain usable without accidentally offering a live API.
    if settings.GAMEFORGE_PROVIDER == "fake":
        return []
    options = []
    for profile in configured_profiles().values():
        reason = unavailable_reason(profile, request)
        options.append({**profile, "available": not reason, "unavailable_reason": reason})
    return options


def default_profile(options):
    preferred = "pro" if settings.GAMEFORGE_PROVIDER == "codex" else "lite"
    return next((p["id"] for p in options if p["id"] == preferred and p["available"]),
                next((p["id"] for p in options if p["available"]), ""))
