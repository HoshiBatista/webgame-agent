"""Versioned Standard API equivalents, never a subscription charge or an invoice."""

from __future__ import annotations

import json
import os
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from importlib.resources import files
from pathlib import Path
from typing import Any

NANO = 1_000_000_000


def nano_usd(value: str | Decimal) -> int:
    return int(Decimal(value) * NANO)


def usd(value: int) -> str:
    return format(Decimal(value) / NANO, ".9f")


def catalog() -> dict[str, Any]:
    """Operator-owned file overrides the bundled, explicitly dated rate card."""
    configured = os.environ.get("PROMPT2PLAY_PRICING_FILE")
    raw = (
        Path(configured).read_text()
        if configured
        else files("prompt2play.resources").joinpath("pricing.json").read_text()
    )
    data: dict[str, Any] = json.loads(raw)
    if data.get("schema_version") != 1 or data.get("service_tier") != "standard":
        raise ValueError("Unsupported pricing policy")
    for model, rates in data["models"].items():
        if not isinstance(model, str) or not model or len(model) > 120:
            raise ValueError("Invalid pricing model")
        for key in ("input", "cached_input", "cache_write", "output"):
            try:
                rate = Decimal(rates[key])
            except (InvalidOperation, TypeError) as exc:
                raise ValueError("Invalid pricing rate") from exc
            if not rate.is_finite() or rate <= 0 or rate > 1000:
                raise ValueError("Invalid pricing rate")
        if not (
            Decimal(rates["cached_input"])
            <= Decimal(rates["input"])
            <= Decimal(rates["cache_write"])
        ):
            raise ValueError("Inconsistent cache rates")
    return data


def snapshot(model: str, provider: str) -> dict[str, Any]:
    data = catalog()
    if model not in data["models"]:
        raise ValueError(f"Для модели {model} нет подтверждённого тарифа. Выберите другую модель.")
    return {
        "schema_version": 1,
        "model": model,
        "provider": provider,
        "as_of": data["as_of"],
        "service_tier": "standard",
        "source": f"https://developers.openai.com/api/docs/models/{model}",
        "usd_per_million": dict(data["models"][model]),
        "long_context_threshold": 272000,
        "long_input_multiplier": "2",
        "long_output_multiplier": "1.5",
        "policy": "standard-equivalent-v1",
    }


def cost_bounds(usage: dict[str, int], pricing: dict[str, Any]) -> tuple[int, int]:
    """Per invocation, in nanodollars. Cached input is a subset, never added twice.

    Receipts do not expose cache-write counts. Lower uses ordinary fresh input;
    upper treats all fresh input as cache writes. A Codex turn may contain several
    requests, so its aggregate cannot prove that any one request used long context.
    For that case lower uses short rates and upper uses long rates when possible.
    Reasoning tokens are already part of output_tokens.
    """
    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise ValueError("Incomplete or invalid usage receipt")
    incoming, cached, output = (
        usage[k] for k in ("input_tokens", "cached_input_tokens", "output_tokens")
    )
    if cached > incoming:
        raise ValueError("Cached input exceeds total input")
    rates = {key: Decimal(value) for key, value in pricing["usd_per_million"].items()}
    long = incoming > pricing["long_context_threshold"]
    high_input = Decimal(pricing["long_input_multiplier"]) if long else Decimal(1)
    high_output = Decimal(pricing["long_output_multiplier"]) if long else Decimal(1)
    low_input = high_input if pricing["provider"] == "openai" else Decimal(1)
    low_output = high_output if pricing["provider"] == "openai" else Decimal(1)
    lower = (
        (incoming - cached) * rates["input"] + cached * rates["cached_input"]
    ) * low_input + output * rates["output"] * low_output
    upper = (
        (incoming - cached) * rates["cache_write"] + cached * rates["cached_input"]
    ) * high_input + output * rates["output"] * high_output
    return (
        int((lower * 1000).to_integral_value(rounding=ROUND_CEILING)),
        int((upper * 1000).to_integral_value(rounding=ROUND_CEILING)),
    )


def reservation_usage(prompt: str, max_output: int, schema: str = "") -> dict[str, int]:
    # Bytes + overhead deliberately overestimate text tokens. Codex does not expose
    # a portable output cap; this reserves an estimate, not a provider-side ceiling.
    return {
        "input_tokens": len(prompt.encode()) + len(schema.encode()) + 4096,
        "cached_input_tokens": 0,
        "output_tokens": max_output,
    }
