import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize("provider,model", [("codex", "gpt-6-luna"), ("codex_api", "gpt-6-sol"),
                                           ("vllm", "qwen38"), ("relay", "qwen38")])
def test_llm_aliases_do_not_replace_codex_selection(monkeypatch, provider, model):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    monkeypatch.setenv("DJANGO_SECRET_KEY", "isolated-configuration-test")
    monkeypatch.setenv("GAMEFORGE_PROVIDER", provider)
    monkeypatch.setenv("GAMEFORGE_MODEL", "")
    monkeypatch.setenv("GAMEFORGE_VLLM_MODEL", "")
    monkeypatch.setenv("LLM_MODEL", "qwen38")
    values = runpy.run_path(str(Path(__file__).resolve().parents[1] / "gameforge/settings.py"))
    assert values["GAMEFORGE_PROVIDER"] == provider
    assert values["GAMEFORGE_MODEL"] == model


@pytest.mark.parametrize("value", ["0", "1", "4", "999", "invalid"])
def test_repair_limit_cannot_create_an_unbounded_new_run(monkeypatch, value):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    monkeypatch.setenv("GAMEFORGE_MAX_REPAIR_ATTEMPTS", value)
    with pytest.raises(ValueError):
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "gameforge/settings.py"))


@pytest.mark.parametrize("trusted", [False, True])
def test_https_proxy_requires_explicit_trust(monkeypatch, trusted):
    from django.http import HttpResponse
    from django.middleware.security import SecurityMiddleware
    from django.test import RequestFactory, override_settings

    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    monkeypatch.setenv("DJANGO_SECRET_KEY", "isolated-configuration-test")
    monkeypatch.setenv("DJANGO_TRUST_PROXY_HEADERS", "1" if trusted else "0")
    monkeypatch.setenv("DJANGO_SSL_REDIRECT", "1")
    monkeypatch.setenv("DJANGO_SECURE_COOKIES", "1")
    values = runpy.run_path(str(Path(__file__).resolve().parents[1] / "gameforge/settings.py"))
    with override_settings(
        SECURE_PROXY_SSL_HEADER=values.get("SECURE_PROXY_SSL_HEADER"),
        SECURE_SSL_REDIRECT=values["SECURE_SSL_REDIRECT"],
        ALLOWED_HOSTS=["testserver"],
    ):
        request = RequestFactory().get("/api/session/", HTTP_X_FORWARDED_PROTO="https")
        response = SecurityMiddleware(lambda request: HttpResponse("ok"))(request)
        assert request.is_secure() is trusted
        assert response.status_code == (200 if trusted else 301)
    assert values["SESSION_COOKIE_SECURE"] and values["CSRF_COOKIE_SECURE"]


@pytest.mark.parametrize('value', ['0', '-1', '101', 'invalid'])
def test_remote_pro_concurrency_is_bounded(monkeypatch, value):
    monkeypatch.setattr('dotenv.load_dotenv', lambda *_: None)
    monkeypatch.setenv('GAMEFORGE_CODEX_API_CONCURRENCY', value)
    with pytest.raises(ValueError):
        runpy.run_path(str(Path(__file__).resolve().parents[1] / 'gameforge/settings.py'))


@pytest.mark.parametrize('value', [1, 2, 100])
def test_remote_pro_concurrency_accepts_supported_range(monkeypatch, value):
    monkeypatch.setattr('dotenv.load_dotenv', lambda *_: None)
    monkeypatch.setenv('GAMEFORGE_CODEX_API_CONCURRENCY', str(value))
    values = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'gameforge/settings.py'))
    assert values['GAMEFORGE_CODEX_API_CONCURRENCY'] == value
