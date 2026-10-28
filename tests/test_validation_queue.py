import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from validation.service import _socket_validate


def serve_fixture(path):
    from validation import daemon
    os.environ['VALIDATOR_SOCKET'] = path
    daemon.identity = lambda: 'mini-browser-v1:test:browser'

    def execute(payload, cancelled=None, progress=None):
        start = time.monotonic()
        while time.monotonic() - start < payload.get('duration', 0.4):
            if cancelled and cancelled():
                return {'status': 'cancelled'}
            time.sleep(0.01)
        return {'status': 'passed', 'job_id': payload['job_id']}

    daemon.run_bounded = execute
    daemon.serve()


@pytest.fixture
def daemon_socket():
    directory = tempfile.TemporaryDirectory(prefix='gf-v-', dir='/tmp')
    path = str(Path(directory.name) / 'v.sock')
    process = multiprocessing.get_context('spawn').Process(target=serve_fixture, args=(path,))
    process.start()
    try:
        for _ in range(200):
            if Path(path).exists():
                break
            time.sleep(0.01)
        assert Path(path).exists()
        yield path
    finally:
        process.terminate()
        process.join(5)
        directory.cleanup()


@pytest.mark.parametrize('count', [1, 2, 4])
def test_health_and_fifo_under_concurrent_jobs(daemon_socket, count):
    events = [[] for _ in range(count)]
    with ThreadPoolExecutor() as pool:
        futures = [pool.submit(_socket_validate, daemon_socket,
                   {'html': 'fixture', 'job_id': str(uuid.uuid4())}, 0.7, progress=events[i].append)
                   for i in range(count)]
        for _ in range(100):
            if any(any(e['event'] == 'started' for e in stream) for stream in events):
                break
            time.sleep(0.01)
        start = time.monotonic()
        assert _socket_validate(daemon_socket, {'probe': True}, 1)['state'] == 'busy'
        assert time.monotonic() - start < 1
        results = [f.result(5) for f in futures]
    assert all(r['status'] == 'passed' for r in results)
    assert all([e['event'] for e in stream] == ['queued', 'started'] for stream in events)
    assert max(r['timings']['queue_seconds'] for r in results) >= (count - 1) * 0.35


def test_cancellation_frees_renderer_for_next_job(daemon_socket):
    ident = str(uuid.uuid4())
    events = []
    with ThreadPoolExecutor() as pool:
        first = pool.submit(_socket_validate, daemon_socket,
                            {'html': 'fixture', 'job_id': ident, 'duration': 10}, 12, progress=events.append)
        for _ in range(100):
            if any(e['event'] == 'started' for e in events):
                break
            time.sleep(0.01)
        _socket_validate(daemon_socket, {'cancel': True, 'job_id': ident}, 1)
        assert first.result(2)['status'] == 'cancelled'
        assert _socket_validate(daemon_socket, {'html': 'fixture', 'job_id': str(uuid.uuid4())}, 2)['status'] == 'passed'


def test_cancel_kills_real_process(monkeypatch):
    from validation import daemon
    original = subprocess.Popen
    children = []

    def child(*args, **kwargs):
        p = original([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
        children.append(p)
        return p

    monkeypatch.setattr(daemon.subprocess, 'Popen', child)
    monkeypatch.setattr(daemon, 'identity', lambda: 'test')
    started = time.monotonic()
    result = daemon.run_bounded({'checks': []}, lambda: time.monotonic() - started > 0.2)
    assert result['status'] == 'cancelled'
    assert children[0].poll() is not None


def test_mismatched_controller_is_rejected_before_browser_admission(daemon_socket):
    events = []
    report = _socket_validate(daemon_socket, {'html': 'fixture', 'job_id': str(uuid.uuid4()),
                               'validator_hash': 'stale-controller'}, 1, progress=events.append)
    assert report['status'] == 'infrastructure_error'
    assert not events  # never queued or started
    assert 'before admission' in report['findings'][0]['message']
