"""Bounded provider errors, without transcripts, request payloads or credentials."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .diagnostics import safe_message


def error_excerpt(value: str) -> str:
    # Providers sometimes embed request data or headers after an error. Retain
    # the diagnosis before that payload; never persist the echoed request.
    value = re.split(
        r"(?i)\b(?:prompt|messages|input|request_body|headers|authorization|cookie)[\"']?\s*[=:]",
        value,
        maxsplit=1,
    )[0]
    value = re.sub(r'https?://[^\s"<>]+', "[URL]", value)
    return safe_message(value)[:1000]


def codex_diagnostic(events: Path, stderr: Path, exit_code: int) -> dict[str, Any]:
    raw = events.read_bytes()[:8_000_000]
    errors = stderr.read_bytes()[:1_000_000]
    result: dict[str, Any] = {
        "provider": "codex",
        "exit_code": exit_code,
        "category": "unknown",
        "terminal_event": "",
        "code": "",
        "message": "",
        "events_sha256": hashlib.sha256(raw).hexdigest(),
        "stderr_sha256": hashlib.sha256(errors).hexdigest(),
    }
    messages: list[str] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(event, dict) or event.get("type") not in ("error", "turn.failed"):
            continue
        result["terminal_event"] = event["type"]
        error = event.get("error")
        error = error if isinstance(error, dict) else event
        code = error.get("code", "")
        if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code):
            result["code"] = code
        message = error.get("message", "")
        if isinstance(message, str):
            messages.append(message)
    if not messages:
        # No arbitrary process output: only explicit error lines, never prompts,
        # response events or successful assistant messages.
        messages = [
            line
            for line in errors.decode("utf-8", errors="replace").splitlines()
            if re.search(r"(?i)(^error:|\bERROR\b|^error\[)", line)
        ][:3]
    detail = "\n".join(messages).lower()
    for category, words in (
        ("schema", ("schema", "response_format")),
        ("authentication", ("unauthorized", "authentication", "401")),
        ("model_unavailable", ("model_not_found", "unsupported model", "model is not")),
        ("quota", ("rate limit", "quota", "429", "usage limit")),
        ("connection", ("connection", "network", "dns", "certificate", "stream disconnected")),
        ("context_length", ("context length", "context window", "too many tokens")),
        ("configuration", ("unexpected argument", "unrecognized option", "invalid value")),
    ):
        if any(word in detail for word in words):
            result["category"] = category
            break
    result["message"] = (
        error_excerpt("\n".join(messages))
        or "Codex returned no usable result; the cause is unknown."
    )
    return result
