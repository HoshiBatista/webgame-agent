"""Transactional domain operations. Redis is delivery, PostgreSQL owns all state."""

import hashlib
import json
import os
from decimal import ROUND_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Budget, Chat, Invocation, Message, Outbox, Preference, Run, RunEvent


class DomainError(Exception):
    def __init__(self, code, message, status=400, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details
        super().__init__(message)


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
        "gpt-6.1-sol": {"input": 2, "cached": 0.10, "cache_write": 2.5, "output": 10},
    }
    if provider != "codex":
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
    request = {**request, "provider": run.provider, "model": run.model}
    import uuid

    invocation_id = uuid.uuid4()
    if run.provider == "relay":
        from generation.errors import GenerationError
        from generation.providers.relay import prepare

        try:
            request["relay"] = prepare(request, str(invocation_id))
        except GenerationError as exc:
            raise DomainError(exc.code, exc.message, 409) from exc
    Budget.objects.get_or_create(pk=1, defaults={"limit_usd": Decimal(settings.GAMEFORGE_BUDGET_USD)})
    Budget.objects.select_for_update().get(pk=1)
    current = Run.objects.get(pk=run.pk)
    if not current.allow_model_calls:
        raise DomainError("model_calls_disabled", "Этот запуск только проверяет сохранённый ответ.", 409)
    if current.invocations.count() >= current.max_model_calls:
        raise DomainError("repair_exhausted", "Лимит исправлений этого запуска исчерпан. Черновик сохранён.", 409)
    price = tariff(run.provider, run.model)
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
        raise DomainError(
            "budget_exhausted",
            "Доступного бюджета недостаточно для следующего запроса. Черновик сохранён.",
            409,
        )
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
):
    Budget.objects.select_for_update().get(pk=1)
    run_id = Invocation.objects.only("run_id").get(pk=invocation_id).run_id
    run = Run.objects.select_for_update().get(pk=run_id)
    inv = Invocation.objects.select_for_update().get(pk=invocation_id)
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


@transaction.atomic
def create_run(chat, data, *, continued_from=None):
    chat = Chat.objects.select_for_update().get(pk=chat.pk, deleted_at__isnull=True)
    key = data.get("idempotency_key")
    if not isinstance(key, str) or not key.strip() or len(key) > 100:
        raise DomainError("idempotency_required", "Укажите ключ запроса для защиты от повторной отправки.")
    prompt = data.get("prompt") or (continued_from.prompt if continued_from else "")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise DomainError("invalid_prompt", "Опишите игру или небольшую правку (до 12 000 символов).")
    audience = data.get("audience", chat.audience)
    if audience not in ("everyone", "gamers", "children", "seniors"):
        raise DomainError("invalid_audience", "Неизвестная аудитория.")
    model = data.get("model") or (continued_from.model if continued_from else settings.GAMEFORGE_MODEL)
    if not isinstance(model, str) or len(model) > 100:
        raise DomainError("invalid_model", "Некорректная модель.")
    payload = {
        "prompt": prompt.strip(),
        "audience": audience,
        "model": model,
        "continued_from": str(continued_from.id) if continued_from else None,
    }
    accept_unknown_cost = data.get("accept_unknown_cost") is True
    if accept_unknown_cost:
        payload["accept_unknown_cost"] = True
    previous = Run.objects.filter(chat=chat, idempotency_key=key).first()
    if previous:
        if previous.request_fingerprint != fingerprint(payload):
            raise DomainError("idempotency_conflict", "Этот ключ уже использован для другого запроса.", 409)
        return previous
    if chat.runs.filter(status__in=Run.ACTIVE).exists():
        raise DomainError("chat_busy", "В этом чате уже выполняется задание.", 409)
    if continued_from and continued_from.status not in (
        "needs_attention",
        "unverified",
        "failed",
        "cancelled",
        "unknown",
    ):
        raise DomainError("cannot_continue", "Задание не ожидает продолжения.", 409)
    unknown = bool(continued_from and continued_from.invocations.filter(state="unknown").exists())
    if unknown and not accept_unknown_cost:
        raise DomainError(
            "outcome_unknown",
            "Итоговый расход неизвестен. Для нового запроса отдельно подтвердите расход; прежняя сумма останется в учёте.",
            409,
        )
    if continued_from and (unknown or continued_from.status == "unknown"):
        if not unknown or not accept_unknown_cost:
            raise DomainError("cannot_continue", "Сначала нужно уточнить состояние запроса.", 409)
        if chat.current_revision_id != continued_from.base_revision_id:
            raise DomainError(
                "retry_base_changed",
                "После этого запроса рабочая версия изменилась. Отправьте новое описание к текущей игре.",
                409,
            )
    base = chat.current_revision
    candidate = continued_from.candidate_revision if continued_from else None
    operation = "repair" if candidate or continued_from else ("edit" if base else "create")
    run = Run.objects.create(
        chat=chat,
        operation=operation,
        prompt=prompt.strip(),
        audience=audience,
        model=model,
        provider=continued_from.provider if continued_from else settings.GAMEFORGE_PROVIDER,
        idempotency_key=key,
        request_fingerprint=fingerprint(payload),
        base_revision=base,
        candidate_revision=candidate,
        continued_from=continued_from,
        max_repair_attempts=settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS,
    )
    chat.audience = audience
    chat.save(update_fields=["audience", "updated_at"])
    Message.objects.create(chat=chat, run=run, role="user", content=prompt.strip())
    event(run, "queued", "Запрос принят. Ожидаем свободное место для генерации.")
    if unknown:
        event(run, "explicit_retry", "Новый запрос подтверждён пользователем; прежний неизвестный расход сохранён.",
              {"previous_run_id": str(continued_from.id)})
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
        event(run, "cancelled", run.message)
    return run


@transaction.atomic
def finish_run(run_id, fence, status, message, *, error=None, revision=None):
    chat_id = Run.objects.only("chat_id").get(pk=run_id).chat_id
    Chat.objects.select_for_update().get(pk=chat_id)
    run = Run.objects.select_for_update(of=("self",)).select_related("chat").get(pk=run_id)
    if run.fence != fence or run.cancel_requested or run.chat.deleted_at:
        return False
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
        run.result_revision = revision
        revision.accepted = True
        revision.verification = "automatic"
        revision.save(update_fields=["accepted", "verification"])
        chat = Chat.objects.select_for_update().get(pk=run.chat_id)
        # A late result can never overwrite another accepted base.
        if chat.current_revision_id != run.base_revision_id:
            raise DomainError(
                "base_changed", "Рабочая версия уже изменилась. Результат сохранён как черновик.", 409
            )
        chat.current_revision = revision
        if not chat.title:
            chat.title = revision.title
        chat.save(update_fields=["current_revision", "title", "updated_at"])
    run.save()
    Message.objects.create(chat=run.chat, run=run, role="assistant", content=message)
    event(run, status, message, {"error": error} if error else {})
    return True
