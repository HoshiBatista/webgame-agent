import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from generation.errors import GenerationError
from generation.providers import codex, vllm
from generation.providers.fake import fixture_response
from generation.service import generate as generate_operation


@pytest.mark.parametrize("version", ["0.163.0-alpha.10.2", "0.163.0-alpha.11.2", "0.164.0-alpha.11.1", "0.999.0"])
def test_codex_cli_contract_allows_only_reviewed_versions(monkeypatch, version):
    monkeypatch.setattr(codex, "binary", lambda: "codex")
    monkeypatch.setattr(codex.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=f"codex-cli {version}"))
    if version == "0.999.0":
        with pytest.raises(GenerationError) as exc:
            codex.verify_cli_contract()
        assert exc.value.code == "codex_profile_unverified"
    else:
        assert codex.verify_cli_contract() == f"codex-cli {version}"


def generate(request, **kwargs):
    if request.get("provider") == "vllm":
        request = {**request, "execution_limits": {"context_window": 64000, "max_output_tokens": 8000}}
    return generate_operation(request, **kwargs)


@pytest.mark.parametrize("operation", ["create", "edit", "repair", "check_repair"])
def test_codex_receives_selected_operation_schema_with_rpc_double(codex_rpc, operation):
    from generation.schema import response_schema

    request = {"provider": "codex", "operation": operation, "model": "gpt-6-luna"}
    reply = fixture_response()
    if operation == "check_repair":
        from generation.check_repair import permission

        policy = permission("a" * 64, reply["checks"], reply["design"])
        request.update(base_revision="base", check_repair=policy)
        reply = {"operation": operation, "status": "ok", "base_revision": "base",
                 "artifact_hash": policy["artifact_hash"], "checks_hash": policy["checks_hash"],
                 "checks": reply["checks"], "message": "Сценарии проверки."}
    elif operation != "create":
        request["base_revision"] = "base"
        reply.update(operation=operation, base_revision="base", files=[], checks=[])
    codex_rpc["events"][1]["params"]["item"]["text"] = json.dumps(reply)
    result = generate_operation(request, on_event=lambda _: None, is_cancelled=lambda: False)
    params = next(params for method, params in codex_rpc["calls"] if method == "turn/start")
    assert params["outputSchema"] == response_schema(request)
    assert params["outputSchema"]["properties"]["operation"]["enum"] == [operation]
    assert result["response"]["operation"] == operation


@pytest.mark.parametrize("source_format", ["string", "lines"])
@pytest.mark.parametrize("operation", ["create", "edit", "repair", "check_repair"])
def test_codex_compact_operations_keep_wire_contract_and_isolation(codex_rpc, operation, source_format):
    from generation.schema import response_schema
    from tests.test_compact_generation import compact_response

    request = {"provider": "codex", "model": "gpt-6-luna", "operation": operation,
               "generation_profile": "compact", "source_format": source_format}
    example = compact_response()
    if operation == "create":
        reply = example
    elif operation == "repair":
        request['module_repair'] = {'files': {'game.js': 'a' * 64}}
        request['files'] = {'game.js': example['source']}
        reply = {'status': 'ok', 'message': 'Исправлен модуль.', 'source': example['source']}
    else:
        reply = {'status': 'ok', 'message': 'Исправление.',
                 'observations': example['observations'], 'probes': example['probes']}
        if operation == 'edit':
            reply['edits'] = [{'old_text': 'hits:0', 'new_text': 'hits:1'}]
    if source_format == 'lines' and 'source' in reply:
        reply['source_lines'] = reply.pop('source').split('\n')
    codex_rpc['events'][1]['params']['item']['text'] = json.dumps(reply)
    result = generate_operation(request, on_event=lambda _: None, is_cancelled=lambda: False)
    turns = [params for method, params in codex_rpc['calls'] if method == 'turn/start']
    assert len(turns) == 1
    assert turns[0]['outputSchema'] == response_schema(request)
    assert turns[0]['environments'] == [] and turns[0]['runtimeWorkspaceRoots'] == []
    assert result['response'] == reply and result['provider'] == 'codex'
    assert result['usage']['input_tokens'] == 100 and codex_rpc['closed']


