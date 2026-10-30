import json
import uuid

import httpx
import pytest

from generation.errors import GenerationPending
from generation.providers import relay
from generation.providers.fake import fixture_response
from generation.relay_api.client import Client
from generation.relay_api.protocol import digest
from tests.relay_double import RelayDouble


def test_adapter_retries_same_job_after_lost_submit_ack(monkeypatch):
    store = RelayDouble()
    client = Client("https://relay.test", "x" * 32, transport=httpx.WSGITransport(store))
    monkeypatch.setattr(relay, "configuration", lambda: ("https://relay.test", "x" * 32))
    monkeypatch.setattr(relay, "Client", lambda *_: client)
    monkeypatch.setattr(client, "close", lambda: None)
    ident = str(uuid.uuid4())
    request = {
        "relay": {
            "id": ident,
            "url": "https://relay.test",
            "payload": {"model": "qwen38", "messages": [], "max_tokens": 32},
        }
    }
    original = client.call
    calls = []

    def lose_ack(method, path, body=None):
        result = original(method, path, body)
        if method == "PUT":
            calls.append(1)
            raise httpx.ReadError("ACK lost")
        return result

    monkeypatch.setattr(client, "call", lose_ack)
    for _ in range(3):
        with pytest.raises(GenerationPending):
            relay.generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    assert calls == [1] and len(store.jobs) == 1
    store.finish(
        ident,
        "gpu",
        {
            "ok": True,
            "result": {
                "response": {
                    "model": "qwen38",
                    "choices": [
                        {"message": {"content": json.dumps(fixture_response())}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
            },
        },
    )
    assert (
        relay.generate(request, on_event=lambda _: None, is_cancelled=lambda: False)["response"]
        == fixture_response()
    )
    client.http.close()


def test_corrupted_receipt_is_refetched():
    receipt = {"ok": True, "result": {"response": {}}}
    with pytest.raises(GenerationPending):
        relay.unpack({"receipt": receipt, "receipt_hash": "wrong"}, str(uuid.uuid4()))
    assert digest(json.loads(json.dumps(receipt))) == digest(receipt)


@pytest.mark.parametrize(
    "text,finish,code",
    [
        ("ordinary prose", "stop", "invalid_json"),
        ("{}", "length", "incomplete_response"),
        ("", "content_filter", "provider_refusal"),
    ],
)
def test_application_content_validation_belongs_to_gameforge(text, finish, code):
    from generation.errors import GenerationError

    receipt = {
        "ok": True,
        "result": {
            "response": {
                "model": "qwen38",
                "choices": [{"message": {"content": text}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        },
    }
    with pytest.raises(GenerationError) as error:
        relay.unpack({"receipt": receipt, "receipt_hash": digest(receipt)}, "stable-id")
    assert error.value.code == code
    assert error.value.usage["output_tokens"] == 5
    assert error.value.provider_metadata["relay_job_id"] == "stable-id"


@pytest.mark.parametrize("status,code", [(401, "relay_unauthorized"), (403, "relay_forbidden"), (507, "relay_storage_full")])
def test_permanent_relay_errors_require_operator_without_discarding_job(monkeypatch, status, code):
    from generation.relay_api.client import RelayHTTPError
    request = {"relay": {"id": str(uuid.uuid4()), "url": "https://relay.test", "payload": {}}}
    monkeypatch.setattr(relay, "configuration", lambda: ("https://relay.test", "x" * 32))
    monkeypatch.setattr(Client, "call", lambda *args: (_ for _ in ()).throw(RelayHTTPError(status)))
    with pytest.raises(GenerationPending) as error:
        relay.fetch(request)
    assert error.value.operator_required
    assert error.value.code == code and error.value.retry_after == 300
    assert error.value.metadata == {"http_status": status}
