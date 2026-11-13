"""Frozen advisory context. Never an acceptance oracle or a new model operation."""

import json
from copy import deepcopy

from .errors import ContractError
from .requirements import digest

VERSION = 1
MAX_SNAPSHOT_BYTES = 8192
MAX_CONTEXT_CHARS = 1600
LABEL = "Демонстрационные данные"


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or (
        snapshot.get("version") != VERSION or snapshot.get("source") != "demo"
        or not isinstance(snapshot.get("model_context"), str)
        or not snapshot["model_context"].startswith(LABEL)
        or len(snapshot["model_context"]) > MAX_CONTEXT_CHARS
        or not isinstance(snapshot.get("recommendations"), list)
        or not 1 <= len(snapshot["recommendations"]) <= 2
    ):
        raise ContractError("invalid_analytics_snapshot", "Повреждён сохранённый контекст аналитики.")
    try:
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode()
        valid = len(encoded) <= MAX_SNAPSHOT_BYTES and snapshot.get("snapshot_hash") == digest(
            {k: v for k, v in snapshot.items() if k != "snapshot_hash"}
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ContractError("invalid_analytics_snapshot", "Не совпадает hash контекста аналитики.")
    return deepcopy(snapshot)


def model_context(request):
    snapshot = request.get("analytics_snapshot")
    if not snapshot:
        return None
    validate_snapshot(snapshot)
    if request.get("operation", "create") not in {"plan", "create"} or (
        snapshot.get("audience") != request.get("audience", "everyone")
    ):
        return None
    return snapshot["model_context"]


def guidance(request):
    if model_context(request) is None:
        return ""
    return """
OPTIONAL ANALYTICS IDEAS
analytics contains explicitly selected ideas from DEMONSTRATION data, not observed customer results.
The current explicit request takes priority, then compatible saved preferences, then these ideas.
Apply ideas only where compatible; never substitute another genre or add unrelated scope.
These are advisory design choices, not user quotes or new mandatory requirements. In planning use
origin=design and quote="" for such choices. Do not claim statistical proof or that you tested an idea.
"""
