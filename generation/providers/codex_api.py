"""Codex Worker HTTP v1 adapter. Independent wire client, no sibling imports.

The remote service owns inference. Persist its UUID, exact body, origin and client
fingerprint before PUT; retries only deliver/poll that same durable job.
"""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from ..errors import GenerationError, GenerationPending
from ..feedback_image import image_input
from ..prompts import build_messages
from ..relay_api.protocol import digest, encoded, secret, secure_url
from ..schema import response_schema

TERMINAL = {"completed", "failed", "cancelled", "unknown"}
CATALOG_TTL = 180


class APIError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Codex worker HTTP {status}")


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    encoded(value).encode()  # Reject non-finite numbers and lone Unicode surrogates.
    return value


def origin():
    url = secure_url(os.environ.get("GAMEFORGE_CODEX_API_URL", ""))
    if urlsplit(url).path:
        raise ValueError("An origin without a path is required")
    return url


def configuration():
    try:
        url, token = origin(), secret("GAMEFORGE_CODEX_API_KEY")
        if not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError()
        return url, token
    except (ValueError, OSError) as exc:
        raise GenerationError("codex_api_not_configured", "Администратору нужно настроить подключение Pro API.") from exc


class Client:
    def __init__(self, url, token, *, transport=None):
        self.url = url
        self.http = httpx.Client(headers={"Authorization": "Bearer " + token},
                                 timeout=httpx.Timeout(30, connect=10), trust_env=False,
                                 follow_redirects=False, transport=transport)

    def close(self):
        self.http.close()

    def call(self, method, path, body=None):
        with self.http.stream(method, self.url + "/codex/v1" + path,
                              content=encoded(body).encode() if body is not None else None,
                              headers={"Content-Type": "application/json"}) as response:
            if response.status_code != 200:
                raise APIError(response.status_code)
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 16_000_000:
                    raise ValueError("response_too_large")
            result = parse(data)
            if not isinstance(result, dict):
                raise ValueError("invalid_response")
            return result


def prepare(request, ident):
    url, token = configuration()
    messages = build_messages(request)
    payload = {"model": request["model"], "effort": request.get("reasoning_effort", "low"),
               "instructions": messages[0]["content"], "input": messages[1]["content"],
               "output_schema": response_schema(request)}
    if len(encoded(payload).encode()) > 256_000:
        raise GenerationError("context_too_large", "Контекст Pro слишком велик; исходники не обрезались.")
    frame = image_input(request)
    if frame:
        mime, data = frame["url"][5:].split(";base64,", 1)
        payload["images"] = [{"mime": mime, "data": data}]
    return {"id": ident, "url": url, "payload": payload,
            "client_fingerprint": hashlib.sha256(token.encode()).hexdigest()}


def pending(code, message, *, operator=False, status=None):
    return GenerationPending(message, code=code, operator_required=operator,
                             retry_after=300 if operator else 5,
                             metadata={"http_status": status} if status is not None else {})


def checked_status(status, saved):
    if status.get("id") != saved["id"] or status.get("state") not in TERMINAL | {"queued", "preparing", "running"}:
        raise ValueError("job_identity_mismatch")
    tombstone = status.get("state") == "cancelled" and status.get("inference_submitted") is False
    if status.get("payload_hash") != digest(saved["payload"]) and not (tombstone and status.get("payload_hash") is None):
        raise ValueError("payload_identity_mismatch")
    return status


def fetch(request, *, cancel=False):
    saved = request.get("codex_api")
    try:
        if not isinstance(saved, dict) or str(UUID(saved["id"])) != saved["id"]:
            raise ValueError()
        for key in ("url", "payload", "client_fingerprint"):
            saved[key]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise pending("codex_api_identity_missing", "Нужно проверить сохранённое задание Pro API.", operator=True) from exc
    try:
        url, token = configuration()
    except GenerationError as exc:
        raise pending(exc.code, exc.message, operator=True) from exc
    if url != saved["url"] or hashlib.sha256(token.encode()).hexdigest() != saved["client_fingerprint"]:
        raise pending("codex_api_identity_changed", "Подключение Pro изменилось. Для получения сохранённого ответа "
                      "администратору нужно восстановить прежний адрес и клиентский ключ.", operator=True)
    client = Client(url, token)
    path = "/jobs/" + saved["id"]
    try:
        if cancel:
            status = client.call("POST", path + "/cancel", {})
        else:
            try:
                status = client.call("GET", path)
            except APIError as exc:
                if exc.status != 404:
                    raise
                status = client.call("PUT", path, {"payload": saved["payload"]})
        checked_status(status, saved)
        if status["state"] in TERMINAL:
            result = checked_status(client.call("GET", path + "/result"), saved)
            if result["state"] != status["state"] or result.get("receipt_hash") != status.get("receipt_hash"):
                raise ValueError("receipt_changed")
            if result.get("receipt", {}).get("ok") is True and result["receipt"].get("model") != saved["payload"]["model"]:
                raise ValueError("model_changed")
            return result
        return status
    except APIError as exc:
        if exc.status == 507:
            raise pending("codex_api_storage_full", "На сервере Pro закончилось место. Нужен администратор.",
                          operator=True, status=exc.status) from exc
        if exc.status in {400, 409, 411, 413, 415}:
            raise pending("codex_api_request_rejected", "Pro API отклонил сохранённое задание. "
                          "Нужна проверка администратора; новый вызов не создаётся.", operator=True,
                          status=exc.status) from exc
        if 300 <= exc.status < 500 and exc.status not in {408, 429}:
            raise pending("codex_api_access_error", "Нужна проверка адреса и доступа к Pro API. "
                          "Сохранённое задание ожидает восстановления связи.", operator=True,
                          status=exc.status) from exc
        raise pending("codex_api_waiting", "Pro API временно недоступен или занят. "
                      "Продолжим получение того же задания.", status=exc.status) from exc
    except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise pending("codex_api_delivery_pending", "Ожидаем достоверный сохранённый ответ Pro API.") from exc
    finally:
        client.close()


