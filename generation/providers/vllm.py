"""OpenAI-compatible Chat Completions transport, configured only by the operator."""

import json
import math
import os
import queue
import threading
import time
from typing import Any

import httpx

from ..errors import GenerationError
from ..transport_diagnostics import ObservedStream, TransportDiagnostics, error_facts, safe_id

MAX_REQUEST_BYTES = 2_000_000  # Same bounded text request as relay protocol v1.


def normalize_usage(raw):
    if not isinstance(raw, dict):
        return None
    incoming = raw.get("prompt_tokens", raw.get("input_tokens"))
    outgoing = raw.get("completion_tokens", raw.get("output_tokens"))
    if not isinstance(incoming, int) or not isinstance(outgoing, int) or min(incoming, outgoing) < 0:
        return None
    details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", raw.get("cached_input_tokens", 0))
    if not isinstance(cached, int) or not 0 <= cached <= incoming:
        return None
    return {"input_tokens": incoming, "cached_input_tokens": cached, "output_tokens": outgoing}


def configuration():
    url = (os.environ.get("GAMEFORGE_VLLM_URL") or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise GenerationError(
            "provider_not_configured", "Администратор ещё не настроил API локальной модели."
        )
    try:
        connect_timeout = float(os.environ.get("GAMEFORGE_VLLM_CONNECT_TIMEOUT", "15"))
        read_timeout = float(os.environ.get("GAMEFORGE_VLLM_READ_TIMEOUT", "660"))
        if not all(math.isfinite(value) and value > 0 for value in (connect_timeout, read_timeout)):
            raise ValueError
    except ValueError as exc:
        raise GenerationError("invalid_provider_config", "Таймауты API должны быть положительными числами.") from exc
    return {
        "url": url,
        "key": os.environ.get("GAMEFORGE_VLLM_API_KEY") or os.environ.get("LLM_API_KEY", ""),
        "json_mode": os.environ.get("GAMEFORGE_VLLM_JSON_MODE", "json_object"),
        "stream": os.environ.get("GAMEFORGE_VLLM_STREAM", "true").lower() == "true",
        "connect_timeout": connect_timeout,
        "read_timeout": read_timeout,
    }


def probe():
    """Read-only model discovery. Protocol features still require an explicit smoke test."""
    config = configuration()
    headers = {"Authorization": "Bearer " + config["key"]} if config["key"] else {}
    try:
        with httpx.Client(timeout=10, trust_env=False) as client:
            response = client.get(config["url"] + "/models", headers=headers)
            response.raise_for_status()
            models = [
                {"id": item["id"], "name": item["id"]}
                for item in response.json().get("data", [])
                if isinstance(item.get("id"), str)
            ]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise GenerationError(
            "provider_unavailable", "API локальной модели не ответил на проверку моделей."
        ) from exc
    return {
        "models": models,
        "json_mode": config["json_mode"],
        "stream": config["stream"],
        "live_generation_tested": False,
    }


def generate(request, *, on_event, is_cancelled):
    if is_cancelled():
        raise GenerationError("cancelled", "Запуск отменён до отправки.", outcome_unknown=False)
    config = configuration()
    payload = build_payload(request, json_mode=config["json_mode"], stream=config["stream"])
    return complete(payload, config=config, on_event=on_event, is_cancelled=is_cancelled,
                    trace_id=request.get("transport_trace_id"))


def build_payload(request, *, json_mode="json_object", stream=True):
    """Freeze the exact model request before durable relay admission."""
    from ..prompts import build_messages, schema_prompt
    from ..schema import response_schema

    model = request.get("model") or os.environ.get("GAMEFORGE_VLLM_MODEL") or os.environ.get("LLM_MODEL")
    if not model:
        raise GenerationError("model_not_configured", "Выберите модель локального API в настройках сервера.")
    messages = build_messages(request)
    mode = json_mode
    limits = request.get("execution_limits") or {}
    context_window = limits.get("context_window")
    max_output = limits.get("max_output_tokens")
    if type(context_window) is not int or type(max_output) is not int or not 0 < max_output < context_window:
        raise GenerationError(
            "provider_limits_unknown", "Нужны проверенные пределы контекста и ответа локальной модели."
        )
    payload = {"model": model, "messages": messages, "stream": stream, "max_tokens": max_output}
    if mode == "json_schema":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "mini_game", "strict": True, "schema": response_schema(request)},
        }
    elif mode == "json_object":
        payload["response_format"] = {"type": "json_object"}
        messages[0]["content"] += "\nRequired JSON schema: " + schema_prompt(request)
    elif mode == "none":
        messages[0]["content"] += "\nRequired JSON schema: " + schema_prompt(request)
    else:
        raise GenerationError("invalid_provider_config", "Неизвестный формат ответа локальной модели.")
    context_check = os.environ.get("GAMEFORGE_VLLM_CONTEXT_CHECK", "conservative")
    if context_check not in {"conservative", "server"}:
        raise GenerationError("invalid_provider_config", "Неизвестный режим проверки контекста модели.")
    if stream:
        payload["stream_options"] = {"include_usage": True}
    if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise GenerationError("request_too_large", "Запрос превышает допустимый размер передачи модели.")
    # A UTF-8 upper bound is deliberately conservative, NOT an actual token count.
    # With an operator-verified vLLM, its tokenizer can enforce the real context
    # instead. vLLM may cap output to the remaining context; length is still an
    # incomplete response. Never truncate input or change a saved relay payload.
    input_bound = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 8192
    if mode == "json_schema":
        input_bound += len(schema_prompt(request).encode("utf-8"))
    if context_check == "conservative" and input_bound + max_output > context_window:
        raise GenerationError(
            "context_limit", "Текущий код не помещается в настроенный контекст локальной модели."
        )
    return payload