@pytest.fixture
def api(monkeypatch):
    state = {"requests": [], "headers": [], "mode": "ok", "status": 200, "request_header": True}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"local-test-model"}]}')

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(payload)
            state["headers"].append(dict(self.headers))
            self.send_response(state["status"])
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("X-Proxy-Request-ID", "proxy-test-1")
            if state["mode"] == "broken_chunked":
                self.send_header("Transfer-Encoding", "chunked")
            if state["request_header"]:
                self.send_header("x-request-id", "request-test-1")
            self.end_headers()
            if state["status"] != 200:
                return
            if state["mode"] == "idle":
                time.sleep(0.5)
                return
            if state["mode"] == "bad_sse":
                self.wfile.write(b'data: {secret malformed provider response\n\n')
                return
            if state["mode"] == "broken_chunked":
                self.wfile.write(b'ff\r\ndata: {')
                self.wfile.flush()
                self.close_connection = True
                return
            text = json.dumps(fixture_response(), ensure_ascii=False)
            if state["mode"] == "invalid":
                text = "{incomplete"
            chunks = [
                {
                    "id": "chatcmpl-test-1",
                    "choices": [{"delta": {"content": text[:50]}, "finish_reason": None}],
                },
                {
                    "choices": [
                        {
                            "delta": {"content": text[50:]},
                            "finish_reason": "length" if state["mode"] == "length" else "stop",
                        }
                    ]
                },
            ]
            if state["mode"] == "partial":
                chunks = chunks[:1]
            if state["mode"] == "refusal":
                chunks = [{"choices": [{"delta": {"refusal": "no"}, "finish_reason": "stop"}]}]
            if state["mode"] not in {"partial", "no_usage"}:
                chunks.append(
                    {
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 50,
                            "prompt_tokens_details": {"cached_tokens": 40},
                        },
                    }
                )
            try:
                if not payload["stream"]:
                    self.wfile.write(
                        json.dumps(
                            {
                                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                            }
                        ).encode()
                    )
                else:
                    for chunk in chunks:
                        self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                        self.wfile.flush()
                    if state["mode"] == "usage_then_idle":
                        time.sleep(0.5)
                        return
                    if state["mode"] not in {"partial", "usage_then_eof"}:
                        self.wfile.write(b"data: [DONE]\n\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("GAMEFORGE_VLLM_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("GAMEFORGE_VLLM_API_KEY", "local-test-token")
    monkeypatch.setenv("GAMEFORGE_VLLM_JSON_MODE", "json_schema")
    monkeypatch.setenv("GAMEFORGE_VLLM_CONTEXT_CHECK", "conservative")
    monkeypatch.setenv("GAMEFORGE_VLLM_STREAM", "true")
    yield state
    server.shutdown()
    server.server_close()


def test_vllm_accepts_llm_env_aliases_and_explicit_settings_take_precedence(monkeypatch):
    for key in ("GAMEFORGE_VLLM_URL", "GAMEFORGE_VLLM_API_KEY", "GAMEFORGE_VLLM_CONNECT_TIMEOUT",
                "GAMEFORGE_VLLM_READ_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://proxy.example/v1/")
    monkeypatch.setenv("LLM_API_KEY", "example-token")
    config = vllm.configuration()
    assert config["url"] == "https://proxy.example/v1"
    assert config["key"] == "example-token"
    assert config["connect_timeout"] == 15
    assert config["read_timeout"] == 660
    monkeypatch.setenv("GAMEFORGE_VLLM_URL", "https://explicit.example/v1")
    monkeypatch.setenv("GAMEFORGE_VLLM_API_KEY", "explicit-token")
    monkeypatch.setenv("GAMEFORGE_VLLM_READ_TIMEOUT", "120")
    assert vllm.configuration()["url"] == "https://explicit.example/v1"
    assert vllm.configuration()["key"] == "explicit-token"
    assert vllm.configuration()["read_timeout"] == 120


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_vllm_rejects_invalid_inactivity_timeout(monkeypatch, value):
    monkeypatch.setenv("GAMEFORGE_VLLM_URL", "https://proxy.example/v1")
    monkeypatch.setenv("GAMEFORGE_VLLM_READ_TIMEOUT", value)
    with pytest.raises(GenerationError, match="Таймауты"):
        vllm.configuration()


def test_vllm_protocol_models_and_complete_stream(api):
    assert vllm.probe()["models"][0]["id"] == "local-test-model"
    events = []
    result = generate(
        {"provider": "vllm", "model": "local-test-model", "prompt": "Игра"},
        on_event=events.append,
        is_cancelled=lambda: False,
    )
    assert result["response"] == fixture_response()
    assert result["usage"] == {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 50}
    assert result["provider_metadata"]["request_id"] == "request-test-1"
    assert api["requests"][0]["response_format"]["json_schema"]["strict"]
    assert len(api["requests"]) == 1
    assert api["requests"][0]["max_tokens"] == 8000
    assert events[0]["type"] == "first_output"


@pytest.mark.parametrize(
    "mode,code,unknown",
    [
        ("partial", "incomplete_response", True),
        ("invalid", "invalid_json", False),
        ("length", "incomplete_response", False),
        ("refusal", "provider_refusal", False),
    ],
)
def test_vllm_partial_invalid_refusal_no_hidden_retry(api, mode, code, unknown):
    api["mode"] = mode
    with pytest.raises(GenerationError) as error:
        generate(
            {"provider": "vllm", "model": "local-test-model"},
            on_event=lambda _: None,
            is_cancelled=lambda: False,
        )
    assert error.value.code == code
    assert error.value.outcome_unknown is unknown
    assert error.value.provider_metadata["request_id"] == "request-test-1"
    assert len(api["requests"]) == 1


def test_vllm_missing_usage_remains_unknown(api):
    api["mode"] = "no_usage"
    result = generate(
        {"provider": "vllm", "model": "local-test-model"}, on_event=lambda _: None, is_cancelled=lambda: False
    )
    assert result["usage"] is None


def test_vllm_http_error_not_retried(api):
    api["status"] = 503
    with pytest.raises(GenerationError) as error:
        generate(
            {"provider": "vllm", "model": "local-test-model"},
            on_event=lambda _: None,
            is_cancelled=lambda: False,
        )
    assert error.value.outcome_unknown
    assert len(api["requests"]) == 1


def test_vllm_response_id_remains_available_without_request_header(api):
    api["request_header"] = False
    result = generate(
        {"provider": "vllm", "model": "local-test-model"}, on_event=lambda _: None, is_cancelled=lambda: False
    )
    assert result["provider_metadata"]["request_id"] == "chatcmpl-test-1"


def test_vllm_cancel_idle_stream_preserves_unknown(api):
    api["mode"] = "idle"
    started = time.monotonic()
    with pytest.raises(GenerationError) as error:
        generate(
            {"provider": "vllm", "model": "local-test-model"},
            on_event=lambda _: None,
            is_cancelled=lambda: time.monotonic() - started > 0.2,
        )
    assert error.value.code == "cancelled"
    assert error.value.outcome_unknown
    assert time.monotonic() - started < 2
    assert len(api["requests"]) == 1


@pytest.mark.parametrize("mode", ["usage_then_eof", "usage_then_idle"])
def test_vllm_usage_before_final_marker_does_not_release_unknown_liability(api, mode):
    api["mode"] = mode
    started = time.monotonic()
    with pytest.raises(GenerationError) as error:
        generate(
            {"provider": "vllm", "model": "local-test-model"},
            on_event=lambda _: None,
            is_cancelled=lambda: mode == "usage_then_idle" and time.monotonic() - started > 0.2,
        )
    assert error.value.code == ("cancelled" if mode == "usage_then_idle" else "incomplete_response")
    assert error.value.usage["input_tokens"] == 100
    assert error.value.outcome_unknown
    assert error.value.provider_metadata["request_id"] == "request-test-1"
    assert len(api["requests"]) == 1


def test_vllm_nonstream_capability(api, monkeypatch):
    monkeypatch.setenv("GAMEFORGE_VLLM_STREAM", "false")
    monkeypatch.setenv("GAMEFORGE_VLLM_JSON_MODE", "none")
    result = generate(
        {"provider": "vllm", "model": "local-test-model"}, on_event=lambda _: None, is_cancelled=lambda: False
    )
    assert result["response"]["status"] == "ok"
    assert "response_format" not in api["requests"][0]
    assert "Required JSON schema" in api["requests"][0]["messages"][0]["content"]


def test_vllm_correlates_actual_request_and_records_safe_timings(api):
    trace_id = "b" * 32
    result = generate(
        {"provider": "vllm", "model": "local-test-model", "transport_trace_id": trace_id},
        on_event=lambda _: None, is_cancelled=lambda: False,
    )
    metadata = result["provider_metadata"]
    assert api["headers"][0]["X-GameForge-Trace-ID"] == metadata["trace_id"] == trace_id
    diag = metadata["transport"]
    assert diag["proxy_request_id"] == "proxy-test-1"
    assert diag["provider_response_id"] == "chatcmpl-test-1"
    assert diag["request_bytes"] == int(api["headers"][0]["Content-Length"])
    assert diag["received_bytes"] > diag["output_bytes"] > 0
    assert diag["sse_events"] == 3
    assert diag["done_received"] and diag["http_status"] == 200
    assert 0 <= diag["first_byte_seconds"] <= diag["elapsed_seconds"]
    assert diag["http_events"] and len(diag["http_events"]) <= 32
    assert diag["outcome"] == "completed"
    assert "local-test-token" not in json.dumps(metadata)
    assert "messages" not in json.dumps(metadata)


@pytest.mark.parametrize("mode,exception,code", [
    ("idle", "ReadTimeout", "provider_disconnected"),
    ("bad_sse", "JSONDecodeError", "provider_protocol_error"),
    ("broken_chunked", "RemoteProtocolError", "provider_disconnected"),
])
def test_vllm_distinguishes_timeout_corrupt_frame_and_broken_http(api, monkeypatch, mode, exception, code):
    api["mode"] = mode
    monkeypatch.setenv("GAMEFORGE_VLLM_READ_TIMEOUT", "0.15")
    with pytest.raises(GenerationError) as error:
        generate({"provider": "vllm", "model": "local-test-model"},
                 on_event=lambda _: None, is_cancelled=lambda: False)
    metadata = error.value.provider_metadata
    assert error.value.code == code
    assert metadata["transport_error"] == exception
    assert metadata["transport"]["errors"][0]["type"] == exception
    assert metadata["transport"]["http_status"] == 200
    assert metadata["transport"]["done_received"] is False
    assert error.value.outcome_unknown
    assert len(api["requests"]) == 1
    assert "secret malformed" not in json.dumps(metadata)
    if mode == "idle":
        assert metadata["transport"]["idle_seconds"] >= 0.1
    if mode == "bad_sse":
        assert metadata["transport"]["error_phase"] == "decoding_sse"


def test_vllm_eof_and_cancellation_have_distinct_diagnostics(api):
    for mode, cancelled, expected in [("partial", False, "incomplete_response"),
                                      ("idle", True, "cancelled")]:
        api["mode"] = mode
        started = time.monotonic()
        with pytest.raises(GenerationError) as error:
            generate({"provider": "vllm", "model": "local-test-model"}, on_event=lambda _: None,
                     is_cancelled=lambda: cancelled and time.monotonic() - started > .1)
        diag = error.value.provider_metadata["transport"]
        assert diag["outcome"] == expected
        assert not diag["done_received"]
        if not cancelled:
            assert diag["eof_received"]


@pytest.fixture
def codex_rpc(monkeypatch):
    state = {"calls": [], "events": [], "closed": False}

    class Connection:
        def __init__(self, cwd):
            self.pending = []

        def rpc(self, method, params, is_cancelled):
            state["calls"].append((method, params))
            if method == "initialize":
                return {}
            if method == "config/read":
                return {"config": {"mcp_servers": {"private": {"command": "secret"}}}}
            if method == "thread/start":
                return {"thread": {"id": "thread-1"}, "model": params["model"]}
            raise AssertionError(method)

        def send(self, method, params, **kwargs):
            state["calls"].append((method, params))
            return 99

        def next(self, is_cancelled):
            if is_cancelled():
                raise GenerationError("cancelled", "Cancelled", outcome_unknown=True)
            if not state["events"]:
                raise GenerationError("codex_disconnected", "Disconnected", outcome_unknown=True)
            return state["events"].pop(0)

        def close(self):
            state["closed"] = True

    monkeypatch.setattr(codex, "Connection", Connection)
    monkeypatch.setattr(codex, "verify_cli_contract", lambda: "verified")
    monkeypatch.setattr(codex, "available_models", lambda: [{"id": "gpt-6-luna"}, {"id": "gpt-6-sol"}])
    state["events"] = [
        {"id": 99, "result": {"turn": {"id": "turn-1"}}},
        {
            "method": "item/completed",
            "params": {"item": {"type": "agentMessage", "text": json.dumps(fixture_response())}},
        },
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "tokenUsage": {
                    "total": {
                        "inputTokens": 100,
                        "cachedInputTokens": 40,
                        "outputTokens": 50,
                        "cacheWriteInputTokens": 5,
                    }
                }
            },
        },
        {"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}},
    ]
    return state


