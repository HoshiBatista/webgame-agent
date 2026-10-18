"""A single model operation. Retries and saved-candidate policy belong to the queue."""

import time
import uuid

from .errors import GenerationError
from .providers import codex, fake, vllm
from .schema import validate_response

PROVIDERS = {"codex": codex, "vllm": vllm, "fake": fake}


def generate(request, *, on_event, is_cancelled):
    provider_name = request.get("provider", "codex")
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise GenerationError("unknown_provider", "Неизвестный провайдер генерации.")
    started = time.monotonic()
    result = provider.generate(request, on_event=on_event, is_cancelled=is_cancelled)
    try:
        validate_response(result["response"], operation=request.get("operation", "create"))
    except GenerationError as exc:
        exc.usage = result.get("usage")
        exc.raw_response = result.get("raw_response") or result.get("response")
        exc.provider_metadata = result.get("provider_metadata") or {}
        raise
    # A completed receipt must reach durable storage even if cancellation raced it.
    # The backend fence prevents applying it to an already cancelled run.
    result.update(
        provider=provider_name,
        model=result.get("model") or request.get("model") or ("fixture" if provider_name == "fake" else None),
        elapsed_seconds=time.monotonic() - started,
        invocation_id=str(uuid.uuid4()),
    )
    return result


def estimate_reservation(request, price):
    """Conservative one-inference liability, never a claimed actual charge.

    Official limits for the currently verified Codex model profile (2026-10-18):
    872k maximum context and 128k output. Tools and transport retries are disabled,
    so a product invocation cannot silently turn into an unbounded agent loop.
    Other paid providers must declare their bounds in the operator's tariff.
    """
    from decimal import ROUND_UP, Decimal

    if request.get("provider") == "fake":
        return Decimal(0)
    rates = [Decimal(str(price.get(key, 0))) for key in ("input", "cached", "cache_write", "output")]
    if any(not value.is_finite() or value < 0 for value in rates):
        raise GenerationError("invalid_tariff", "Тариф должен содержать конечные неотрицательные цены.")
    if not any(rates):
        return Decimal(0)
    model = request.get("model") or "gpt-6-luna"
    if request.get("provider", "codex") == "codex" and model in {"gpt-6-luna", "gpt-6.1-sol"}:
        context, output, input_factor, output_factor = 872000, 128000, Decimal(2), Decimal("1.5")
    else:
        context, output = price.get("context_window"), price.get("max_output_tokens")
        if type(context) is not int or type(output) is not int or not 0 < output < context:
            raise GenerationError(
                "provider_limits_unknown",
                "Для платного провайдера не заданы проверенные пределы одного запроса.",
            )
        input_factor = Decimal(str(price.get("max_input_multiplier", 1)))
        output_factor = Decimal(str(price.get("max_output_multiplier", 1)))
        if any(not value.is_finite() or value < 1 for value in (input_factor, output_factor)):
            raise GenerationError(
                "invalid_tariff", "Множители тарифов должны быть конечными числами не меньше единицы."
            )
    result = (
        Decimal(context) * max(rates[:3]) * input_factor + Decimal(output) * rates[3] * output_factor
    ) / 1000000
    return result.quantize(Decimal(".000001"), rounding=ROUND_UP)
