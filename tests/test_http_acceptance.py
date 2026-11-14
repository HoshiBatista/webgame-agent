"""The release probe must obey the same source identity contract as the UI."""

from unittest.mock import Mock

import httpx
import pytest

from scripts.verify_container import run, verify


@pytest.mark.parametrize("source", [None, {"id": "shown-draft", "artifact_hash": "a" * 64}])
def test_probe_sends_exact_displayed_source_and_explicit_fixture_profile(source):
    def api(method, path, payload):
        assert (method, path) == ("POST", "/api/chats/owned-chat/runs/")
        assert payload["model_profile"] == ""
        assert payload["prompt"] == "Change background"
        if source:
            assert payload["source_revision_id"] == source["id"]
            assert payload["source_artifact_hash"] == source["artifact_hash"]
        else:
            assert "source_revision_id" not in payload
            assert "source_artifact_hash" not in payload
        return {"status": "succeeded", "provider": "fake", "model": "fixture"}

    result, _ = run(api, "owned-chat", "Change background", source=source)
    assert result["status"] == "succeeded"


def test_rejected_edit_never_retries_as_create():
    request = httpx.Request("POST", "http://localhost/api/chats/owned/runs/")
    rejected = httpx.Response(409, request=request)
    api = Mock(side_effect=httpx.HTTPStatusError("source changed", request=request, response=rejected))
    with pytest.raises(httpx.HTTPStatusError):
        run(api, "owned", "Change background", source={"id": "draft", "artifact_hash": "a" * 64})
    assert api.call_count == 1


def test_live_provider_is_rejected_before_any_chat_or_run_creation(monkeypatch):
    client = httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(lambda request: httpx.Response(
        200 if request.url.path != "/api/login/" or request.headers.get("X-CSRFToken") else 403,
        json={"csrfToken": "fixture-csrf", "capabilities": {"provider": "relay", "model": "real"}},
    )))
    original = client.request
    paths = []

    def capture(method, url, **kwargs):
        paths.append(url)
        return original(method, url, **kwargs)

    monkeypatch.setattr(client, "request", capture)
    monkeypatch.setattr("scripts.verify_container.httpx.Client", lambda **kwargs: client)
    with pytest.raises(RuntimeError, match="fixture provider"):
        verify("http://localhost", "http://localhost:8081", "test", "test-password")
    assert not any("chats" in str(path) or "runs" in str(path) for path in paths)
