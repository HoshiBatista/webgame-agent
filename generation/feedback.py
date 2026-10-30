"""Small repair inputs; the complete validation report remains authoritative."""

import json
import re
from urllib.parse import urlsplit, urlunsplit

MAX_FINDINGS = 3
MAX_MESSAGE_CHARS = 500
MAX_CONTEXT_CHARS = 1000
MAX_CHECK_IDS = 12

_URL = re.compile(r"https?://[^\s<>\"']+")
_CREDENTIAL = re.compile(
    r"(?i)(\b(?:authorization|api[_-]?key|access[_-]?token|password|secret)\b"
    r"[\"']?\s*[:=]\s*[\"']?)(?:Bearer\s+)?[^\s,;\"']+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")
_PRIVATE_KEYS = {"raw_response", "response", "headers", "authorization", "token", "api_key", "password", "secret"}


def _safe_url(match):
    try:
        parts = urlsplit(match.group())
        host = parts.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return "[URL omitted]"


def _text(value, limit=MAX_MESSAGE_CHARS):
    text = _URL.sub(_safe_url, str(value))
    text = _CREDENTIAL.sub(r"\1[redacted]", text)
    text = _BEARER.sub("Bearer [redacted]", text)
    return text if limit is None or len(text) <= limit else text[: limit - 1] + "…"


def _context(value, depth=0):
    """Keep small observed values, not whole state dumps or response payloads."""
    if isinstance(value, str):
        return _text(value, 250)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= 3:
        return "[nested value omitted]"
    if isinstance(value, dict):
        fields = [(key, item) for key, item in value.items() if str(key).lower() not in _PRIVATE_KEYS]
        result = {_text(key, 80): _context(item, depth + 1) for key, item in fields[:8]}
        if len(fields) > 8:
            result["…"] = "additional fields omitted"
        return result
    if isinstance(value, list):
        return [_context(item, depth + 1) for item in value[:8]] + (["…"] if len(value) > 8 else [])
    return "[unsupported value omitted]"


def _bounded_context(value):
    result = _context(value)
    encoded = json.dumps(result, ensure_ascii=False)
    return result if len(encoded) <= MAX_CONTEXT_CHARS else encoded[: MAX_CONTEXT_CHARS - 1] + "…"


def _finding(source):
    # Explicit fields exclude raw responses, screenshots and provider credentials.
    result = {}
    for key in ("code", "message", "check_id", "path", "file", "filename", "line", "column",
                "script_index", "script_line", "script_column", "location", "column_unit", "file_hash",
                "source_excerpt", "bundled_location", "excerpt_start_column", "excerpt_end_column",
                "excerpt_truncated", "source_anchor", "source_structure"):
        if key in source:
            result[key] = _text(source[key]) if isinstance(source[key], str) else _bounded_context(source[key])
    for key in ("before", "after", "expected", "compile_issue"):
        if key in source:
            result[key] = _bounded_context(source[key])
    if isinstance(source.get("diagnostic"), dict):
        result["diagnostic"] = _diagnostic(source["diagnostic"])
    return result


def _diagnostic(source):
    from validation.diagnostics import bounded

    def scrub(value):
        if isinstance(value, str):
            # Let bounded() mark any shortening; redaction alone is not truncation.
            return _text(value, None)
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if k.lower() not in _PRIVATE_KEYS}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value
    allowed = {"check_id", "step_index", "step", "observation", "before", "after", "expected",
               "actual_type", "viewport", "controls", "truncated", "state", "selector_matches", "unavailable",
               "observations", "observation_skips", "input_probe"}
    return bounded(scrub({k: v for k, v in source.items() if k in allowed}), 4096)


def _unique(findings, *, root_errors=False):
    result: list[dict] = []
    seen: dict[str, dict] = {}
    for source in findings:
        item = _finding(source)
        for key in ("errors", "requests"):
            values = source.get(key)
            if isinstance(values, list) and values and isinstance(values[0], str):
                item[key] = [_text(values[0])]
        identity = {key: value for key, value in item.items() if key not in {"check_id"}}
        if root_errors and item.get("errors"):
            # Stack locations can vary by scenario; the first error line is the root symptom.
            identity = {"code": item.get("code"), "error": item["errors"][0].splitlines()[0]}
        key = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        if key in seen:
            existing = seen[key]
            check_id = item.get("check_id")
            if check_id and check_id != existing.get("check_id"):
                ids = existing.setdefault("check_ids", [existing["check_id"]] if existing.get("check_id") else [])
                if check_id not in ids and len(ids) < MAX_CHECK_IDS:
                    ids.append(check_id)
        elif len(result) < MAX_FINDINGS:
            seen[key] = item
            result.append(item)
    remaining = 4096
    for item in result:
        if "diagnostic" in item:
            size = len(json.dumps(item["diagnostic"], ensure_ascii=False).encode())
            if size > remaining:
                item.pop("diagnostic")
            else:
                remaining -= size
    return result


def focus_findings(findings: list[dict]) -> list[dict]:
    """Select up to three actionable symptoms from the earliest failing stage.

    Only repair context is reduced. No checks, findings, or verdicts are changed in
    storage, and the next candidate must still pass the complete validation suite.
    Input order breaks ties deterministically and all returned values are copies.
    """
    sources = [finding for finding in findings if isinstance(finding, dict)]
    syntax = [finding for finding in sources if finding.get("code") == "javascript_syntax"]
    if syntax:
        return _unique(syntax)
    runtime = []
    for finding in sources:
        if finding.get("code") != "runtime_or_network":
            continue
        for field in ("errors", "requests"):
            values = finding.get(field)
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str) and value.strip():
                        runtime.append({**_finding(finding), field: [value]})
    if runtime:
        # Actual JavaScript failures precede blocked-resource symptoms.
        runtime.sort(key=lambda finding: "errors" not in finding)
        return _unique(runtime, root_errors=True)
    return _unique(sources)
