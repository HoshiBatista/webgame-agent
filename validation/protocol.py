import json
import os
import signal
import subprocess
import time


class ValidationCancelled(Exception):
    pass


def communicate(process, data, *, timeout, cancelled=None, progress=None, read_progress=None):
    """Bound execution from actual process start; cancellation kills descendants."""
    deadline = time.monotonic() + timeout
    consumed = 0

    def notify(raw=None):
        nonlocal consumed
        if not progress:
            return
        raw = read_progress() if read_progress else raw or b''
        raw = raw.encode() if isinstance(raw, str) else raw
        end = raw.rfind(b'\n') + 1
        for line in raw[consumed:end].splitlines():
            event = json.loads(line)
            if event.get('event') == 'scenario':
                progress(event)
        consumed = end

    while True:
        if cancelled and cancelled():
            raise ValidationCancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            result = process.communicate(data, timeout=min(0.2, remaining))
            notify(result[0])
            return result
        except subprocess.TimeoutExpired as exc:
            notify(exc.output)
            data = None


def result_from_output(raw):
    """Progress frames precede the single final report on the private pipe."""
    if isinstance(raw, bytes):
        raw = raw.decode()
    lines = raw.splitlines()
    if not lines:
        raise ValueError('missing validator result')
    result = json.loads(lines[-1])
    if not isinstance(result, dict) or 'event' in result:
        raise ValueError('missing final validator result')
    return result


def terminate(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=3)


def receive(connection, size):
    value = bytearray()
    while len(value) < size:
        part = connection.recv(size - len(value))
        if not part:
            raise ConnectionError("incomplete validation message")
        value.extend(part)
    return bytes(value)
