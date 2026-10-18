"""Trusted controller: pass bytes to a networkless container, never execute game code here."""

import hashlib
import json
import os
import socket
import struct
import subprocess
import time

from .contracts import browser_watchdog_seconds, implementation_hash

ENVIRONMENT = "mini-browser-v1"


def environment_identity():
    code_hash = implementation_hash()
    try:
        if path := os.environ.get("VALIDATOR_SOCKET"):
            environment = _socket_validate(path, {"probe": True}, 10)["environment"]
            if not isinstance(environment, str) or not environment.startswith(f"{ENVIRONMENT}:{code_hash}:"):
                raise ValueError("stale validator implementation")
            return environment
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.Image}}",
                os.environ.get("VALIDATOR_CONTAINER", "gf-mini-validator"),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return f"{ENVIRONMENT}:{code_hash}:{result.stdout.strip()}"
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return f"{ENVIRONMENT}:{code_hash}:unavailable"


def _socket_validate(path, payload, timeout):
    from .protocol import receive

    encoded = json.dumps(payload).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(path)
        connection.sendall(struct.pack("!I", len(encoded)) + encoded)
        size = struct.unpack("!I", receive(connection, 4))[0]
        if not 0 < size <= 4_000_000:
            raise ValueError("invalid response size")
        return json.loads(receive(connection, size))


def _failure(message, artifact_hash, started):
    return {
        "status": "infrastructure_error",
        "findings": [{"code": "validator_unavailable", "message": message}],
        "facts": [],
        "artifact_hash": artifact_hash,
        "environment": ENVIRONMENT,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _validated_report(report, checks, artifact_hash, started):
    if not isinstance(report, dict) or report.get("artifact_hash") != artifact_hash:
        raise ValueError("artifact hash mismatch")
    if report.get("status") not in {"passed", "failed", "unverified", "infrastructure_error"}:
        raise ValueError("invalid validation status")
    if not all(
        isinstance(report.get(name), list) and all(isinstance(value, dict) for value in report[name])
        for name in ("facts", "findings")
    ):
        raise ValueError("invalid validation facts")
    if report["status"] != "infrastructure_error":
        environment = report.get("environment")
        if not isinstance(environment, str) or not environment.startswith(
            f"{ENVIRONMENT}:{implementation_hash()}:"
        ):
            raise ValueError("validator implementation is stale; rebuild the browser image")
    if report["status"] == "passed":
        expected = {check.get("id"): check for check in checks}
        facts = {fact.get("id"): fact for fact in report["facts"]}
        if (
            not checks
            or not {"start", "control", "outcome"}.issubset({check.get("category") for check in checks})
            or len(expected) != len(checks)
            or len(facts) != len(report["facts"])
            or set(expected) != set(facts)
            or report["findings"]
        ):
            raise ValueError("passed report lacks complete browser evidence")
        for ident, check in expected.items():
            fact = facts[ident]
            if fact.get("status") != "passed" or any(
                fact.get(key) != check.get(key) for key in ("category", "requirement", "viewport")
            ):
                raise ValueError("passed report does not match requested effects")
            if fact.get("actions") != check.get("steps"):
                raise ValueError("passed report skipped real input actions")
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def validate(html: str, checks: list[dict], *, artifact_hash: str) -> dict:
    started = time.monotonic()
    if hashlib.sha256(html.encode()).hexdigest() != artifact_hash:
        return _failure("Хеш переданного HTML не совпадает с кандидатом.", artifact_hash, started)
    container = os.environ.get("VALIDATOR_CONTAINER", "gf-mini-validator")
    payload = {"html": html, "checks": checks, "artifact_hash": artifact_hash}
    try:
        max_duration = browser_watchdog_seconds(checks) + 5
        if socket_path := os.environ.get("VALIDATOR_SOCKET"):
            report = _socket_validate(socket_path, payload, max_duration)
            return _validated_report(report, checks, artifact_hash, started)
        inspected = subprocess.run(
            ["docker", "inspect", container],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        config = json.loads(inspected.stdout)[0]
        host = config["HostConfig"]
        if (
            host.get("NetworkMode") != "none"
            or host.get("Init") is not True
            or not host.get("ReadonlyRootfs")
            or not config["Config"].get("User")
            or config["Config"]["User"] in {"0", "root"}
            or "ALL" not in (host.get("CapDrop") or [])
            or host.get("Privileged")
            or any(m.get("Type") == "bind" for m in config.get("Mounts", []))
        ):
            return _failure("Контейнер проверки не соответствует профилю изоляции.", artifact_hash, started)
        # The watchdog bounds broken browser infrastructure, not model generation.
        result = subprocess.run(
            ["docker", "exec", "-i", container, "python", "-m", "validation.daemon", "--once"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=max_duration,
            check=True,
        )
        report = json.loads(result.stdout)
        return _validated_report(report, checks, artifact_hash, started)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError) as exc:
        return _failure(f"Изолированный браузер недоступен ({type(exc).__name__}).", artifact_hash, started)