def complete(payload, *, config, on_event, is_cancelled, trace_id=None):
    """One local model call. No retries, independent of Django and relay connectivity."""
    if is_cancelled():
        raise GenerationError("cancelled", "Запуск отменён до отправки.", outcome_unknown=False)
    model = payload["model"]
    streaming = payload.get("stream", False)
    headers = {"Authorization": "Bearer " + config["key"]} if config["key"] else {}
    # Encode once so request_bytes is the actual HTTP payload size, not a token estimate.
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    diagnostics = TransportDiagnostics(trace_id=trace_id, config=config, request_bytes=len(body),
                                       streaming=streaming)
    headers.update({"Content-Type": "application/json",
                    "X-GameForge-Trace-ID": diagnostics.data["trace_id"],
                    "X-Request-ID": diagnostics.data["trace_id"]})
    events: queue.Queue[tuple[str, Any]] = queue.Queue()
    response_holder = []
    provider_metadata = {"trace_id": diagnostics.data["trace_id"]}
    stop = threading.Event()
    # This is a network inactivity guard, not a deadline for a progressing generation.
    client = httpx.Client(
        timeout=httpx.Timeout(connect=config["connect_timeout"], read=config["read_timeout"], write=30, pool=10),
        trust_env=False,
    )

    def receive():
        try:
            diagnostics.update(phase="waiting_headers")
            with client.stream(
                "POST", config["url"] + "/chat/completions", content=body, headers=headers,
                extensions={"trace": diagnostics.trace},
            ) as response:
                response_holder.append(response)
                diagnostics.update(phase="reading_body", http_status=response.status_code,
                                   http_version=response.http_version,
                                   headers_seconds=round(time.monotonic() - diagnostics.started, 3),
                                   proxy_request_id=safe_id(response.headers.get("x-proxy-request-id")))
                if request_id := safe_id(response.headers.get("x-request-id")):
                    provider_metadata["request_id"] = request_id
                diagnostics.report("headers", force=True)
                response.stream = ObservedStream(response.stream, diagnostics)
                if response.status_code >= 400:
                    events.put(("http_error", response.status_code))
                    return
                if streaming:
                    for line in response.iter_lines():
                        if stop.is_set():
                            return
                        if line.startswith("data:"):
                            data = line[5:].strip()
                            if data == "[DONE]":
                                diagnostics.update(done_received=True)
                                events.put(("done", None))
                                return
                            if data:
                                diagnostics.update(phase="decoding_sse")
                                diagnostics.sse_event()
                                events.put(("chunk", json.loads(data)))
                                diagnostics.update(phase="reading_body")
                else:
                    response_body = response.read()
                    diagnostics.update(phase="decoding_response")
                    events.put(("response", json.loads(response_body)))
                diagnostics.update(eof_received=True)
                events.put(("eof", None))
        except (httpx.HTTPError, ValueError, OSError) as exc:
            diagnostics.update(errors=error_facts(exc), error_phase=diagnostics.snapshot()["phase"])
            events.put(("error", type(exc).__name__))
        finally:
            client.close()

    diagnostics.report("started", force=True)
    threading.Thread(target=receive, daemon=True, name="gameforge-vllm-stream").start()
    text = ""
    usage = None
    finish = None
    first = True
    refusal = False
    completed = False
    try:
        while True:
            diagnostics.report("progress")
            if is_cancelled():
                raise GenerationError(
                    "cancelled",
                    "Запрос остановлен пользователем; неизвестный расход сохранён.",
                    usage=usage,
                    outcome_unknown=True,
                    raw_response=text or None,
                )
            try:
                kind, value = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if kind == "http_error":
                # HTTP rejection before a response is a known non-result; no blind retry.
                raise GenerationError(
                    "provider_http_error",
                    f"API модели отклонил запрос (HTTP {value}).",
                    outcome_unknown=value >= 500,
                )
            if kind == "error":
                provider_metadata["transport_error"] = value
                decode_error = diagnostics.snapshot().get("error_phase") in {"decoding_sse", "decoding_response"}
                raise GenerationError(
                    "provider_protocol_error" if decode_error else "provider_disconnected",
                    "API модели вернул повреждённый поток; автоматический повтор не выполняется."
                    if decode_error else "Соединение с моделью прервано; автоматический повтор не выполняется.",
                    usage=usage,
                    outcome_unknown=True,
                    raw_response=text or None,
                )
            if kind in {"done", "eof"}:
                completed = kind == "done" or not streaming
                break
            if first:
                diagnostics.update(first_event_seconds=round(time.monotonic() - diagnostics.started, 3))
                on_event({"type": "first_output", "message": "Модель начала отвечать."})
                first = False
            usage = normalize_usage(value.get("usage")) or usage
            if safe_id(value.get("id")):
                provider_metadata.setdefault("request_id", value["id"])
                diagnostics.update(provider_response_id=value["id"])
            for choice in value.get("choices", []):
                delta = choice.get("delta", {}) if kind == "chunk" else choice.get("message", {})
                if delta.get("refusal"):
                    refusal = True
                content = delta.get("content")
                if content:
                    text += content
                    diagnostics.update(output_bytes=len(text.encode()))
                finish = choice.get("finish_reason") or finish
                if len(text.encode()) > 2000000:
                    raise GenerationError(
                        "response_too_large",
                        "Ответ превышает формат мини-игры.",
                        usage=usage,
                        outcome_unknown=True,
                    )
        if not completed:
            raise GenerationError(
                "incomplete_response",
                "Поток прерван до подтверждения завершения; промежуточный расход требует сверки.",
                usage=usage,
                outcome_unknown=True,
                raw_response=text or None,
            )
        if refusal or finish == "content_filter":
            raise GenerationError(
                "provider_refusal",
                "Модель отказалась выполнять запрос.",
                usage=usage,
                outcome_unknown=usage is None,
                raw_response=text or None,
            )
        if finish != "stop":
            raise GenerationError(
                "incomplete_response",
                "Модель не завершила ответ; сохранён доступный фрагмент.",
                usage=usage,
                outcome_unknown=usage is None,
                raw_response=text or None,
            )
        try:
            diagnostics.update(phase="parsing_result", finish_reason=finish)
            response = json.loads(text)
        except ValueError as exc:
            raise GenerationError(
                "invalid_json",
                "Модель вернула незавершённый или неверный JSON.",
                usage=usage,
                raw_response=text,
            ) from exc
        provider_metadata["transport"] = diagnostics.finish("completed")
        return {
            "response": response,
            "usage": usage,
            "model": model,
            "raw_response": text,
            "provider_metadata": provider_metadata,
        }
    except GenerationError as exc:
        provider_metadata["transport"] = diagnostics.finish(exc.code)
        exc.provider_metadata = provider_metadata
        raise
    except Exception as exc:
        diagnostics.update(errors=error_facts(exc))
        provider_metadata["transport"] = diagnostics.finish("unexpected_client_error")
        raise GenerationError("provider_client_error", "Ошибка обработки ответа API; повтор не выполняется.",
                              usage=usage, outcome_unknown=True, raw_response=text or None,
                              provider_metadata=provider_metadata) from exc
    finally:
        stop.set()
        # Closing the transport interrupts an idle read. No joined model deadline.
        if response_holder:
            response_holder[0].close()
