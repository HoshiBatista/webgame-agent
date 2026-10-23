import json
import re
import time
from collections import OrderedDict

import httpx

from .diagnostics import emit, errors
from .protocol import MAX_RECEIPT, PREFIX, secure_url


class RelayHTTPError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Relay HTTP {status}")


class Client:
    def __init__(self, url, token, *, transport=None):
        self.url = secure_url(url)
        if len(token) < 32:
            raise ValueError("A separate relay token is required")
        self.attempts = OrderedDict()
        self.http = httpx.Client(
            headers={"Authorization": "Bearer " + token},
            timeout=httpx.Timeout(60, connect=10),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def close(self):
        self.http.close()

    def call(self, method, path, body=None):
        match = re.fullmatch(r"/(jobs|worker)/([0-9a-f-]{36})(?:/(cancel|start|heartbeat|receipt))?", path)
        job = match[2] if match else None
        operation = (match[3] or method.lower()) if match else {
            "/health": "health", "/worker/claim": "claim"}.get(path, "other")
        key = (operation, job)
        self.attempts[key] = self.attempts.get(key, 0) + 1
        self.attempts.move_to_end(key)
        if len(self.attempts) > 256:
            self.attempts.popitem(last=False)
        facts = {"job_id": job, "operation": operation, "attempt": self.attempts[key],
                 "request_bytes": 0, "received_bytes": 0}
        started = time.monotonic()
        try:
            body_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":"),
                                    allow_nan=False).encode() if body is not None else None
            facts["request_bytes"] = len(body_bytes or b"")
            headers = {"Content-Type": "application/json"}
            if job:
                headers["X-GameForge-Trace-ID"] = job.replace("-", "")
            with self.http.stream(method, self.url + PREFIX + path, content=body_bytes,
                                  headers=headers) as response:
                facts["http_status"] = response.status_code
                if response.status_code != 200:
                    raise RelayHTTPError(response.status_code)
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    facts["received_bytes"] += len(chunk)
                    if len(data) > MAX_RECEIPT + 2_000_000:
                        raise ValueError("Relay response too large")
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise ValueError("Invalid relay response")
                facts["receipt_received"] = result.get("receipt") is not None
                return result
        except (httpx.HTTPError, RelayHTTPError, ValueError, OSError) as exc:
            facts["errors"] = errors(exc)
            raise
        finally:
            facts["elapsed_seconds"] = round(time.monotonic() - started, 3)
            # Successful empty polling is deliberately quiet; failures and transfers are visible.
            if "errors" in facts or facts.get("receipt_received") or operation not in {"claim", "heartbeat", "health", "get"}:
                emit("relay_http", **facts)
