"""OpenAI-compatible Chat Completions transport, configured only by the operator."""

import json
import os
import queue
import threading
from typing import Any

import httpx

from ..errors import GenerationError
from ..prompts import build_messages, schema_prompt
from ..schema import RESPONSE_SCHEMA


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
    url = os.environ.get("GAMEFORGE_VLLM_URL", "").rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise GenerationError(
            "provider_not_configured", "Администратор ещё не настроил API локальной модели."
        )
    return {
        "url": url,
        "key": os.environ.get("GAMEFORGE_VLLM_API_KEY", ""),
        "json_mode": os.environ.get("GAMEFORGE_VLLM_JSON_MODE", "json_object"),
        "stream": os.environ.get("GAMEFORGE_VLLM_STREAM", "true").lower() == "true",
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
    model = request.get("model") or os.environ.get("GAMEFORGE_VLLM_MODEL")
    if not model:
        raise GenerationError("model_not_configured", "Выберите модель локального API в настройках сервера.")
    messages = build_messages(request)
    mode = config["json_mode"]
    limits = request.get("execution_limits") or {}
    context_window = limits.get("context_window")
    max_output = limits.get("max_output_tokens")
    if type(context_window) is not int or type(max_output) is not int or not 0 < max_output < context_window:
        raise GenerationError(
            "provider_limits_unknown", "Нужны проверенные пределы контекста и ответа локальной модели."
        )
    payload = {"model": model, "messages": messages, "stream": config["stream"], "max_tokens": max_output}
    if mode == "json_schema":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "mini_game", "strict": True, "schema": RESPONSE_SCHEMA},
        }
    elif mode == "json_object":
        payload["response_format"] = {"type": "json_object"}
        messages[0]["content"] += "\nRequired JSON schema: " + schema_prompt()
    elif mode == "none":
        messages[0]["content"] += "\nRequired JSON schema: " + schema_prompt()
    else:
        raise GenerationError("invalid_provider_config", "Неизвестный формат ответа локальной модели.")
    # UTF-8 bytes bound tokenizer input conservatively, with explicit headroom
    # for the server's chat template; no tokenizer guess based on characters/4.
    input_bound = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 8192
    if mode == "json_schema":
        input_bound += len(schema_prompt().encode("utf-8"))
    if input_bound + max_output > context_window:
        raise GenerationError(
            "context_limit", "Текущий код не помещается в настроенный контекст локальной модели."
        )
    if config["stream"]:
        payload["stream_options"] = {"include_usage": True}
    headers = {"Authorization": "Bearer " + config["key"]} if config["key"] else {}
    events: queue.Queue[tuple[str, Any]] = queue.Queue()
    response_holder = []
    provider_metadata = {}
    stop = threading.Event()
    # This is a network inactivity guard, not a deadline for a progressing generation.
    client = httpx.Client(timeout=httpx.Timeout(connect=10, read=60, write=30, pool=10), trust_env=False)

    def receive():
        try:
            with client.stream(
                "POST", config["url"] + "/chat/completions", json=payload, headers=headers
            ) as response:
                response_holder.append(response)
                if request_id := response.headers.get("x-request-id"):
                    provider_metadata["request_id"] = request_id
                if response.status_code >= 400:
                    events.put(("http_error", response.status_code))
                    return
                if config["stream"]:
                    for line in response.iter_lines():
                        if stop.is_set():
                            return
                        if line.startswith("data:"):
                            data = line[5:].strip()
                            if data == "[DONE]":
                                events.put(("done", None))
                                return
                            if data:
                                events.put(("chunk", json.loads(data)))
                else:
                    events.put(("response", json.loads(response.read())))
                events.put(("eof", None))
        except (httpx.HTTPError, ValueError, OSError) as exc:
            events.put(("error", type(exc).__name__))
        finally:
            client.close()

    threading.Thread(target=receive, daemon=True, name="gameforge-vllm-stream").start()
    text = ""
    usage = None
    finish = None
    first = True
    refusal = False
    completed = False
    try:
        while True:
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
                raise GenerationError(
                    "provider_disconnected",
                    "Соединение с моделью прервано; автоматический повтор не выполняется.",
                    usage=usage,
                    outcome_unknown=True,
                    raw_response=text or None,
                )
            if kind in {"done", "eof"}:
                completed = kind == "done" or not config["stream"]
                break
            if first:
                on_event({"type": "first_output", "message": "Модель начала отвечать."})
                first = False
            usage = normalize_usage(value.get("usage")) or usage
            if isinstance(value.get("id"), str) and value["id"]:
                provider_metadata.setdefault("request_id", value["id"])
            for choice in value.get("choices", []):
                delta = choice.get("delta", {}) if kind == "chunk" else choice.get("message", {})
                if delta.get("refusal"):
                    refusal = True
                content = delta.get("content")
                if content:
                    text += content
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
            response = json.loads(text)
        except ValueError as exc:
            raise GenerationError(
                "invalid_json",
                "Модель вернула незавершённый или неверный JSON.",
                usage=usage,
                raw_response=text,
            ) from exc
        return {
            "response": response,
            "usage": usage,
            "model": model,
            "raw_response": text,
            "provider_metadata": provider_metadata,
        }
    except GenerationError as exc:
        exc.provider_metadata = provider_metadata
        raise
    finally:
        stop.set()
        # Closing the transport interrupts an idle read. No joined model deadline.
        if response_holder:
            response_holder[0].close()
