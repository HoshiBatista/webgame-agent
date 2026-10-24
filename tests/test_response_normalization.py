import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from generation.errors import ContractError
from generation.normalization import normalize_response
from generation.providers.fake import fixture_response
from generation.schema import validate_response
from generation.service import generate


def noncanonical_response():
    response = fixture_response()
    response["type"] = response.pop("status")
    response["scope_refusal"] = None
    for item in response["files"]:
        item["file_hash"] = None
    for item in response["checks"]:
        item["title"] = ""
    return response


def test_normalization_preserves_original_code_and_check_semantics():
    source = noncanonical_response()
    snapshot = deepcopy(source)
    result, paths = normalize_response(source)
    validate_response(result, operation="create")
    assert source == snapshot
    assert result == fixture_response()
    assert "type->status" in paths
    assert normalize_response(result) == (result, [])


@pytest.mark.parametrize("case", ["unknown", "conflict", "missing", "hash", "title", "refusal", "long_check"])
def test_normalization_never_discards_ambiguity_or_weakens_checks(case):
    source = noncanonical_response()
    if case == "unknown":
        source["checks"][0]["force_win"] = True
    elif case == "conflict":
        source["status"] = "unchanged"
    elif case == "missing":
        del source["checks"][0]["requirement"]
    elif case == "hash":
        source["files"][0]["file_hash"] = "claimed-hash"
    elif case == "title":
        source["checks"][0]["title"] = "Potentially meaningful text"
    elif case == "refusal":
        source["scope_refusal"] = "I cannot implement this"
    else:
        source["checks"][0]["steps"] = [{"action": "wait", "ms": 10000}] * 2
    result, _ = normalize_response(source)
    with pytest.raises(ContractError):
        validate_response(result, operation="create")


def test_provider_result_preserves_raw_response_usage_and_normalization_audit():
    raw = json.dumps(noncanonical_response())
    usage = {"input_tokens": 1, "output_tokens": 2}
    with patch("generation.service.fake.generate", return_value={
        "response": json.loads(raw), "raw_response": raw, "usage": usage,
    }):
        result = generate({"provider": "fake", "operation": "create"},
                          on_event=lambda _: None, is_cancelled=lambda: False)
    assert result["response"] == fixture_response()
    assert result["raw_response"] == raw
    assert result["usage"] == usage
    assert result["provider_metadata"]["response_normalization"]["paths"]


def test_normalized_response_still_cannot_change_trusted_operation():
    response = noncanonical_response()
    normalized, _ = normalize_response(response)
    with pytest.raises(ContractError, match="вид операции"):
        validate_response(normalized, operation="repair")


def test_relay_passes_strict_schema_without_a_model_call(monkeypatch):
    from generation.providers.relay import prepare
    from generation.schema import response_schema

    monkeypatch.setenv("GAMEFORGE_RELAY_URL", "https://relay.example")
    monkeypatch.setenv("GAMEFORGE_RELAY_API_KEY", "test-key" * 8)
    monkeypatch.setenv("GAMEFORGE_VLLM_JSON_MODE", "json_schema")
    monkeypatch.setenv("GAMEFORGE_VLLM_CONTEXT_CHECK", "server")
    prepared = prepare({"model": "qwen38", "operation": "create", "execution_limits": {
        "context_window": 32768, "max_output_tokens": 16384,
    }}, "d5d09aca-cf06-46f8-b3d9-0d83df364994")
    fmt = prepared["payload"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == response_schema({"operation": "create"})
