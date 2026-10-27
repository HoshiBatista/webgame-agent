"""Trusted controller: pass bytes to an OS-isolated browser, never execute game code here."""

import hashlib
import json
import os
import socket
import struct
import subprocess
import time

from .contracts import browser_watchdog_seconds, implementation_hash, suite_findings

ENVIRONMENT = "mini-browser-v1"


def environment_identity():
    code_hash = implementation_hash()
    try:
        if os.environ.get("VALIDATOR_BACKEND", "docker") == "native":
            from .native import environment_identity as native_identity

            return native_identity()
        if os.environ.get("VALIDATOR_BACKEND", "docker") != "docker":
            raise ValueError("unknown validator backend")
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
    except (OSError, ImportError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
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


def _validated_report(report, checks, artifact_hash, started, *, contract=None, operator_criteria=None):
    if not isinstance(report, dict) or report.get("artifact_hash") != artifact_hash:
        raise ValueError("artifact hash mismatch")
    if report.get("status") not in {"passed", "failed", "unverified", "infrastructure_error"}:
        raise ValueError("invalid validation status")
    if not all(
        isinstance(report.get(name), list) and all(isinstance(value, dict) for value in report[name])
        for name in ("facts", "findings")
    ):
        raise ValueError("invalid validation facts")
    if operator_criteria or 'coverage' in report:
        from .criteria import coverage

        expected_coverage = coverage(checks, operator_criteria or [], report['facts'])
        if report.get('coverage') != expected_coverage:
            raise ValueError('coverage does not match independent criteria')
        if report['status'] == 'passed' and expected_coverage['uncovered']:
            raise ValueError('passed report lacks independent requirements')
    if report["status"] != "infrastructure_error":
        environment = report.get("environment")
        if not isinstance(environment, str) or not environment.startswith(
            f"{ENVIRONMENT}:{implementation_hash()}:"
        ):
            raise ValueError("validator implementation is stale; rebuild the browser image")
        if 'artifact_evidence' not in report:
            raise ValueError('missing mandatory artifact gate receipt')
    if "artifact_evidence" in report:
        from .evidence import gates as evidence_gates
        from .evidence import valid

        if not valid(report["artifact_evidence"], artifact_hash, report.get("environment")):
            raise ValueError("invalid artifact gate receipt")
        if report['artifact_evidence'].get('contract', {}) != (contract or {}):
            raise ValueError('artifact receipt belongs to another module contract')
        if "gates" in report and report["gates"] != evidence_gates(report["artifact_evidence"]):
            raise ValueError("gate flags contradict artifact receipt")
    if report["status"] == "unverified" and report.get("gates") and all(report["gates"].values()):
        from .checks import gates_verified

        if not gates_verified(report, checks):
            raise ValueError("manual verification lacks mandatory gate evidence")
    if report["status"] == "passed":
        if "artifact_evidence" in report:
            from .checks import gates_verified

            if not gates_verified(report, checks):
                raise ValueError("passed report lacks mandatory artifact evidence")
        expected = {check.get("id"): check for check in checks}
        facts = {fact.get("id"): fact for fact in report["facts"]}
        if (
            not checks
            or suite_findings(checks)
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


def validate(html: str, checks: list[dict], *, artifact_hash: str, contract=None, test_profile=None, operator_criteria=(), capture_visual=False) -> dict:
    started = time.monotonic()
    if hashlib.sha256(html.encode()).hexdigest() != artifact_hash:
        return _failure("Хеш переданного HTML не совпадает с кандидатом.", artifact_hash, started)
    container = os.environ.get("VALIDATOR_CONTAINER", "gf-mini-validator")
    payload: dict = {"html": html, "checks": checks, "artifact_hash": artifact_hash}
    from .criteria import OperatorCriterion

    if not isinstance(operator_criteria, tuple) or any(type(c) is not OperatorCriterion for c in operator_criteria):
        raise ValueError("operator criteria must be application-owned objects")
    if operator_criteria:
        payload["operator_criteria"] = [c.payload() for c in operator_criteria]
    if capture_visual:
        payload["capture_visual"] = True
    if contract:
        payload["contract"] = contract
    if test_profile:
        payload["test_profile"] = test_profile
    try:
        max_duration = browser_watchdog_seconds(checks, payload.get("operator_criteria"), capture_visual=payload.get("capture_visual", False)) + 5
        if os.environ.get("VALIDATOR_BACKEND", "docker") == "native":
            from .native import execute

            return _validated_report(execute(payload), checks, artifact_hash, started, contract=contract, operator_criteria=payload.get("operator_criteria"))
        if os.environ.get("VALIDATOR_BACKEND", "docker") != "docker":
            raise ValueError("unknown validator backend")
        if socket_path := os.environ.get("VALIDATOR_SOCKET"):
            report = _socket_validate(socket_path, payload, max_duration)
            return _validated_report(report, checks, artifact_hash, started, contract=contract, operator_criteria=payload.get("operator_criteria"))
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
        return _validated_report(report, checks, artifact_hash, started, contract=contract, operator_criteria=payload.get("operator_criteria"))
    except (OSError, ImportError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError) as exc:
        return _failure(f"Изолированный браузер недоступен ({type(exc).__name__}).", artifact_hash, started)
