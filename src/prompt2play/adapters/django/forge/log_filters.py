"""Keep scoped preview capabilities out of Django access and request logs."""

from __future__ import annotations

import logging
import re
from html import escape
from typing import Any
from urllib.parse import quote, unquote_plus

from django.http import HttpRequest
from django.utils.log import ServerFormatter
from django.views.debug import ExceptionReporter, SafeExceptionReporterFilter


_PREVIEW_QUERY = re.compile(r"(/preview/[A-Za-z0-9_-]+/?\?)([^\s\"'<>#]*)")
_PREVIEW_PATH = re.compile(r"/preview/[A-Za-z0-9_-]+/?\Z")


def _redact_query(query: str) -> str:
    parameters = []
    for parameter in query.split("&"):
        name, separator, value = parameter.partition("=")
        if separator and unquote_plus(name) == "token":
            value = "[REDACTED]"
        parameters.append(name + separator + value)
    return "&".join(parameters)


def _preview_request(request: HttpRequest | None) -> bool:
    return request is not None and bool(_PREVIEW_PATH.fullmatch(request.path_info))


def redact_preview_tokens(message: str) -> str:
    """Preserve the request and diagnostics while masking only preview token values."""

    def redact_query(match: re.Match[str]) -> str:
        return match.group(1) + _redact_query(match.group(2))

    return _PREVIEW_QUERY.sub(redact_query, message)


class PreviewTokenFilter(logging.Filter):
    """Sanitize string fields without formatting request objects or environment data."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_preview_tokens(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_preview_tokens(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_preview_tokens(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        if isinstance(record.exc_text, str):
            record.exc_text = redact_preview_tokens(record.exc_text)
        return True


class PreviewExceptionFormatter(logging.Formatter):
    """Cover exception URLs formatted after record filters have already run."""

    def formatException(self, ei: Any) -> str:
        return redact_preview_tokens(super().formatException(ei))


class PreviewServerFormatter(ServerFormatter):
    def formatException(self, ei: Any) -> str:
        return redact_preview_tokens(super().formatException(ei))


class PreviewExceptionReporterFilter(SafeExceptionReporterFilter):
    """Django's existing reporter filtering, with scoped preview query protection."""

    def get_safe_request_meta(self, request: HttpRequest | None) -> dict[str, Any]:
        meta = super().get_safe_request_meta(request)
        if _preview_request(request):
            for key, value in meta.items():
                if isinstance(value, str):
                    meta[key] = (
                        _redact_query(value)
                        if key == "QUERY_STRING"
                        else redact_preview_tokens(value)
                    )
        return meta


class PreviewExceptionReporter(ExceptionReporter):
    """Filter Django's direct GET/URI report fields and rendered exception strings."""

    def _capabilities(self) -> set[str]:
        if not _preview_request(self.request):
            return set()
        # Real signed capabilities are long. Their exact bytes can also occur in
        # traceback locals or exception strings outside a URL. Avoid replacing
        # arbitrary short, invalid token input throughout otherwise useful reports.
        return {
            variant
            for value in self.request.GET.getlist("token")
            if len(value) >= 32
            for variant in (value, quote(value, safe=""), escape(value))
        }

    def _sanitize_text(self, text: str) -> str:
        if not _preview_request(self.request):
            return text
        text = redact_preview_tokens(text)
        for capability in self._capabilities():
            text = text.replace(capability, "[REDACTED]")
        return text

    def get_traceback_text(self) -> str:
        # Chained exception objects are formatted by Django's template after
        # get_traceback_data(), so also sanitize the resulting string.
        return self._sanitize_text(super().get_traceback_text())

    def get_traceback_html(self) -> str:
        return self._sanitize_text(super().get_traceback_html())

    def get_traceback_data(self) -> dict[str, Any]:
        data = super().get_traceback_data()
        if not _preview_request(self.request):
            return data
        data["request_GET_items"] = [
            (name, "[REDACTED]" if name == "token" else value)
            for name, value in self.request.GET.items()
        ]

        def sanitize(value: Any) -> Any:
            if isinstance(value, str):
                return self._sanitize_text(value)
            if isinstance(value, dict):
                return {key: sanitize(item) for key, item in value.items()}
            if isinstance(value, list):
                return [sanitize(item) for item in value]
            if isinstance(value, tuple):
                return tuple(sanitize(item) for item in value)
            # Never stringify request objects, environments or arbitrary locals.
            return value

        return sanitize(data)