def test_codex_protocol_single_turn_environments_disabled_and_usage(codex_rpc):
    result = generate({"provider": "codex"}, on_event=lambda _: None, is_cancelled=lambda: False)
    calls = codex_rpc["calls"]
    assert sum(m == "turn/start" for m, _ in calls) == 1
    for method, params in calls:
        if method in {"thread/start", "turn/start"}:
            assert params["environments"] == [] and params["runtimeWorkspaceRoots"] == []
        if method == "thread/start":
            assert params["config"]["mcp_servers"] == {"private": {"enabled": False}}
            assert params["dynamicTools"] == [] and params["selectedCapabilityRoots"] == []
            assert params["developerInstructions"] == ""
    assert result["usage"]["cache_write_input_tokens"] == 5
    assert result["provider_metadata"]["thread_id"] == "thread-1"
    assert result["provider_metadata"]["turn_id"] == "turn-1"
    assert result["response"] == fixture_response()
    assert codex_rpc["closed"]


def test_codex_disconnect_preserves_text_unknown_and_no_repeat(codex_rpc):
    codex_rpc["events"] = codex_rpc["events"][:2]
    with pytest.raises(GenerationError) as error:
        generate({"provider": "codex"}, on_event=lambda _: None, is_cancelled=lambda: False)
    assert error.value.outcome_unknown
    assert "Тестовая" in json.loads(error.value.raw_response)["title"]
    assert error.value.provider_metadata["turn_id"] == "turn-1"
    assert sum(m == "turn/start" for m, _ in codex_rpc["calls"]) == 1
    assert codex_rpc["closed"]