def unpack(status, ident):
    receipt = status.get("receipt")
    if receipt is None:
        raise pending("codex_api_pending", "Pro создаёт ответ." if status.get("state") == "running"
                      else "Задание Pro сохранено. Ожидаем исполнителя.")
    try:
        if (status.get("id") != ident or not isinstance(receipt, dict)
                or type(receipt.get("ok")) is not bool or digest(receipt) != status.get("receipt_hash")):
            raise ValueError()
        usage = receipt.get("usage")
        if usage is not None and (not isinstance(usage, dict) or any(
            type(usage.get(k)) is not int or usage[k] < 0
            for k in ("input_tokens", "cached_input_tokens", "output_tokens")
        ) or usage["cached_input_tokens"] > usage["input_tokens"]):
            raise ValueError()
        if not isinstance(receipt.get("metadata"), dict):
            raise ValueError()
        if receipt["ok"]:
            if (status.get("state") != "completed" or not isinstance(receipt.get("response"), dict)
                    or not isinstance(receipt.get("raw_response"), str)
                    or parse(receipt["raw_response"]) != receipt["response"]):
                raise ValueError()
        elif (status.get("state") not in TERMINAL - {"completed"}
              or not isinstance(receipt.get("error"), dict)
              or not isinstance(receipt["error"].get("code"), str)
              or type(receipt["error"].get("outcome_unknown")) is not bool
              or status.get("state") == "unknown" and not receipt["error"]["outcome_unknown"]):
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise pending("codex_api_receipt_invalid", "Проверяем целостность сохранённого ответа Pro.") from exc
    metadata = {**receipt["metadata"], "codex_api_job_id": ident,
                "receipt_hash": status["receipt_hash"], "inference_submitted": status.get("inference_submitted")}
    if not receipt["ok"]:
        if (status['state'] == 'failed' and receipt['error']['outcome_unknown'] is False
                and metadata.get('turn_status') == 'failed'
                and metadata.get('provider_error', {}).get('incomplete_reason') == 'max_output_tokens'):
            raise GenerationError('response_output_limit',
                                  'Ответ модели прервался из-за ограничения длины. Полученные данные сохранены.',
                                  usage=usage, raw_response=receipt.get('partial_response'), provider_metadata=metadata)
        raise GenerationError(receipt["error"]["code"], "Pro не завершил ответ. Полученные данные сохранены.",
                              usage=usage, outcome_unknown=receipt["error"]["outcome_unknown"],
                              raw_response=receipt.get("partial_response"), provider_metadata=metadata)
    return {"response": receipt["response"], "raw_response": receipt["raw_response"],
            "model": receipt["model"], "usage": usage, "provider_metadata": metadata}


def generate(request, *, on_event, is_cancelled):
    if is_cancelled():
        raise pending("codex_api_pending", "Ожидание передано следующему обработчику.")
    return unpack(fetch(request), request["codex_api"]["id"])


def refresh_catalog():
    """Worker exports non-secret availability; web never needs a remote API token."""
    url, token = configuration()
    client = Client(url, token)
    try:
        health, catalog = client.call("GET", "/health"), client.call("GET", "/models")
        if health.get("protocol") != 1 or not isinstance(catalog.get("models"), list):
            raise ValueError("unsupported_protocol")
        snapshot = {"url": url, "checked_at": time.time(), "health": {
            k: health.get(k) for k in ("status", "worker_online", "draining", "attention_required")
        }, "models": catalog["models"]}
        target = Path(os.environ["GAMEFORGE_CODEX_API_CATALOG"])
        # Directory is operator-created. Only this sanitized snapshot is shared with web.
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(encoded(snapshot))
            output.flush()
            os.fsync(output.fileno())
        try:
            temporary.chmod(0o644)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return snapshot
    finally:
        client.close()


def available_models():
    try:
        path = Path(os.environ["GAMEFORGE_CODEX_API_CATALOG"])
        if path.stat().st_size > 128_000:
            return []
        snapshot = parse(path.read_bytes())
        if snapshot["url"] != origin() or not 0 <= time.time() - snapshot["checked_at"] < CATALOG_TTL:
            return []
        health = snapshot["health"]
        if (health.get("status") != "ok" or health.get("worker_online") is not True
                or health.get("draining") is not False or health.get("attention_required") is not False):
            return []
        return [{"id": item["id"], "name": item["name"],
                 "reasoning_efforts": [{"effort": effort} for effort in item["efforts"]]}
                for item in snapshot["models"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []
