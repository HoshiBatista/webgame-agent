"""Preview bearer capabilities must not leak through normal Django log handlers."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from django.core import mail, signing
from django.test import RequestFactory, override_settings
from django.utils.log import AdminEmailHandler

from prompt2play.adapters.django.forge.log_filters import (
    PreviewExceptionFormatter,
    PreviewTokenFilter,
)


@pytest.mark.parametrize(
    "query",
    [
        "token=private-capability&view=mobile",
        "view=mobile&token=private-capability",
        "view=mobile&%74oken=private%2Dcapability&token=second-capability",
    ],
)
def test_access_record_retains_request_status_and_other_query_parameters(query: str) -> None:
    record = logging.LogRecord(
        "django.server",
        logging.WARNING,
        "server.py",
        1,
        '"%s" %s %s',
        (f"GET /preview/7c1f-frozen/?{query} HTTP/1.1", 403, 28),
        None,
    )
    assert PreviewTokenFilter().filter(record)
    message = record.getMessage()
    assert "GET /preview/7c1f-frozen/?" in message
    assert 'HTTP/1.1" 403 28' in message
    assert "view=mobile" in message
    assert "[REDACTED]" in message
    assert "capability" not in message
    assert record.levelno == logging.WARNING


def test_message_and_mapping_arguments_are_sanitized_without_erasing_errors() -> None:
    record = logging.LogRecord(
        "django.request",
        logging.ERROR,
        "request.py",
        1,
        "Forbidden /preview/abc/?token=first %(url)s (%(status)s)",
        ({"url": "https://preview.test/preview/xyz?token=second&width=390", "status": 403},),
        None,
    )
    assert PreviewTokenFilter().filter(record)
    assert record.getMessage() == (
        "Forbidden /preview/abc/?token=[REDACTED] "
        "https://preview.test/preview/xyz?token=[REDACTED]&width=390 (403)"
    )
    assert record.levelno == logging.ERROR


def test_filter_does_not_format_request_objects_or_change_other_token_parameters() -> None:
    class UnformattedRequest:
        def __str__(self) -> str:
            raise AssertionError("Logging filter must not inspect request objects")

    request = UnformattedRequest()
    record = logging.LogRecord(
        "django.request", logging.ERROR, "request.py", 1, "failure %s %s", (request, 500), None
    )
    record.__dict__["request"] = request
    assert PreviewTokenFilter().filter(record)
    assert record.args == (request, 500)
    other = logging.LogRecord(
        "django.request",
        logging.WARNING,
        "request.py",
        1,
        "/api/oauth/?token=unrelated",
        (),
        None,
    )
    assert PreviewTokenFilter().filter(other)
    assert other.getMessage() == "/api/oauth/?token=unrelated"


def test_exception_formatter_masks_url_without_suppressing_exception() -> None:
    try:
        raise RuntimeError("Failed request /preview/abc/?token=exception-secret&width=390")
    except RuntimeError:
        record = logging.LogRecord(
            "django.request", logging.ERROR, "request.py", 1, "Preview failed", (), sys.exc_info()
        )
    PreviewTokenFilter().filter(record)
    message = PreviewExceptionFormatter().format(record)
    assert "exception-secret" not in message
    assert "Traceback (most recent call last)" in message
    assert "RuntimeError: Failed request /preview/abc/?token=[REDACTED]&width=390" in message


def test_admin_exception_report_masks_get_meta_and_traceback_without_mutating_request() -> None:
    capability = signing.dumps({"version": "abc", "artifact": "frozen-artifact"})
    url = f"/preview/abc/?token={quote(capability, safe='')}&view=mobile"
    request = RequestFactory().get(url)
    raw_query = request.META["QUERY_STRING"]
    request.META["RAW_URI"] = url
    try:
        try:
            raise ValueError(f"Underlying capability {capability}")
        except ValueError as cause:
            raise RuntimeError(f"Artifact failed for capability {capability}") from cause
    except RuntimeError:
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            "request.py",
            1,
            "Preview 500: %s",
            (url,),
            sys.exc_info(),
        )
    record.__dict__["request"] = request
    with override_settings(
        DEBUG=False,
        ADMINS=[("Operator", "operator@example.com")],
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    ):
        handler = AdminEmailHandler(include_html=True)
        handler.addFilter(PreviewTokenFilter())
        handler.handle(record)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    emitted = message.subject + message.body + str(message.alternatives[0].content)
    assert capability not in emitted
    assert quote(capability, safe="") not in emitted
    assert "Preview 500:" in emitted
    assert "RuntimeError" in emitted
    assert "Artifact failed for capability [REDACTED]" in emitted
    assert "Underlying capability [REDACTED]" in emitted
    assert "view=mobile" in emitted
    assert "QUERY_STRING" in emitted
    assert "[REDACTED]" in emitted
    assert request.GET["token"] == capability
    assert request.META["QUERY_STRING"] == raw_query
    assert request.META["RAW_URI"] == url


@pytest.mark.parametrize("settings_module", ["settings", "preview_settings"])
def test_both_listeners_mask_tokens_in_actual_django_handlers(
    tmp_path: Path, settings_module: str
) -> None:
    environment = dict(os.environ)
    environment["PROMPT2PLAY_DATA_DIR"] = str(tmp_path / "data")
    environment["DJANGO_DEBUG"] = "1"
    environment["DJANGO_SETTINGS_MODULE"] = f"prompt2play.adapters.django.config.{settings_module}"
    script = """
import logging
import django
django.setup()
logging.getLogger('django.server').warning(
    '\"%s\" %s %s', 'GET /preview/abc/?view=mobile&token=secret-preview HTTP/1.1', 403, 28,
    extra={'status_code': 403},
)
logging.getLogger('django.request').error(
    'Forbidden: %s', '/preview/abc/?token=secret-preview&view=mobile',
)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    emitted = result.stdout + result.stderr
    assert "secret-preview" not in emitted
    assert 'GET /preview/abc/?view=mobile&token=[REDACTED] HTTP/1.1" 403 28' in emitted
    assert "Forbidden: /preview/abc/?token=[REDACTED]&view=mobile" in emitted
