"""Private Unix-socket transport for the container deployment (no Docker socket)."""

import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from .contracts import browser_watchdog_seconds, implementation_hash
from .protocol import ValidationCancelled, communicate, receive, result_from_output
from .runner import identity

MAX_BYTES = 2_000_000


def run_bounded(payload, cancelled=None, progress=None):
    """A hung renderer cannot block the persistent validation service forever."""
    limit = browser_watchdog_seconds(payload.get("checks"), payload.get("operator_criteria"), capture_visual=payload.get("capture_visual", False))
    process = subprocess.Popen(
        [sys.executable, "-m", "validation.runner"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = communicate(process, json.dumps(payload), timeout=limit, cancelled=cancelled, progress=progress)
        if process.returncode != 0:
            raise ValueError("browser worker exited unexpectedly")
        result = result_from_output(output)
        if not isinstance(result, dict):
            raise ValueError("invalid browser result")
        return result
    except (subprocess.TimeoutExpired, ValidationCancelled) as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=3)
        return {
            "status": "cancelled" if isinstance(exc, ValidationCancelled) else "infrastructure_error",
            "artifact_hash": payload.get("artifact_hash"),
            "environment": identity(),
            "facts": [],
            "findings": [
                {
                    "code": "validation_cancelled" if isinstance(exc, ValidationCancelled) else "browser_watchdog",
                    "message": "Процесс проверки остановлен; следующие проверки доступны.",
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


class BrowserQueue:
    """One renderer, bounded FIFO. Control requests never wait for the renderer."""

    def __init__(self):
        self.condition = threading.Condition()
        self.pending: deque[str] = deque()
        self.jobs = {}
        self.active = None

    def cancel(self, ident):
        with self.condition:
            if ident in self.jobs:
                self.jobs[ident].set()
            self.condition.notify_all()

    def execute(self, payload, send):
        ident = payload.get('job_id')
        if not isinstance(ident, str) or not 1 <= len(ident) <= 100:
            raise ValueError('invalid validation job id')
        queued = time.monotonic()
        with self.condition:
            if ident in self.jobs or len(self.jobs) >= 8:
                raise ValueError('validation queue full or duplicate job')
            cancelled = self.jobs[ident] = threading.Event()
            self.pending.append(ident)
        try:
            send({'event': 'queued'})
            with self.condition:
                while self.active is not None or self.pending[0] != ident:
                    if cancelled.is_set():
                        raise ValidationCancelled()
                    if time.monotonic() - queued >= 1200:
                        raise TimeoutError('validation queue deadline')
                    self.condition.wait(0.2)
                if cancelled.is_set():
                    raise ValidationCancelled()
                self.pending.popleft()
                self.active = ident
            elapsed = time.monotonic() - queued
            send({'event': 'started', 'queue_seconds': round(elapsed, 3)})
            started = time.monotonic()
            result = run_bounded(payload, cancelled.is_set, send if payload.get('progress') else None)
            result['timings'] = {'queue_seconds': round(elapsed, 3),
                                 'execution_seconds': round(time.monotonic() - started, 3)}
            return result
        finally:
            with self.condition:
                if ident in self.pending:
                    self.pending.remove(ident)
                if self.active == ident:
                    self.active = None
                self.jobs.pop(ident, None)
                self.condition.notify_all()


def serve():
    path = Path(os.environ.get("VALIDATOR_SOCKET", "/run/validator/service.sock"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    queue = BrowserQueue()
    environment = identity()
    clients = threading.BoundedSemaphore(24)

    def handle(connection):
        def send(result):
            encoded = json.dumps(result).encode()
            connection.sendall(struct.pack('!I', len(encoded)) + encoded)

        with connection:
            connection.settimeout(10)
            payload = {}
            try:
                size = struct.unpack('!I', receive(connection, 4))[0]
                if not 0 < size <= MAX_BYTES:
                    raise ValueError('invalid request size')
                payload = json.loads(receive(connection, size))
                if not isinstance(payload, dict):
                    payload = {}
                    raise ValueError('request must be an object')
                if payload.get('probe') is True:
                    result = {'environment': environment, 'state': 'busy' if queue.active else 'idle',
                              'queued': len(queue.pending)}
                elif payload.get('cancel') is True:
                    queue.cancel(payload.get('job_id'))
                    result = {'cancel_requested': True}
                elif payload.get('expected_environment') not in (None, environment):
                    raise ValueError('validator environment changed before admission')
                elif payload.get('validator_hash') not in (None, implementation_hash()):
                    raise ValueError('validator implementation changed before admission')
                else:
                    result = queue.execute(payload, send)
            except ValidationCancelled:
                result = {'status': 'cancelled', 'facts': [], 'findings': [],
                          'artifact_hash': payload.get('artifact_hash'), 'environment': environment}
            except Exception as exc:
                result = {'status': 'infrastructure_error', 'artifact_hash': payload.get('artifact_hash'),
                          'environment': environment, 'facts': [],
                          'findings': [{'code': 'validator_failed', 'message': str(exc)[:500]}]}
            try:
                send(result)
            except OSError:
                pass
            finally:
                clients.release()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        path.chmod(0o660)
        server.listen(8)
        while True:
            connection, _ = server.accept()
            if clients.acquire(blocking=False):
                threading.Thread(target=handle, args=(connection,), daemon=True).start()
            else:
                connection.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["--once"]:
        print(json.dumps(run_bounded(json.loads(sys.stdin.read(MAX_BYTES))), ensure_ascii=False))
    else:
        serve()
