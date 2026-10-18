"""Private Unix-socket transport for the container deployment (no Docker socket)."""

import json
import os
import signal
import socket
import struct
import subprocess
import sys
from pathlib import Path

from .contracts import browser_watchdog_seconds
from .protocol import receive
from .runner import identity

MAX_BYTES = 2_000_000


def run_bounded(payload):
    """A hung renderer cannot block the persistent validation service forever."""
    limit = browser_watchdog_seconds(payload.get("checks"))
    process = subprocess.Popen(
        [sys.executable, "-m", "validation.runner"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(json.dumps(payload), timeout=limit)
        if process.returncode != 0:
            raise ValueError("browser worker exited unexpectedly")
        result = json.loads(output)
        if not isinstance(result, dict):
            raise ValueError("invalid browser result")
        return result
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=3)
        return {
            "status": "infrastructure_error",
            "artifact_hash": payload.get("artifact_hash"),
            "environment": identity(),
            "facts": [],
            "findings": [
                {
                    "code": "browser_watchdog",
                    "message": "Изолированный браузер перестал отвечать. Процесс остановлен; следующие проверки доступны.",
                }
            ],
        }
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)


def serve():
    path = Path(os.environ.get("VALIDATOR_SOCKET", "/run/validator/service.sock"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        path.chmod(0o660)
        server.listen(8)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(180)
                payload = {}
                try:
                    size = struct.unpack("!I", receive(connection, 4))[0]
                    if not 0 < size <= MAX_BYTES:
                        raise ValueError("invalid request size")
                    payload = json.loads(receive(connection, size))
                    if not isinstance(payload, dict):
                        payload = {}
                        raise ValueError("request must be an object")
                    result = (
                        {"environment": identity()} if payload.get("probe") is True else run_bounded(payload)
                    )
                except Exception as exc:
                    result = {
                        "status": "infrastructure_error",
                        "artifact_hash": payload.get("artifact_hash"),
                        "environment": "mini-browser-v1",
                        "facts": [],
                        "findings": [{"code": "validator_failed", "message": str(exc)[:500]}],
                    }
                encoded = json.dumps(result).encode()
                try:
                    connection.sendall(struct.pack("!I", len(encoded)) + encoded)
                except OSError:
                    pass


if __name__ == "__main__":
    if sys.argv[1:] == ["--once"]:
        print(json.dumps(run_bounded(json.loads(sys.stdin.read(MAX_BYTES))), ensure_ascii=False))
    else:
        serve()
