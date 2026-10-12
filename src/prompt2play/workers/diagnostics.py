"""Bounded worker diagnostics without credentials, provider transcripts or locals."""

from __future__ import annotations

import json
import os
import re
import traceback
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SECRET_NAME = re.compile(r"token|password|secret|api.?key|authorization|cookie", re.I)
_CREDENTIAL = re.compile(
    r"(?i)(\bBearer\s+)\S+|"
    r"((?:token|password|secret|api[_-]?key|authorization|cookie)[\"']?\s*[:=]\s*[\"']?)"
    r"[^\s\"'&,;}]+"
)
_KEY = re.compile(r"(?:sk-(?:proj-)?|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{16,}")
_URL_CREDENTIAL = re.compile(r"(https?://)[^\s/@]+:[^\s/@]+@", re.I)


def safe_message(message: str, secrets: Iterable[str] = ()) -> str:
    values = {
        value for name, value in os.environ.items() if _SECRET_NAME.search(name) and len(value) >= 4
    } | {value for value in secrets if value}
    for value in sorted(values, key=len, reverse=True):
        message = message.replace(value, "[REDACTED]")
    message = _CREDENTIAL.sub(lambda match: (match[1] or match[2]) + "[REDACTED]", message)
    message = _KEY.sub("[REDACTED]", message)
    message = _URL_CREDENTIAL.sub(r"\1[REDACTED]@", message)
    return message[:4000]


def exception_details(exc: Exception, secrets: Iterable[str] = ()) -> dict[str, Any]:
    """Respect suppressed exception context; never render traceback source/locals."""
    chain: list[dict[str, Any]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        item: dict[str, Any] = {
            "type": type(current).__name__,
            "message": safe_message(str(current), secrets),
            "frames": [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(current.__traceback__)[-12:]
            ],
        }
        diagnostic = getattr(current, "structured_diagnostic", None)
        if isinstance(diagnostic, dict):
            # The provider constructs these schema coordinates, excluding rejected data.
            item["structured_diagnostic"] = {
                key: value
                for key, value in diagnostic.items()
                if key in {"category", "keyword", "instance_path", "schema_path"}
            }
        provider = getattr(current, "provider_diagnostic", None)
        if isinstance(provider, dict):
            item["provider_diagnostic"] = {
                key: safe_message(value, secrets) if isinstance(value, str) else value
                for key, value in provider.items()
                if key
                in {
                    "provider",
                    "exit_code",
                    "category",
                    "terminal_event",
                    "code",
                    "message",
                    "events_sha256",
                    "stderr_sha256",
                }
            }
        chain.append(item)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return {"exceptions": chain}


def emit(event: str, *, secrets: Iterable[str] = (), **fields: Any) -> None:
    """One JSON object per line, suitable for a private captured worker log."""
    record = {"timestamp": datetime.now(UTC).isoformat(), "event": event, **fields}

    # Keep JSON valid by sanitizing values, including schema paths, before encoding.
    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return safe_message(value, secrets)
        if isinstance(value, dict):
            return {str(key): clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    print(json.dumps(clean(record), ensure_ascii=False, separators=(",", ":")), flush=True)
