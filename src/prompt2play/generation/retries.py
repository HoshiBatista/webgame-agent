"""Durable eligibility for one additional dispatch after local Codex cleanup.

This marker does not establish zero remote spend: unknown usage stays reserved.
Network errors, cancellation and worker death never receive this marker.
"""

from typing import Any

CODEX_TIMEOUT_RECEIPT = {"interruption": "codex_wall_timeout"}
TIMEOUT_RETRY_SUFFIX = ":retry:1"


def structured_diagnostic(error: BaseException) -> dict[str, Any] | None:
    """Only locally validated response failures are safe model feedback.

    Do not turn a transport failure, cancellation, or arbitrary exception into
    permission to dispatch another paid request.
    """
    value = getattr(error, "structured_diagnostic", None)
    if not isinstance(value, dict) or value.get("category") not in ("schema", "invalid_json"):
        return None
    return {
        key: value[key]
        for key in ("category", "keyword", "instance_path", "schema_path")
        if key in value
    }


def is_rejected_response(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"rejection", "diagnostic"}
        and value["rejection"] == "structured_output"
        and isinstance(value["diagnostic"], dict)
        and value["diagnostic"].get("category") in ("schema", "invalid_json")
    )
