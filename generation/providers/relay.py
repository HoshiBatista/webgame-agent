"""Short, repeatable queue operations; model execution is owned by the GPU executor."""

import json
import os

import httpx

from ..errors import GenerationError, GenerationPending
from ..relay_api.client import Client, RelayHTTPError
from ..relay_api.protocol import Problem, digest, secret, secure_url, validate_receipt
from .vllm import build_payload, normalize_usage


def configuration():
    try:
        url = secure_url(os.environ.get("GAMEFORGE_RELAY_URL", ""))
        token = secret("GAMEFORGE_RELAY_API_KEY")
        if len(token) < 32:
            raise ValueError
        return url, token
    except (ValueError, OSError) as exc:
        raise GenerationError(
            "relay_not_configured", "Администратор ещё не настроил очередь модели."
        ) from exc


def prepare(request, ident):
    url, _ = configuration()
    return {
        "id": ident,
        "url": url,
        "payload": build_payload(
            request, json_mode=os.environ.get("GAMEFORGE_VLLM_JSON_MODE", "json_object"), stream=True
        ),
    }


def fetch(request, *, cancel=False):
    saved = request.get("relay")
    if not saved:
        raise GenerationError("relay_identity_missing", "Отсутствует сохранённый идентификатор задания.")
    try:
        url, token = configuration()
    except GenerationError as exc:
        raise GenerationPending(exc.message, code=exc.code, operator_required=True, retry_after=300) from exc
    if url != saved["url"]:
        raise GenerationPending("Адрес очереди изменён. Для получения ответа нужен прежний сервер.",
                                code="relay_address_changed", operator_required=True, retry_after=300)
    client = Client(url, token)
    path = f"/jobs/{saved['id']}"
    try:
        if cancel:
            return client.call("POST", path + "/cancel", {})
        try:
            return client.call("GET", path)
        except RelayHTTPError as exc:
            if exc.status != 404:
                raise
        return client.call("PUT", path, {"payload": saved["payload"]})
    except RelayHTTPError as exc:
        blocked = {
            401: ("relay_unauthorized", "Требуется администратор: ключ очереди недействителен или отозван."),
            403: ("relay_forbidden", "Требуется администратор: ключ не даёт доступа к заданиям."),
            507: ("relay_storage_full", "Требуется администратор: хранилище очереди заполнено."),
        }
        if exc.status in blocked:
            code, message = blocked[exc.status]
            raise GenerationPending(message + " Задание сохранено; после исправления продолжим его.",
                                    code=code, operator_required=True, retry_after=300,
                                    metadata={"http_status": exc.status}) from exc
        if exc.status in {400, 409, 413, 415}:
            # An incompatible request must not cause a fresh inference with another ID.
            raise GenerationError(
                "relay_request_conflict",
                "Очередь отклонила сохранённое задание.",
                outcome_unknown=True,
                provider_metadata={"relay_job_id": saved["id"]},
            ) from exc
        if 400 <= exc.status < 500 and exc.status not in {408, 429}:
            raise GenerationPending("Требуется администратор: проверьте адрес и совместимость очереди. "
                                    "Сохранённое задание не будет запущено повторно.",
                                    code="relay_configuration_error", operator_required=True, retry_after=300,
                                    metadata={"http_status": exc.status}) from exc
        if exc.status == 429:
            raise GenerationPending("Очередь занята. Ожидаем свободное место для сохранённого задания.",
                                    code="relay_queue_full", retry_after=30,
                                    metadata={"http_status": 429}) from exc
        raise GenerationPending("Очередь временно недоступна. Задание сохранено, ожидаем связь.",
                                code="relay_http_error", metadata={"http_status": exc.status}) from exc
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise GenerationPending("Связь с очередью прервана. Продолжим получение того же ответа.") from exc
    finally:
        client.close()


def unpack(status, ident):
    receipt = status.get("receipt")
    if receipt is None:
        raise GenerationPending(
            "Модель выполняет сохранённое задание."
            if status.get("state") == "running"
            else "Задание сохранено в очереди. Ожидаем исполнителя."
        )
    try:
        validate_receipt(receipt)
        if digest(receipt) != status.get("receipt_hash"):
            raise ValueError
    except (Problem, ValueError) as exc:
        raise GenerationPending(
            "Ответ получен не полностью. Повторим получение сохранённого результата."
        ) from exc
    if receipt["ok"]:
        result = dict(receipt["result"])
        return decode_completion(
            result["response"],
            {**(result.get("provider_metadata") or {}), "relay_job_id": ident},
        )
    error = receipt["error"]
    raise GenerationError(
        error["code"],
        error.get("message", "Ошибка исполнителя."),
        usage=normalize_usage(error.get("usage")),
        outcome_unknown=error["outcome_unknown"],
        raw_response=error.get("raw_response"),
        provider_metadata={**(error.get("provider_metadata") or {}), "relay_job_id": ident},
    )


def decode_completion(completion, metadata):
    """Game-specific interpretation belongs here, never in either transport service."""
    usage = normalize_usage(completion.get("usage"))
    choices = completion.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise GenerationError(
            "invalid_provider_response",
            "Некорректный ответ API модели.",
            usage=usage,
            outcome_unknown=usage is None,
            provider_metadata=metadata,
        )
    choice = choices[0]
    message = choice.get("message") or {}
    if not isinstance(message, dict):
        message = {}
    content = message.get("content")
    details = {"usage": usage, "raw_response": content, "provider_metadata": metadata}
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        raise GenerationError(
            "provider_refusal",
            "Модель отказалась выполнять запрос.",
            outcome_unknown=usage is None,
            **details,
        )
    if choice.get("finish_reason") != "stop":
        raise GenerationError(
            "incomplete_response", "Модель не завершила ответ.", outcome_unknown=usage is None, **details
        )
    try:
        if not isinstance(content, str):
            raise ValueError
        response = json.loads(content)
        if not isinstance(response, dict):
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise GenerationError("invalid_json", "Модель вернула неверный JSON игры.", **details) from exc
    return {
        "response": response,
        "usage": usage,
        "raw_response": content,
        "model": completion.get("model"),
        "provider_metadata": metadata,
    }


def generate(request, *, on_event, is_cancelled):
    if is_cancelled():
        # Lease loss is not user cancellation. The cancellation outbox handles explicit stops.
        raise GenerationPending("Ожидание передано следующему обработчику.")
    status = fetch(request)
    # Poll arrival time is not time-to-first-token. Actual GPU timing arrives in the receipt.
    return unpack(status, request["relay"]["id"])