def test_codex_interim_usage_does_not_resolve_disconnected_outcome(codex_rpc):
    codex_rpc["events"] = codex_rpc["events"][:-1]
    with pytest.raises(GenerationError) as error:
        generate({"provider": "codex"}, on_event=lambda _: None, is_cancelled=lambda: False)
    assert error.value.outcome_unknown
    assert error.value.usage["input_tokens"] == 100
    assert error.value.provider_metadata["turn_id"] == "turn-1"
    assert sum(m == "turn/start" for m, _ in codex_rpc["calls"]) == 1


@pytest.mark.parametrize("partial", [False, True])
def test_codex_failed_turn_preserves_unknown_and_reports_only_received_text(codex_rpc, partial):
    if not partial:
        codex_rpc["events"].pop(1)
    codex_rpc["events"][-1]["params"]["turn"] = {
        "id": "turn-1", "status": "failed", "error": {"message": "stream disconnected"}
    }
    with pytest.raises(GenerationError) as error:
        generate({"provider": "codex"}, on_event=lambda _: None, is_cancelled=lambda: False)
    assert error.value.outcome_unknown  # Even with interim tokenUsage/updated.
    assert error.value.usage["input_tokens"] == 100
    assert bool(error.value.raw_response["partial_response"]) is partial
    assert ("фрагмент сохранён" in error.value.message) is partial
    assert sum(m == "turn/start" for m, _ in codex_rpc["calls"]) == 1


