"""Session JSON bridges the root studio and API-scoped CSRF cookies."""

from typing import Any
from unittest.mock import patch

import pytest
from django.test import Client, RequestFactory

from prompt2play.adapters.django.forge import errors
from prompt2play.adapters.django.forge.models import User


@pytest.mark.django_db
def test_session_token_login_rotation_and_protected_mutations(settings: Any) -> None:
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    User.objects.create_user("auth-fixture", password="authored-test-password")
    client = Client(enforce_csrf_checks=True)
    # An unrelated localhost app can leave a malformed root-scoped Django cookie.
    client.cookies["csrftoken"] = "stale-invalid"
    session = client.get("/api/auth/session/")
    before = session.json()["csrf_token"]
    assert len(before) == 64
    assert client.cookies[settings.CSRF_COOKIE_NAME]["path"] == "/api/"
    assert settings.CSRF_COOKIE_NAME != "csrftoken"
    assert "no-store" in session["Cache-Control"]
    credentials = {"username": "auth-fixture", "password": "authored-test-password"}
    missing = client.post("/api/auth/login/", credentials, content_type="application/json")
    assert missing.status_code == 403
    assert missing.json()["code"] == "csrf_failed"
    response = client.post(
        "/api/auth/login/",
        credentials,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=before,
    )
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    after = response.json()["csrf_token"]
    assert after != before
    for invalid in ("", before):
        rejected = client.post(
            "/api/projects/",
            {"title": "Auth fixture", "prompt": "Authored fixture"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=invalid,
        )
        assert rejected.status_code == 403
    created = client.post(
        "/api/projects/",
        {"title": "Auth fixture", "prompt": "Authored fixture"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=after,
    )
    assert created.status_code == 201
    assert client.get("/api/auth/session/").json()["authenticated"] is True
    logout = client.post(
        "/api/auth/logout/", {}, content_type="application/json", HTTP_X_CSRFTOKEN=after
    )
    assert logout.status_code == 200
    assert client.get("/api/auth/session/").json()["authenticated"] is False


def test_csrf_audit_reports_duplicate_cookies_without_secret_values(settings: Any) -> None:
    request = RequestFactory().post(
        "/api/auth/login/",
        HTTP_COOKIE=f"{settings.CSRF_COOKIE_NAME}=first; {settings.CSRF_COOKIE_NAME}=second",
        HTTP_X_CSRFTOKEN="private-token-fixture",
    )
    failure: Any = errors.csrf_failure
    with patch("prompt2play.adapters.django.forge.errors.logging.getLogger") as logger:
        response = failure(request, "CSRF cookie has incorrect length. private-reason-fixture")
    assert response.status_code == 403
    arguments = logger.return_value.warning.call_args.args
    assert arguments[1:] == ("cookie_invalid", True, True, 6, 2)
    assert "private" not in repr(arguments)
    assert "first" not in repr(arguments)
    assert "second" not in repr(arguments)
    assert "require_debug_true" not in settings.LOGGING["handlers"]["auth_audit"]["filters"]
