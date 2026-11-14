import json
import os
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import RequestFactory

from gameforge import telemetry as t
from gameforge.telemetry_middleware import TelemetryMiddleware

CANARY = 'PRIVATE-prompt-source-cookie-key-never-export'


@pytest.fixture
def telemetry(monkeypatch):
    payloads = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            payloads.append((self.path, dict(self.headers), self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('GAMEFORGE_OBSERVABILITY_ENABLED', '1')
    monkeypatch.setenv('GAMEFORGE_OTLP_ENDPOINT', f'http://127.0.0.1:{server.server_port}')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_HEADERS', 'authorization=' + CANARY)
    monkeypatch.setenv('OTEL_RESOURCE_ATTRIBUTES', 'private=' + CANARY)
    monkeypatch.setattr(t, '_state', None)
    monkeypatch.setattr(t, '_failed_pid', None)
    assert t.get_state() is not None
    try:
        yield payloads
    finally:
        t.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_disabled_is_inert_and_does_not_repeat_business_call(monkeypatch):
    monkeypatch.delenv('GAMEFORGE_OBSERVABILITY_ENABLED', raising=False)
    with patch.object(t, 'State') as state:
        calls = []

        @t.observed('validator')
        def business():
            calls.append(1)
            raise ValueError(CANARY)

        with pytest.raises(ValueError, match=CANARY):
            business()
        assert calls == [1]
        assert t.capture() == {}
        state.assert_not_called()


def test_otlp_privacy_route_patterns_and_context(telemetry):
    from django.http import JsonResponse
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    run_id = uuid.uuid4()
    parent = {}

    def response(request):
        request.resolver_match = SimpleNamespace(route='api/runs/<uuid:ident>/')
        parent.update(t.capture())
        return JsonResponse({'private': CANARY})

    request = RequestFactory().get('/api/runs/' + str(run_id) + '/?q=' + CANARY,
                                   HTTP_AUTHORIZATION=CANARY, HTTP_COOKIE=CANARY,
                                   HTTP_TRACEPARENT='00-' + 'a' * 32 + '-' + 'b' * 16 + '-01')
    assert TelemetryMiddleware(response)(request).status_code == 200
    assert set(parent) == {'traceparent'}
    with t.span('gameforge.run_process', {'gameforge.run.id': run_id, 'prompt': CANARY}, parent):
        assert t.capture()['traceparent'].split('-')[1] == parent['traceparent'].split('-')[1]
        t.event('run.finished', {'gameforge.run.id': run_id, 'status': 'succeeded', 'error': CANARY})
        t.counter('runs_finished', attributes={'gameforge.run.id': run_id, 'status': 'succeeded'})
    t.flush()
    assert {p[0] for p in telemetry} == {'/v1/metrics', '/v1/traces', '/v1/logs'}
    assert all(CANARY.encode() not in body and CANARY not in json.dumps(headers) for _, headers, body in telemetry)
    metrics = [ExportMetricsServiceRequest.FromString(body) for path, _, body in telemetry if path == '/v1/metrics']
    assert all(str(run_id).encode() not in m.SerializeToString() for m in metrics)
    traces = [ExportTraceServiceRequest.FromString(body) for path, _, body in telemetry if path == '/v1/traces']
    spans = [s for batch in traces for resource in batch.resource_spans for scope in resource.scope_spans for s in scope.spans]
    assert any(s.name == 'HTTP GET api/runs/<uuid:ident>/' for s in spans)
    assert all(s.trace_id.hex() != 'a' * 32 for s in spans)
    assert len({s.trace_id for s in spans}) == 1


def test_instrumentation_callback_failure_preserves_result_and_exception(telemetry):
    calls = []

    def broken(*_):
        raise RuntimeError(CANARY)

    @t.observed('validator', attributes=broken, outcome=broken, parent=broken)
    def business():
        calls.append(1)
        return {'result': CANARY}

    assert business() == {'result': CANARY}
    assert calls == [1]
    with pytest.raises(ValueError, match=CANARY):
        with t.span('failure'):
            raise ValueError(CANARY)
    t.flush()
    assert all(CANARY.encode() not in body for _, _, body in telemetry)


def test_failed_setup_does_not_change_result(monkeypatch):
    monkeypatch.setenv('GAMEFORGE_OBSERVABILITY_ENABLED', '1')
    monkeypatch.setenv('GAMEFORGE_OTLP_ENDPOINT', 'https://user:private@example.com/')
    monkeypatch.setattr(t, '_state', None)
    monkeypatch.setattr(t, '_failed_pid', None)
    assert t.observed('validator')(lambda: 42)() == 42
    assert t.capture() == {}


def test_gauges_clear_old_groups_but_keep_distinct_dependencies(telemetry):
    t.gauge('runs', [(3, {'status': 'queued'})])
    t.gauge('runs', [(1, {'status': 'succeeded'})])
    assert (0, {'status': 'queued'}) in t.get_state().samples['runs']
    t.gauge('dependency_up', [(1, {'dependency': 'redis'})], replace=False)
    t.gauge('dependency_up', [(0, {'dependency': 'postgres'})], replace=False)
    assert len(t.get_state().samples['dependency_up']) == 2


def test_metric_dimensions_are_bounded():
    result = t.clean({'provider': CANARY, 'model': CANARY, 'user': uuid.uuid4(),
                      'gameforge.run.id': uuid.uuid4(), 'http_status': 500})
    assert result == {'provider': 'other', 'http_status': 500}


def test_prepare_secrets_is_private_idempotent(tmp_path):
    directory = tmp_path / 'private'
    command = [sys.executable, 'scripts/prepare_observability.py', '--directory', str(directory)]
    subprocess.run(command, check=True, capture_output=True)
    original = (directory / 'metrics_db_password').read_bytes()
    result = subprocess.run(command, check=True, capture_output=True)
    assert (directory / 'metrics_db_password').read_bytes() == original
    assert original not in result.stdout
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / 'metrics_db_password').stat().st_mode & 0o777 == 0o600
    if os.name == 'posix':
        (directory / 'grafana_admin_password').unlink()
        (directory / 'grafana_admin_password').symlink_to(directory / 'metrics_db_password')
        assert subprocess.run(command, capture_output=True).returncode != 0