def test_codex_unexpected_tool_is_rejected(codex_rpc):
    codex_rpc["events"].insert(
        1, {"method": "item/started", "params": {"item": {"type": "commandExecution"}}}
    )
    with pytest.raises(GenerationError) as error:
        generate({"provider": "codex"}, on_event=lambda _: None, is_cancelled=lambda: False)
    assert error.value.code == "unexpected_tool"
    assert codex_rpc["closed"]


def test_codex_schema_failure_keeps_provider_ids_and_usage(codex_rpc):
    codex_rpc["events"][1]["params"]["item"]["text"] = '{"wrong":"schema"}'
    with pytest.raises(GenerationError) as error:
        generate({"provider": "codex"}, on_event=lambda _: None, is_cancelled=lambda: False)
    assert error.value.code == "invalid_schema"
    assert error.value.provider_metadata["turn_id"] == "turn-1"
    assert error.value.usage["input_tokens"] == 100


def test_model_cannot_escalate_repair_to_edit_and_receipt_remains_accountable(codex_rpc):
    response = fixture_response()
    response.update(operation="edit", base_revision="base-1", files=[], checks=[])
    codex_rpc["events"][1]["params"]["item"]["text"] = json.dumps(response)
    with pytest.raises(GenerationError) as error:
        generate(
            {"provider": "codex", "operation": "repair"},
            on_event=lambda _: None,
            is_cancelled=lambda: False,
        )
    assert error.value.code == "operation_mismatch"
    assert error.value.usage["input_tokens"] == 100
    assert error.value.provider_metadata["turn_id"] == "turn-1"


