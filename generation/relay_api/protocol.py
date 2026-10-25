import hashlib
import json
import os
from urllib.parse import urlsplit

PREFIX = "/bridge/v1"
MAX_RECEIPT = 4_000_000


class Problem(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def secret(name):
    """Systemd/Docker credentials can be files; secret values never enter arguments."""
    path = os.environ.get(name + "_FILE")
    if path:
        with open(path) as source:
            return source.read().strip()
    return os.environ.get(name, "")


def secure_url(value, *, local=False):
    url = urlsplit(value)
    loopback = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (url.scheme != "https" and not (url.scheme == "http" and loopback)) or (
        not url.hostname or url.username or url.password or url.query or url.fragment
    ):
        raise ValueError("HTTPS is required; HTTP is allowed only on loopback")
    if local and not loopback:
        raise ValueError("The GPU executor must use its local vLLM API")
    return value.rstrip("/")


def validate_receipt(receipt):
    if not isinstance(receipt, dict) or set(receipt) != {"ok", "result" if receipt.get("ok") else "error"}:
        raise Problem(400, "invalid_receipt")
    if type(receipt["ok"]) is not bool:
        raise Problem(400, "invalid_receipt")
    part = receipt["result" if receipt["ok"] else "error"]
    if not isinstance(part, dict):
        raise Problem(400, "invalid_receipt")
    if receipt["ok"]:
        if not isinstance(part.get("response"), dict):
            raise Problem(400, "invalid_receipt")
    elif not isinstance(part.get("code"), str) or type(part.get("outcome_unknown")) is not bool:
        raise Problem(400, "invalid_receipt")
    if len(encoded(receipt).encode()) > MAX_RECEIPT:
        raise Problem(413, "receipt_too_large")
    return receipt
