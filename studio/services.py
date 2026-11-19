"""Transactional domain operations. Redis is delivery, PostgreSQL owns all state."""

import hashlib
import json
import os
from decimal import ROUND_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from generation.audiences import AUDIENCES

from .continuations import delivery_state, lineage_ids, unacknowledged_unknowns
from .model_profiles import configured_profiles, unavailable_reason
from .models import (
    Budget,
    Chat,
    FeedbackProcessing,
    Invocation,
    Message,
    Outbox,
    Preference,
    Revision,
    Run,
    RunEvent,
    VariantAnalyticsExperiment,
)
from .replies import BUDGET_EXHAUSTED_REPLY, assistant_reply, run_reply
from .titles import DEFAULT_CHAT_TITLE, short_game_title, title_from_prompt


class DomainError(Exception):
    def __init__(self, code, message, status=400, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details
        super().__init__(message)


def validate_chat_title(value: object, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 160:
        raise DomainError("invalid_title", "Укажите название до 160 символов.")
    title = " ".join(value.split())
    if not title and not allow_empty:
        raise DomainError("invalid_title", "Название чата не должно быть пустым.")
    return title or DEFAULT_CHAT_TITLE


@transaction.atomic
def rename_chat(chat: Chat, title: object) -> Chat:
    title = validate_chat_title(title)
    locked = (
        Chat.objects.select_for_update()
        .filter(pk=chat.pk, owner_id=chat.owner_id, deleted_at__isnull=True)
        .first()
    )
    if locked is None:
        raise DomainError("chat_not_found", "Чат не найден.", 404)
    locked.title = title
    locked.title_is_custom = True
    locked.save(update_fields=["title", "title_is_custom", "updated_at"])
    return locked


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def preference_for(user):
    return Preference.objects.get_or_create(user=user)[0]


def budget_snapshot():
    budget, _ = Budget.objects.get_or_create(
        pk=1, defaults={"limit_usd": Decimal(settings.GAMEFORGE_BUDGET_USD)}
    )
    spent = Invocation.objects.filter(cost_usd__isnull=False).aggregate(n=Sum("cost_usd"))["n"] or Decimal(0)
    reserved = Invocation.objects.filter(state__in=["reserved", "sent"], cost_usd__isnull=True).aggregate(
        n=Sum("reservation_usd")
    )["n"] or Decimal(0)
    unknown = Invocation.objects.filter(
        state__in=["unknown", "returned", "settled"], cost_usd__isnull=True
    ).aggregate(n=Sum("reservation_usd"))["n"] or Decimal(0)
    # Background review calls use the same global budget and keep ambiguous liabilities.
    spent += FeedbackProcessing.objects.filter(cost_usd__isnull=False).aggregate(n=Sum("cost_usd"))["n"] or Decimal(0)
    reserved += FeedbackProcessing.objects.filter(
        invocation_state__in=["reserved", "sent"], cost_usd__isnull=True
    ).aggregate(n=Sum("reservation_usd"))["n"] or Decimal(0)
    unknown += FeedbackProcessing.objects.filter(
        invocation_state__in=["unknown", "returned"], cost_usd__isnull=True
    ).aggregate(n=Sum("reservation_usd"))["n"] or Decimal(0)
    return {
        k: float(v)
        for k, v in {
            "limit_usd": budget.limit_usd,
            "spent_usd": spent,
            "reserved_usd": reserved,
            "unknown_usd": unknown,
            "available_usd": max(Decimal(0), budget.limit_usd - spent - reserved - unknown),
        }.items()
    }


def tariff(provider, model):
    if provider == "fake":
        return {"input": 0, "cached": 0, "output": 0, "label": "fixture"}
    # Standard API-equivalent rates verified 2026-10-18:
    # https://developers.openai.com/api/docs/pricing (USD per million tokens).
    prices = {
        "gpt-6-luna": {"input": 0.10, "cached": 0.01, "cache_write": 0.125, "output": 0.50},
        # https://developers.openai.com/api/docs/models/gpt-6-sol (2026-10-24).
        "gpt-6-sol": {"input": 2, "cached": 0.20, "cache_write": 2.5, "output": 10},
        "gpt-6.1-sol": {"input": 2, "cached": 0.10, "cache_write": 2.5, "output": 10},
        # Standard with 30-minute cache writes (2026-11-19). Both model pages
        # specify max input 922k, output 128k, and the same long-context uplift.
        "gpt-6.2-sol": {"input": 2, "cached": 0.10, "cache_write": 2.5, "output": 10},
        "gpt-6.2-astra": {"input": 8, "cached": 0.40, "cache_write": 10, "output": 40},
    }
    if provider not in {"codex", "codex_api"}:
        prices = {}
    for price in prices.values():
        price.update(long_context_threshold=272000, long_input_multiplier=2, long_output_multiplier=1.5)
    prices.update(json.loads(os.environ.get("GAMEFORGE_PRICES_JSON", "{}")))
    return prices.get(model, {})


def usage_cost(usage, price):
    if usage is None or not all(
        k in usage and usage[k] is not None for k in ("input_tokens", "cached_input_tokens", "output_tokens")
    ):
        return None
    if not all(k in price for k in ("input", "cached", "output")):
        return None
    incoming, cached, outgoing = (
        int(usage[k]) for k in ("input_tokens", "cached_input_tokens", "output_tokens")
    )
    if min(incoming, cached, outgoing) < 0 or cached > incoming:
        return None
    written = int(usage.get("cache_write_input_tokens") or 0)
    if written < 0 or cached + written > incoming:
        return None
    threshold = price.get("long_context_threshold")
    long_context = isinstance(threshold, int) and incoming > threshold
    input_multiplier = Decimal(str(price.get("long_input_multiplier", 1))) if long_context else Decimal(1)
    output_multiplier = Decimal(str(price.get("long_output_multiplier", 1))) if long_context else Decimal(1)
    cost = (
        (
            Decimal(incoming - cached - written) * Decimal(str(price["input"]))
            + Decimal(cached) * Decimal(str(price["cached"]))
            + Decimal(written) * Decimal(str(price.get("cache_write", price["input"])))
        )
        * input_multiplier
        + Decimal(outgoing) * Decimal(str(price["output"])) * output_multiplier
    ) / 1000000
    return cost.quantize(Decimal(".000001"), rounding=ROUND_UP)


@transaction.atomic
def reserve_invocation(run, request):
    if not run.allow_model_calls:
        raise DomainError("model_calls_disabled", "Этот запуск только проверяет сохранённый ответ.", 409)
    request = {**request, "provider": run.provider, "model": run.model_for(request.get("operation"))}
    if request.get("operation") == "plan" and run.variant_batch_id and run.model_profile == "pro":
        hint = VariantAnalyticsExperiment.objects.filter(
            batch_id=run.variant_batch_id, hint_variant_index=run.variant_index,
        ).values_list("hint", flat=True).first()
        if hint:
            request["design"] = {**(request.get("design") or {}), "optional_analytics_hint": {
                "suggestion": hint["text"],
                "guidance": "Use only if compatible with the game request and saved preferences. "
                            "If adopted, treat it as an optional design assumption with origin=design, "
                            "never as a user requirement.",
            }}
    import uuid

    invocation_id = uuid.uuid4()
    from generation.service import DURABLE_PROVIDERS, PROVIDERS

    if run.provider in DURABLE_PROVIDERS:
        from generation.errors import GenerationError

        try:
            request[run.provider] = PROVIDERS[run.provider].prepare(request, str(invocation_id))
        except GenerationError as exc:
            raise DomainError(exc.code, exc.message, 409) from exc
    Budget.objects.get_or_create(pk=1, defaults={"limit_usd": Decimal(settings.GAMEFORGE_BUDGET_USD)})
    Budget.objects.select_for_update().get(pk=1)
    current = Run.objects.get(pk=run.pk)
    if request.get('pro_parallel_branch'):
        current = Run.objects.select_for_update().get(pk=run.pk)
        if current.fence != run.fence or current.cancel_requested or current.status not in Run.ACTIVE:
            raise DomainError('cancelled', 'Задание остановлено до отправки.', 409)
    if not current.allow_model_calls:
        raise DomainError("model_calls_disabled", "Этот запуск только проверяет сохранённый ответ.", 409)
    unknown_calls, inflight_calls = delivery_state(current)
    if unknown_calls:
        raise DomainError("outcome_unknown", "Итоговый расход неизвестен. Подтвердите новый запрос отдельно.", 409)
    if inflight_calls:
        raise DomainError("outcome_pending", "Предыдущий запрос ещё не завершён. Дождитесь сверки его результата.", 409)
    if current.model_call_deadline and timezone.now() >= current.model_call_deadline:
        raise DomainError("model_deadline", "Время новых модельных вызовов истекло. Кандидат сохранён.", 409)
    if current.invocations.count() >= current.max_model_calls:
        raise DomainError("repair_exhausted", "Лимит исправлений этого запуска исчерпан. Черновик сохранён.", 409)
    price = tariff(run.provider, request["model"])
    if run.provider != "fake" and not price:
        raise DomainError(
            "pricing_unavailable",
            "Для выбранной модели не заданы проверенные цены; платный запрос не отправлен.",
            409,
        )
    from generation.service import estimate_reservation

    # There is exactly one current admission contract; unknown bounds fail closed.
    amount = Decimal(str(estimate_reservation(request, price)))
    if Decimal(str(budget_snapshot()["available_usd"])) < amount:
        raise DomainError("budget_exhausted", BUDGET_EXHAUSTED_REPLY, 409)
    from .capacity import capacity_full

    if capacity_full(current, include_current_calls=bool(request.get('pro_parallel_branch'))):
        raise DomainError("provider_busy", "Ожидаем свободное место для следующего шага генерации.", 409)
    return Invocation.objects.create(
        id=invocation_id, run=run, attempt=run.attempts + 1, request=request, reservation_usd=amount, price=price
    )


@transaction.atomic
def settle_invocation(
    invocation_id,
    *,
    response=None,
    raw_response=None,
    usage=None,
    error=None,
    unknown=False,
    elapsed=0,
    provider_id="",
    provider_metadata=None,
    unsent_fence=None,
):
    Budget.objects.select_for_update().get(pk=1)
    run_id = Invocation.objects.only("run_id").get(pk=invocation_id).run_id
    run = Run.objects.select_for_update().get(pk=run_id)
    inv = Invocation.objects.select_for_update().get(pk=invocation_id)
    if unsent_fence is not None and (
        run.fence != unsent_fence or inv.sent_at is not None or inv.state != "reserved"
    ):
        # A stale worker cannot cancel its successor's reservation or sent call.
        return inv
    was_unknown = inv.state == "unknown"
    if inv.finished_at and inv.state not in ("unknown",):
        return inv
    inv.response = response
    inv.raw_response = raw_response if raw_response is not None else (error or {}).get("raw_response")
    inv.usage = usage
    inv.error = error
    inv.elapsed_seconds = elapsed
    inv.provider_invocation_id = provider_id or ""
    inv.provider_metadata = provider_metadata or {}
    # Interim usage is not a final bill: an interrupted request can still consume more.
    # Keep the entire admission ceiling as one unknown liability until a final receipt.
    inv.cost_usd = None if unknown else usage_cost(usage, inv.price)
    inv.state = "unknown" if unknown else ("returned" if response is not None else "failed")
    if inv.cost_usd is None and not unknown and response is None and not inv.sent_at:
        inv.cost_usd = Decimal(0)
    elif inv.cost_usd is None and not unknown and error:
        if error.get("raw_response") is not None:
            # We have a reply but not its usage. Preserve a liability, not an invented zero.
            inv.state = "unknown"
        else:
            # Typed provider error explicitly says no ambiguous remote outcome.
            inv.cost_usd = Decimal(0)
    inv.finished_at = timezone.now()
    inv.save()
    if was_unknown and inv.state != "unknown" and run.status == "unknown":
        # A late receipt resolves the ambiguity but never selects game bytes automatically.
        run.status = "needs_attention"
        run.stage = "needs_attention"
        run.message = "Сохранённый ответ модели получен. Можно продолжить без повторной генерации."
        run.error = {"code": "late_response_received", "message": run.message}
        run.save(update_fields=["status", "stage", "message", "error", "updated_at"])
        event(run, "late_response_received", run.message)
    return inv


def event(run, kind, message, details=None):
    return RunEvent.objects.create(run=run, kind=kind, message=message, details=details or {})


def schedule(run):
    from .tasks import dispatch_run

    Outbox.objects.get_or_create(run=run)
    # HTTP handlers only persist and enqueue work. A disconnected browser must
    # never own the model transport, even in a local development configuration.
    # The outbox/beat also delivers work if this callback never runs.
    transaction.on_commit(lambda: dispatch_run(run.id))


def blocking_runs(chat, variant_batch_id=None, variant_index=None):
    active = chat.runs.filter(status__in=Run.ACTIVE)
    if variant_batch_id:
        active = active.filter(~Q(variant_batch_id=variant_batch_id) | Q(variant_index=variant_index))
    return active


def latest_variant_attempt(run):
    return (Run.objects.filter(variant_batch_id=run.variant_batch_id, variant_index=run.variant_index)
            .order_by("-created_at", "-id").values_list("id", flat=True).first() == run.pk)


def budget_blocked_before_multiagent_plan(run):
    return (
        run.pro_parallel and run.operation == "create" and run.planning_required and not run.game_plan
        and run.status == "needs_attention" and (run.error or {}).get("code") == "budget_exhausted"
        and not (run.base_revision_id or run.source_revision_id or run.candidate_revision_id)
        and not Invocation.objects.filter(run_id__in=lineage_ids(run)).exists()
    )


@transaction.atomic
def create_run(chat, data, *, continued_from=None, authorize=None, check_only=False, variant_batch=None):
    if data.get("analytics_experiment", False) is not False and (not variant_batch or continued_from):
        raise DomainError("invalid_analytics_experiment", "Эксперимент доступен при создании новой игры в Pro 4×.")
    chat = Chat.objects.select_for_update().get(pk=chat.pk, deleted_at__isnull=True)
    variant_index = 1 if variant_batch else None
    if continued_from and continued_from.variant_batch_id:
        variant_batch = continued_from.variant_batch
        variant_index = continued_from.variant_index
    if variant_batch and variant_batch.chat_id != chat.pk:
        raise DomainError("invalid_variant", "Серия вариантов недоступна в этом чате.", 409)
    key = data.get("idempotency_key")
    if not isinstance(key, str) or not key.strip() or len(key) > 100:
        raise DomainError("idempotency_required", "Укажите ключ запроса для защиты от повторной отправки.")
    prompt = data.get("prompt") or (continued_from.prompt if continued_from else "")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise DomainError("invalid_prompt", "Опишите игру или небольшую правку (до 12 000 символов).")
    audience = data.get("audience", chat.audience)
    if not isinstance(audience, str) or audience not in AUDIENCES:
        raise DomainError("invalid_audience", "Неизвестная аудитория.")
    previous = Run.objects.filter(chat=chat, idempotency_key=key).first()
    if previous and (previous.variant_batch_id != (variant_batch.pk if variant_batch else None)
                     or previous.variant_index != variant_index):
        raise DomainError("idempotency_conflict", "Этот ключ уже использован для другого запроса.", 409)
    acknowledged_run = None
    if data.get("acknowledge_unknown_run_id"):
        if continued_from or check_only:
            raise DomainError("invalid_retry", "Подтверждение относится к новому запросу.")
        try:
            acknowledged_run = Run.objects.get(pk=data["acknowledge_unknown_run_id"], chat=chat)
        except (Run.DoesNotExist, ValueError, DjangoValidationError) as exc:
            raise DomainError("invalid_retry", "Предыдущий запрос недоступен.", 409) from exc
    # Retries inherit the original choice even if the user's preference or server
    # configuration changed after a lost HTTP response. Continuations inherit it
    # unless the user explicitly selects another profile.
    inherited = previous or continued_from
    default_choice = inherited.model_profile if inherited else (
        "" if settings.GAMEFORGE_PROVIDER == "fake" else (preference_for(chat.owner).model_profile or "pro")
    )
    profile_id = data.get("model_profile", default_choice)
    if not isinstance(profile_id, str) or profile_id not in {"", "pro", "lite", "pro_multi"}:
        raise DomainError("invalid_model_profile", "Выберите модель из списка доступных.")
    if variant_batch and profile_id != "pro":
        raise DomainError("invalid_model_profile", "Четыре варианта доступны для обычной Pro.")
    if inherited and profile_id == inherited.model_profile:
        provider, model = inherited.provider, inherited.model
    elif profile_id:
        profile = configured_profiles()[profile_id]
        reason = unavailable_reason(profile)
        if reason:
            raise DomainError("model_unavailable", reason, 409)
        provider, model = profile["provider"], profile["model"]
    else:
        provider, model = settings.GAMEFORGE_PROVIDER, settings.GAMEFORGE_MODEL
    if data.get("model"):
        if profile_id and data["model"] != model:
            raise DomainError("invalid_model", "Модель определяется выбранным режимом генерации.")
        model = data["model"]
    if not isinstance(model, str) or len(model) > 100:
        raise DomainError("invalid_model", "Некорректная модель.")
    if authorize:
        authorize(provider)
    selected_source = None
    if data.get("source_revision_id"):
        try:
            selected_source = Revision.objects.filter(pk=data["source_revision_id"], chat=chat).first()
        except (ValueError, DjangoValidationError) as exc:
            raise DomainError("source_changed", "Выбранная версия недоступна.", 409) from exc
    default_generation = inherited.generation_profile if inherited else (
        selected_source.generation_profile if selected_source else
        "compact" if settings.GAMEFORGE_COMPACT_LITE_ENABLED and profile_id == "lite" else "full"
    )
    generation_profile = data.get("generation_profile", default_generation)
    source_format = data.get("source_format", inherited.source_format if inherited else "string")
    if generation_profile not in {"full", "compact"} or source_format not in {"string", "lines"} or (
        generation_profile == "full" and source_format != "string"
    ):
        raise DomainError("invalid_generation_profile", "Неизвестный профиль генерации.")
    if selected_source and selected_source.generation_profile != generation_profile:
        raise DomainError("profile_mismatch", "Профиль должен соответствовать выбранной игре.", 409)
    if continued_from and generation_profile != continued_from.generation_profile:
        raise DomainError('profile_mismatch', 'Продолжение сохраняет формат исходной игры.', 409)
    pro_parallel = profile_id == 'pro_multi'
    planner_model = None
    if pro_parallel:
        planner_model = (inherited.planner_model if inherited and inherited.pro_parallel
                         else settings.GAMEFORGE_PRO_PARALLEL_PLANNER_MODEL or None)
    from generation.pro_parallel import VERSION as PRO_PARALLEL_VERSION

    pro_parallel_version = (continued_from.pro_parallel_version if continued_from and continued_from.pro_parallel
                            else PRO_PARALLEL_VERSION if pro_parallel else 1)
    if pro_parallel and (provider != 'codex_api' or generation_profile != 'full'):
        raise DomainError('invalid_generation_profile', 'Режим Multiagent использует полный формат и Pro API.')
    if continued_from and continued_from.pro_parallel != pro_parallel and not (
        continued_from.candidate_revision_id or continued_from.source_revision_id
    ):
        raise DomainError('profile_mismatch', 'Сначала завершите сохранённые этапы в исходном режиме.', 409)
    payload = {
        "prompt": prompt.strip(),
        "audience": audience,
        "model": model,
        "continued_from": str(continued_from.id) if continued_from else None,
        "generation_profile": generation_profile,
        "source_format": source_format,
    }
    if not continued_from:
        payload.update({key: data.get(key) for key in (
            "source_revision_id", "source_artifact_hash", "source_is_historical",
        )})
    call_limit = data.get("model_call_limit")
    deadline_text = data.get("model_call_deadline")
    maximum_calls = (11 if pro_parallel_version in {4, 5} else 10 if pro_parallel_version >= 2 else 9) if pro_parallel else 5
    if call_limit is not None and (type(call_limit) is not int or not 1 <= call_limit <= maximum_calls):
        raise DomainError("invalid_call_budget", f"Лимит вызовов должен быть целым числом от 1 до {maximum_calls}.")
    try:
        deadline = parse_datetime(deadline_text) if isinstance(deadline_text, str) else None
    except ValueError:
        deadline = None
    if deadline_text is not None and (deadline is None or timezone.is_naive(deadline)):
        raise DomainError("invalid_call_budget", "Укажите ISO-время окончания с часовым поясом.")
    if call_limit is not None:
        payload["model_call_limit"] = call_limit
    if deadline is not None:
        payload["model_call_deadline"] = deadline.isoformat()
    if check_only:
        payload["check_only"] = True
    accept_unknown_cost = data.get("accept_unknown_cost") is True
    if accept_unknown_cost:
        payload["accept_unknown_cost"] = True
    if acknowledged_run:
        payload["acknowledge_unknown_run_id"] = str(acknowledged_run.id)
    legacy_fingerprint = fingerprint(payload)
    payload.update(provider=provider, model_profile=profile_id)
    if previous:
        legacy_match = (
            not previous.model_profile and not profile_id and previous.provider == provider
            and previous.request_fingerprint == legacy_fingerprint
        )
        if previous.request_fingerprint != fingerprint(payload) and not legacy_match:
            raise DomainError("idempotency_conflict", "Этот ключ уже использован для другого запроса.", 409)
        return previous
    from generation.schema import CONTRACT_VERSION

    if continued_from and continued_from.pipeline_version != CONTRACT_VERSION or (
        selected_source and selected_source.pipeline_version != CONTRACT_VERSION
    ):
        raise DomainError('unsupported_game', 'Старый игровой формат больше не поддерживается. Создайте новую игру.', 409)
    sibling_batch_id = continued_from.variant_batch_id if continued_from else None
    if blocking_runs(chat, sibling_batch_id, variant_index).exists():
        raise DomainError("chat_busy", "В этом чате уже выполняется задание.", 409)
    if sibling_batch_id and not latest_variant_attempt(continued_from):
        raise DomainError("cannot_continue", "Для этого варианта уже сохранена новая попытка.", 409)
    if continued_from and continued_from.status not in (
        "needs_attention",
        "unverified",
        "failed",
        "cancelled",
        "unknown",
    ):
        raise DomainError("cannot_continue", "Задание не ожидает продолжения.", 409)
    consent_run = acknowledged_run or continued_from
    unknown_calls = unacknowledged_unknowns(consent_run) if consent_run else []
    unknown = bool(unknown_calls)
    if acknowledged_run and (acknowledged_run.status in Run.ACTIVE or not unknown):
        raise DomainError("cannot_retry", "Состояние предыдущего запроса изменилось. Обновите чат.", 409)
    if unknown and not accept_unknown_cost and not check_only:
        raise DomainError(
            "outcome_unknown",
            "Итоговый расход неизвестен. Для нового запроса отдельно подтвердите расход; прежняя сумма останется в учёте.",
            409,
        )
    if continued_from and (unknown or continued_from.status == "unknown") and not check_only:
        if not unknown or not accept_unknown_cost:
            raise DomainError("cannot_continue", "Сначала нужно уточнить состояние запроса.", 409)
        if not variant_batch and chat.current_revision_id != continued_from.base_revision_id:
            raise DomainError(
                "retry_base_changed",
                "После этого запроса рабочая версия изменилась. Отправьте новое описание к текущей игре.",
                409,
            )
    base = continued_from.base_revision if variant_batch and continued_from else chat.current_revision
    candidate = continued_from.candidate_revision if continued_from else None
    source = continued_from.source_revision if continued_from else None
    if check_only and not candidate and continued_from and (continued_from.error or {}).get("code") == "test_only_change":
        candidate = source or continued_from.base_revision
    if not continued_from:
        source_id = data.get("source_revision_id")
        if source_id:
            try:
                source = Revision.objects.select_related("run").get(pk=source_id, chat=chat)
            except (Revision.DoesNotExist, ValueError, DjangoValidationError) as exc:
                raise DomainError("source_changed", "Выбранная версия недоступна. Откройте игру заново.", 409) from exc
            latest = chat.revisions.order_by("-number").values_list("id", flat=True).first()
            if data.get("source_artifact_hash") != source.artifact_hash or (
                source.id not in {latest, chat.current_revision_id} and data.get("source_is_historical") is not True
            ):
                raise DomainError("source_changed", "Выбранная версия изменилась. Откройте игру заново.", 409)
        elif chat.revisions.exists():
            raise DomainError("source_required", "Выберите версию игры для доработки.", 409)
    if check_only and (
        not candidate or not continued_from or (not variant_batch and chat.current_revision_id != continued_from.base_revision_id)
    ):
        raise DomainError("cannot_recheck", "Нет актуального кандидата для повторной проверки.", 409)
    operation = "repair" if candidate or continued_from else ("edit" if source else "create")
    if continued_from and pro_parallel and not check_only and budget_blocked_before_multiagent_plan(continued_from):
        if base or continued_from.continuations.exists():
            raise DomainError("cannot_continue", "В чате уже есть версия игры или продолжение этого задания.", 409)
        # No model call was admitted. Resume the original creation with its full set of stages
        # and keep any caller-imposed limits, even if the client only supplies an idempotency key.
        operation = "create"
        if continued_from.model_call_limit is not None:
            if call_limit is not None and call_limit > continued_from.model_call_limit:
                raise DomainError("invalid_call_budget", "Продолжение сохраняет исходный предел вызовов.")
            call_limit = call_limit or continued_from.model_call_limit
        if continued_from.model_call_deadline:
            if deadline and deadline > continued_from.model_call_deadline:
                raise DomainError("invalid_call_budget", "Продолжение сохраняет исходный срок вызовов.")
            deadline = deadline or continued_from.model_call_deadline
    from generation.planning import should_plan, strategy
    from generation.requirements import manifest, policy_snapshot

    generation_strategy = strategy(provider, model)
    lite_experiment = generation_strategy == "lite" and profile_id != "pro" and provider not in {"codex", "codex_api"}
    if continued_from and lite_experiment and continued_from.generation_strategy == "lite_code_then_checks":
        generation_strategy = continued_from.generation_strategy
    elif (lite_experiment and generation_profile == "compact"
          and settings.GAMEFORGE_LITE_CODE_THEN_CHECKS_ENABLED):
        generation_strategy = "lite_code_then_checks"
    game_plan = continued_from.game_plan if continued_from else (
        source.run.game_plan if source and source.run else {}
    )
    planning_required = not check_only and not game_plan and (
        continued_from.planning_required if continued_from else should_plan(
            profile_id, operation, prompt, provider=provider, model=model,
        )
    )
    from generation.lite import eligible as lite_direct

    # Restore pre-cb807c7 direct creation for new full Lite games only.
    # Continuations retain their saved plan policy and already paid receipts.
    if not continued_from and lite_direct({
        'provider': provider, 'generation_strategy': generation_strategy,
        'generation_profile': generation_profile,
    }):
        planning_required = False
    if not chat.title_is_custom and chat.current_revision_id is None and not chat.runs.exists():
        chat.title = title_from_prompt(prompt)
    if continued_from:
        original_request = continued_from.game_request
        frozen_manifest = continued_from.requirement_manifest
    elif source:
        original_request = source.requirement_manifest.get("request") or (
            (source.run.game_request or source.run.prompt) if source.run else prompt.strip()
        )
        frozen_manifest = manifest(original_request, previous=source.requirement_manifest, amendment=prompt.strip())
    else:
        original_request = prompt.strip()
        frozen_manifest = manifest(original_request)
        if pro_parallel:
            frozen_manifest["touch_control_guidance"] = {
                "version": 1,
                "plan": "For every required touch control, put a reachable player action and its observable gameplay "
                        "effect in the frozen requirement example. Record the actual controls in player_experience.input "
                        "and in the scene/mechanics interface when split. The mobile checker can tap a visible control, "
                        "tap_fraction on its displayed box, or hold_touch at one stationary point for up to 3000 ms.",
                "gestures": "For wheels, joysticks or sliders, provide a real tap or stationary-hold way to control the "
                            "same mechanic, such as pressing the left or right half of the helm to turn. Keep explicitly "
                            "requested drag gestures playable. A tap can demonstrate steering but cannot prove dragging. "
                            "If the user requires gesture-only input, preserve it and state the manual verification "
                            "limit in assumptions. Desktop key input cannot prove a mobile control.",
                "effects": "Give independent mechanics their own playable actions and observable consequences. Verify "
                           "a change of heading, collected item or spent resource through its actual state or HUD. "
                           "A highlighted control or unrelated animation alone cannot demonstrate these effects.",
            }
    from generation.helpers import catalog
    from generation.scene import PATH as scene_path

    from .preferences import validate_notes

    if continued_from:
        helper_catalog = continued_from.helper_catalog
    else:
        helper_catalog = catalog(include_scene=pro_parallel)
        if source and scene_path in source.helper_manifest:
            # An edit/remix retains the actual scene pin even after switching models.
            helper_catalog[scene_path] = source.helper_manifest[scene_path]
    if not continued_from and lite_direct({
        'provider': provider, 'generation_strategy': generation_strategy,
        'generation_profile': generation_profile,
    }):
        from generation.experience import PATH as media_path
        from generation.experience import RECIPE

        # New simple Lite games do not need a media recipe. Edits of existing
        # media games retain the pinned helper and their original assets.
        if not source or RECIPE not in source.files:
            helper_catalog = {path: value for path, value in helper_catalog.items() if path != media_path}
            frozen_manifest['require_keyboard'] = True
            if operation == 'create':
                from generation.music import MARKER

                frozen_manifest[MARKER] = 1
                # Pin the player now; only the later music request receives it.
                helper_catalog[media_path] = catalog()[media_path]
    run = Run.objects.create(
        helper_catalog=helper_catalog,
        chat=chat,
        variant_batch=variant_batch,
        variant_index=variant_index,
        operation=operation,
        prompt=prompt.strip(),
        audience=audience,
        model=model,
        planner_model=planner_model,
        provider=provider,
        model_profile=profile_id,
        idempotency_key=key,
        request_fingerprint=fingerprint(payload),
        base_revision=base,
        source_revision=source,
        generation_profile=generation_profile,
        source_format=source_format,
        generation_strategy=generation_strategy,
        pro_parallel=pro_parallel,
        pro_parallel_version=pro_parallel_version,
        planning_required=planning_required,
        visual_review_enabled=(continued_from.visual_review_enabled if continued_from else
                               not pro_parallel and settings.GAMEFORGE_PRO_VISUAL_REVIEW_ENABLED and generation_strategy=="pro" and operation=="create"),
        visual_state=continued_from.visual_state if continued_from else {},
        game_plan=game_plan,
        game_request=original_request,
        requirement_manifest=frozen_manifest,
        preferences_snapshot=continued_from.preferences_snapshot if continued_from else validate_notes(preference_for(chat.owner).notes),
        policy_snapshot=continued_from.policy_snapshot if continued_from else policy_snapshot(),
        candidate_revision=candidate,
        continued_from=continued_from,
        max_repair_attempts=5 if pro_parallel else settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS,
        allow_model_calls=not check_only,
        model_call_limit=call_limit,
        model_call_deadline=deadline,
    )
    chat.audience = audience
    if continued_from:
        from .response_completion import adopt_completion_policy

        adopt_completion_policy(run)
    chat.save(update_fields=["audience", "title", "updated_at"])
    Message.objects.create(chat=chat, run=run, role="user", content=prompt.strip())
    event(run, "queued", "Запрос принят. Ожидаем свободное место для генерации.")
    if unknown and not check_only:
        event(run, "explicit_retry", "Новый запрос подтверждён пользователем; прежний неизвестный расход сохранён.",
              {"previous_run_id": str(consent_run.id),
               "unknown_invocation_ids": sorted(str(call.id) for call in unknown_calls)})
    schedule(run)
    return run


@transaction.atomic
def cancel_run(run):
    run = Run.objects.select_for_update().get(pk=run.pk)
    if run.status in Run.ACTIVE:
        run.cancel_requested = True
        run.status = "cancelled"
        run.stage = "cancelled"
        run.message = "Задание отменено. Последняя рабочая версия и черновик сохранены."
        run.finished_at = timezone.now()
        run.save()
        Message.objects.create(chat=run.chat, run=run, role="assistant",
                               content=assistant_reply("cancelled", run.message))
        event(run, "cancelled", run.message)
    return run


def choose_working_revision(chat, revision):
    """Called with the chat locked, after validating the revision and its owner."""
    chat.current_revision = revision
    if not chat.title_is_custom:
        chat.title = short_game_title(revision.title)
    chat.save(update_fields=["current_revision", "title", "updated_at"])


@transaction.atomic
def finish_run(run_id, fence, status, message, *, error=None, revision=None):
    chat_id = Run.objects.only("chat_id").get(pk=run_id).chat_id
    chat = Chat.objects.select_for_update().get(pk=chat_id)
    run = Run.objects.select_for_update(of=("self",)).select_related("chat").get(pk=run_id)
    if run.fence != fence or run.cancel_requested or run.chat.deleted_at:
        return False
    if run.invocations.filter(state__in=["reserved", "sent"]).exists() or (
        status != "failed" and run.invocations.filter(state="returned", revision__isnull=True).exists()
    ):
        raise DomainError("invocation_pending", "Сначала нужно обработать сохранённый вызов.", 409)
    run.status = status
    run.stage = status
    run.message = message
    run.error = error
    run.finished_at = timezone.now()
    model_seconds = run.invocations.aggregate(total=Sum("elapsed_seconds"))["total"] or 0
    check_seconds = run.check_reports.aggregate(total=Sum("elapsed_seconds"))["total"] or 0
    run.metrics = {
        **run.metrics,
        "model_seconds": model_seconds,
        "check_seconds": check_seconds,
        "total_seconds": (run.finished_at - run.created_at).total_seconds(),
        "model_calls": run.invocations.filter(sent_at__isnull=False).count(),
    }
    run.lease_until = None
    if revision:
        if revision.checks_review_required:
            raise DomainError("check_review_required", "Изменённые сценарии требуют явного подтверждения результата.")
        run.result_revision = revision
        revision.accepted = True
        revision.verification = "automatic"
        revision.save(update_fields=["accepted", "verification"])
        if not run.variant_batch_id:
            if chat.current_revision_id != run.base_revision_id:
                raise DomainError(
                    "base_changed", "Рабочая версия уже изменилась. Результат сохранён как черновик.", 409
                )
            choose_working_revision(chat, revision)
    run.save()
    responses = run.invocations.filter(state="settled", error__isnull=True, response__isnull=False)
    if run.pro_parallel:
        responses = responses.exclude(request__operation__in=['pro_graphics', 'pro_audio', 'pro_mechanics', 'pro_checks'])
    if (error or {}).get("code") != "scope_refusal":
        responses = responses.exclude(request__has_key="operation", request__operation__in=["plan", "visual_review"])
    if revision:
        responses = responses.filter(revision=revision).exclude(
            request__has_key="operation", request__operation__in=["check_repair", "checks_create"]
        )
    response = responses.order_by("-attempt").values_list("response", flat=True).first()
    model_message = response.get("message", "") if isinstance(response, dict) else ""
    reply = run_reply(
        run, model_message,
        response_status=response.get("status", "") if isinstance(response, dict) else "",
    )
    Message.objects.create(chat=run.chat, run=run, role="assistant", content=reply)
    event(run, status, message, {"error": error} if error else {})
    return True