def test_codex_profile_is_explicit_about_prompt_and_compaction(monkeypatch, tmp_path):
    monkeypatch.setattr(codex, "binary", lambda: "codex")
    args = codex.command(tmp_path / "catalog.json")
    config = {
        args[i + 1].split("=", 1)[0]: json.loads(args[i + 1].split("=", 1)[1])
        for i, part in enumerate(args)
        if part == "-c"
    }
    assert config["developer_instructions"] == ""
    assert config["features.async_compaction"] is False
    assert config["model_post_turn_compact_threshold_percent"] == 0
    assert config["model_context_window"] == 872000
    assert config["model_auto_compact_token_limit"] == 800000
    assert config["model_auto_compact_token_limit_scope"] == "total"


def test_codex_large_context_is_rejected_before_connection_without_truncating(codex_rpc):
    source = "const label='" + "И" * 140000 + "';"
    request = {"provider": "codex", "files": {"game.js": source}}
    with pytest.raises(GenerationError) as error:
        generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    assert error.value.code == "context_limit"
    assert not error.value.outcome_unknown
    assert codex_rpc["calls"] == []
    assert request["files"]["game.js"] == source


def test_codex_env_excludes_application_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("GAMEFORGE_VLLM_API_KEY", "secret")
    environment = codex.child_environment()
    assert not set(environment) & {"DATABASE_URL", "OPENAI_API_KEY", "GAMEFORGE_VLLM_API_KEY"}
    assert "HOME" in environment


def test_sanitized_catalog_removes_capabilities_without_copying_auth(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "models_cache.json").write_text(
        json.dumps(
            {
                "identity": "private account",
                "models": [
                    {
                        "slug": "test",
                        "shell_type": "unified_exec",
                        "apply_patch_tool_type": "freeform",
                        "experimental_supported_tools": ["clock"],
                    }
                ],
            }
        )
    )
    (home / "auth.json").write_text("PRIVATE_TOKEN")
    monkeypatch.setenv("CODEX_HOME", str(home))
    output = tmp_path / "output"
    output.mkdir()
    catalog = json.loads(codex.sanitized_catalog(output).read_text())
    assert "identity" not in catalog
    assert catalog["models"][0]["shell_type"] == "disabled"
    assert catalog["models"][0]["apply_patch_tool_type"] is None
    assert catalog["models"][0]["tool_mode"] == "direct"
    assert "PRIVATE_TOKEN" not in str(catalog)
    assert list(output.iterdir()) == [output / "models.json"]


def test_fake_is_explicitly_labelled_and_does_not_call_any_provider():
    result = generate({"provider": "fake"}, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result["model"] == "fixture"
    assert result["usage"]["input_tokens"] == 0
    assert "заглушка" in result["response"]["title"]


def test_reservation_covers_all_uncached_cachedwrite_and_output_limits():
    from decimal import Decimal

    from generation.service import estimate_reservation

    price = {"input": 0.10, "cached": 0.01, "cache_write": 0.125, "output": 0.50}
    assert estimate_reservation({"provider": "codex", "model": "gpt-6-luna"}, price) == Decimal(".314000")
    assert estimate_reservation({"provider": "fake"}, price) == 0
    with pytest.raises(GenerationError, match="пределы"):
        estimate_reservation({"provider": "vllm", "model": "unknown"}, price)
    assert estimate_reservation({"provider": "vllm"}, {"input": 0, "output": 0, "cached": 0}) == 0


def test_vllm_rejects_unbounded_or_overlarge_input_before_network(api):
    with pytest.raises(GenerationError) as error:
        generate_operation(
            {"provider": "vllm", "model": "local-test-model"},
            on_event=lambda _: None,
            is_cancelled=lambda: False,
        )
    assert error.value.code == "provider_limits_unknown"
    with pytest.raises(GenerationError) as error:
        generate_operation(
            {
                "provider": "vllm",
                "model": "local-test-model",
                "execution_limits": {"context_window": 9000, "max_output_tokens": 1000},
            },
            on_event=lambda _: None,
            is_cancelled=lambda: False,
        )
    assert error.value.code == "context_limit"
    assert api["requests"] == []


@pytest.mark.parametrize("mode", ["json_object", "json_schema", "none"])
def test_verified_server_context_allows_larger_output_without_changing_prompt(monkeypatch, mode):
    request = {
        "model": "local-test-model", "prompt": "Создай игру с русским текстом",
        "execution_limits": {"context_window": 32768, "max_output_tokens": 6144},
    }
    monkeypatch.setenv("GAMEFORGE_VLLM_CONTEXT_CHECK", "conservative")
    original = vllm.build_payload(request, json_mode=mode)
    request["execution_limits"]["max_output_tokens"] = 16384
    with pytest.raises(GenerationError) as error:
        vllm.build_payload(request, json_mode=mode)
    assert error.value.code == "context_limit"
    monkeypatch.setenv("GAMEFORGE_VLLM_CONTEXT_CHECK", "server")
    larger = vllm.build_payload(request, json_mode=mode)
    assert larger == {**original, "max_tokens": 16384}
    assert "truncate_prompt_tokens" not in larger


def test_server_context_still_requires_valid_limits_and_bounded_utf8_payload(monkeypatch):
    monkeypatch.setenv("GAMEFORGE_VLLM_CONTEXT_CHECK", "server")
    request = {"model": "local-test-model", "execution_limits": {
        "context_window": 32768, "max_output_tokens": 32768,
    }}
    with pytest.raises(GenerationError) as error:
        vllm.build_payload(request)
    assert error.value.code == "provider_limits_unknown"
    request["execution_limits"]["max_output_tokens"] = 16384
    request["prompt"] = "я" * 1_000_000
    with pytest.raises(GenerationError) as error:
        vllm.build_payload(request)
    assert error.value.code == "request_too_large"


def test_invalid_context_policy_fails_closed(monkeypatch):
    monkeypatch.setenv("GAMEFORGE_VLLM_CONTEXT_CHECK", "typo")
    with pytest.raises(GenerationError) as error:
        vllm.build_payload({"model": "local-test-model", "execution_limits": {
            "context_window": 32768, "max_output_tokens": 16384,
        }})
    assert error.value.code == "invalid_provider_config"


def test_server_context_rejection_is_terminal_without_retry(api, monkeypatch):
    monkeypatch.setenv("GAMEFORGE_VLLM_CONTEXT_CHECK", "server")
    api["status"] = 400
    with pytest.raises(GenerationError) as error:
        generate_operation({"provider": "vllm", "model": "local-test-model", "execution_limits": {
            "context_window": 32768, "max_output_tokens": 16384,
        }}, on_event=lambda _: None, is_cancelled=lambda: False)
    assert error.value.code == "provider_http_error"
    assert error.value.outcome_unknown is False
    assert len(api["requests"]) == 1
    assert api["requests"][0]["max_tokens"] == 16384



@pytest.mark.parametrize("multiplier", ["NaN", "Infinity", "-1", "0"])
def test_nonfinite_or_discounted_worst_case_multipliers_are_rejected(multiplier):
    from generation.service import estimate_reservation

    with pytest.raises(GenerationError):
        estimate_reservation(
            {"provider": "vllm"},
            {
                "input": 1,
                "cached": 1,
                "output": 1,
                "context_window": 64000,
                "max_output_tokens": 8000,
                "max_input_multiplier": multiplier,
            },
        )


def test_pro_planning_effort_and_schema_use_one_isolated_codex_turn(codex_rpc):
    from generation.providers.fake import generate as fake_generate

    request = {'provider': 'codex', 'model': 'gpt-6-sol', 'generation_strategy': 'pro',
               'operation': 'plan', 'reasoning_effort': 'high', 'presentation_policy': 1}
    reply = fake_generate(request, on_event=lambda _: None, is_cancelled=lambda: False)['response']
    codex_rpc['events'][1]['params']['item']['text'] = json.dumps(reply)
    result = generate_operation(request, on_event=lambda _: None, is_cancelled=lambda: False)
    turns = [p for m, p in codex_rpc['calls'] if m == 'turn/start']
    assert len(turns) == 1
    assert turns[0]['effort'] == 'high' and turns[0]['model'] == 'gpt-6-sol'
    assert turns[0]['environments'] == turns[0]['runtimeWorkspaceRoots'] == []
    assert turns[0]['outputSchema']['properties']['operation']['enum'] == ['plan']
    assert result['provider_metadata']['request_profile']['reasoning_effort'] == 'high'
    assert result['provider_metadata']['request_profile']['presentation_policy'] == 1
    assert 'presentation' in turns[0]['outputSchema']['properties']['plan']['anyOf'][0]['required']
    assert result['response'] == reply


def test_pro_receives_validator_frame_as_data_image_not_path_or_tool(codex_rpc):
    from tests.test_generation_planning import screenshot_request

    request = {**screenshot_request(), 'provider': 'codex', 'model': 'gpt-6-sol',
               'operation': 'repair', 'reasoning_effort': 'high'}
    reply = fixture_response()
    reply.update(operation='repair', base_revision='revision', files=[], checks=[])
    codex_rpc['events'][1]['params']['item']['text'] = json.dumps(reply)
    generate_operation(request, on_event=lambda _: None, is_cancelled=lambda: False)
    turn = next(p for m, p in codex_rpc['calls'] if m == 'turn/start')
    assert len(turn['input']) == 2 and turn['input'][1]['type'] == 'image'
    assert turn['input'][1]['url'].startswith('data:image/png;base64,')
    assert 'preview_image' not in json.loads(turn['input'][0]['text'])
    thread = next(p for m, p in codex_rpc['calls'] if m == 'thread/start')
    assert thread['dynamicTools'] == thread['selectedCapabilityRoots'] == []
    assert thread['config']['mcp_servers'] == {'private': {'enabled': False}}


@pytest.mark.parametrize('operation', ['visual_review', 'visual_patch'])
def test_codex_visual_operations_keep_image_schema_and_disabled_tools(codex_rpc, operation):
    from tests.test_visual_review import review, visual_request

    request = {**visual_request(operation), 'provider':'codex', 'model':'gpt-6-sol'}
    reply = review(request[operation])
    if operation == 'visual_patch':
        reply.pop('issues')
        reply.update(operation=operation, status='unchanged', patches=[])
    codex_rpc['events'][1]['params']['item']['text'] = json.dumps(reply)
    result = generate_operation(request, on_event=lambda _:None, is_cancelled=lambda:False)
    turn = next(p for m,p in codex_rpc['calls'] if m == 'turn/start')
    thread = next(p for m,p in codex_rpc['calls'] if m == 'thread/start')
    assert turn['outputSchema']['properties']['operation']['enum'] == [operation]
    assert len(turn['input']) == 2 and turn['input'][1]['url'].startswith('data:image/jpeg;base64,')
    assert turn['effort'] == 'medium' and not turn['environments'] and not turn['runtimeWorkspaceRoots']
    assert not thread['dynamicTools'] and not thread['selectedCapabilityRoots']
    assert 'preview_image' not in json.loads(turn['input'][0]['text'])
    assert result['response'] == reply
