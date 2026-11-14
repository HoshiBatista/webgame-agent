"""Opt-in, fork-aware operational telemetry. No model data or automatic instrumentation."""

import atexit
import contextlib
import functools
import json
import math
import os
import re
import resource
import socket
import threading
import time
import uuid
from urllib.parse import urlsplit

PROVIDERS = {'fake', 'relay', 'vllm', 'codex', 'codex_api', 'other'}
OPERATIONS = {'create', 'edit', 'repair', 'plan', 'music', 'check_repair', 'checks_create',
              'visual_review', 'visual_patch', 'extract_preferences', 'other'}
STATUSES = {'queued', 'generating', 'checking', 'succeeded', 'needs_attention', 'unverified', 'failed',
            'cancelled', 'unknown', 'reserved', 'sent', 'returned', 'settled', 'processing', 'applied',
            'unchanged', 'full', 'stale', 'skipped', 'none', 'other'}
CODES = {'validator_unavailable', 'javascript_syntax', 'runtime_or_network', 'invalid_check', 'effect_mismatch',
         'check_timeout', 'mobile_overflow', 'canvas_missing', 'surface_not_observed', 'incomplete_checks',
         'missing_keyboard_control', 'missing_mobile_start', 'missing_mobile_control', 'no_changes',
         'invalid_schema', 'repair_exhausted', 'repair_regression', 'outcome_unknown', 'other'}
TASKS = {'process_run', 'process_validation', 'process_feedback', 'dispatch_outbox', 'recover_expired',
         'reconcile_relay_cancellations', 'refresh_codex_api_catalog', 'other'}
VALUES = {'provider': PROVIDERS, 'profile': {'pro', 'lite', 'default', 'other'}, 'operation': OPERATIONS,
          'status': STATUSES | {'waiting', 'infrastructure_error', 'passed', 'superseded'}, 'code': CODES, 'task': TASKS,
          'outcome': {'ok', 'pending', 'error', 'cancelled', 'passed', 'failed', 'unverified', 'infrastructure_error'},
          'component': {'provider_transport', 'validator', 'run_process', 'feedback', 'validation_job', 'other'},
          'method': {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'OTHER'},
          'source': {'automatic', 'manual', 'none'},
          'kind': {'input', 'output', 'cached_input'},
          'dependency': {'postgres', 'redis', 'validator', 'app', 'preview'},
          'state': {'active', 'idle', 'idle in transaction', 'waiting', 'other'}}
COUNTERS = {'http_requests', 'tasks', 'operations', 'runs_created', 'runs_finished', 'invocations_sent',
            'invocations_resolved', 'tokens', 'validation_findings', 'cancellations'}
HISTOGRAMS = {'http_response_ready_seconds', 'task_seconds', 'task_queue_seconds', 'operation_seconds',
              'run_seconds', 'run_queue_seconds', 'model_wait_seconds', 'check_seconds', 'packaging_seconds'}
GAUGES = {'worker_heartbeat_timestamp_seconds', 'beat_publish_timestamp_seconds', 'runs', 'invocations',
          'feedback_jobs', 'validation_jobs', 'outbox_pending', 'outbox_oldest_seconds', 'run_oldest_queued_seconds',
          'expired_leases', 'budget_limit_usd', 'budget_spent_usd', 'budget_reserved_usd', 'budget_unknown_usd',
          'budget_available_usd', 'state_snapshot_timestamp_seconds', 'state_collection_success', 'dependency_up',
          'redis_queue_messages', 'redis_memory_used_bytes', 'redis_memory_max_bytes', 'redis_clients',
          'redis_blocked_clients', 'redis_evicted_keys', 'redis_hits', 'redis_misses', 'redis_commands',
          'postgres_connections', 'postgres_max_connections', 'postgres_database_bytes', 'postgres_deadlocks',
          'postgres_commits', 'postgres_rollbacks', 'postgres_cache_hits', 'postgres_disk_reads'}
BUCKETS = (.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1200)
_state = None
_failed_pid = None
_lock = threading.RLock()


def enabled():
    return os.environ.get('GAMEFORGE_OBSERVABILITY_ENABLED', '0') == '1'


def clean(attributes, *, trace=False):
    result: dict[str, object] = {}
    for key, value in (attributes or {}).items():
        if key in VALUES:
            result[key] = value if isinstance(value, str) and value in VALUES[key] else ('default' if key == 'profile' and not value else 'other')
        elif key == 'http_status' and type(value) is int and 100 <= value <= 599:
            result[key] = value
        elif key == 'route' and isinstance(value, str):
            # Only resolved application patterns are supplied by the middleware, never request.path.
            result[key] = value[:160]
        elif trace and key in {'gameforge.run.id', 'gameforge.validation.id', 'gameforge.feedback.id'}:
            try:
                result[key] = str(uuid.UUID(str(value)))
            except (ValueError, TypeError):
                pass
    return result


def dimensions(value):
    get = value.get if isinstance(value, dict) else lambda k, default=None: getattr(value, k, default)
    return clean({'provider': get('provider', 'other'), 'profile': get('model_profile', 'default'),
                  'operation': get('operation', 'other')})


class State:
    def __init__(self):
        import requests
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.metrics import Observation
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import Histogram, MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import SpanLimits, TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        endpoint = os.environ.get('GAMEFORGE_OTLP_ENDPOINT', 'http://otel-collector:4318').rstrip('/')
        url = urlsplit(endpoint)
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment or url.path:
            raise ValueError('OTLP endpoint must be an origin without credentials, query or path')
        role = os.environ.get('GAMEFORGE_SERVICE_ROLE', 'app')
        if role not in {'app', 'preview', 'worker', 'beat', 'observer'}:
            raise ValueError('Invalid telemetry role')
        self.pid, self.role, self.started = os.getpid(), role, time.monotonic()
        environment = os.environ.get('GAMEFORGE_ENVIRONMENT', 'local')
        release = os.environ.get('GAMEFORGE_RELEASE', 'dev')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,48}', environment) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', release):
            raise ValueError('Invalid telemetry deployment labels')
        resource_data = Resource({'service.name': 'gameforge', 'service.namespace': 'gameforge',
            'service.instance.id': f'{socket.gethostname()[:48]}-{self.pid}-{uuid.uuid4().hex[:8]}',
            'service.version': release, 'deployment.environment.name': environment, 'gameforge.role': role})
        interval = max(1000, int(os.environ.get('GAMEFORGE_TELEMETRY_INTERVAL_MS', '10000')))
        sample = float(os.environ.get('GAMEFORGE_TRACE_SAMPLE_RATIO', '1'))
        if not 0 <= sample <= 1:
            raise ValueError('Trace ratio must be between 0 and 1')

        class OperationalSession(requests.Session):
            def prepare_request(self, request):
                prepared = super().prepare_request(request)
                # SDK 1.45 merges OTEL_*_HEADERS even when explicit headers are passed.
                allowed = {'content-type', 'content-length', 'content-encoding', 'user-agent', 'accept', 'accept-encoding'}
                for name in list(prepared.headers):
                    if name.lower() not in allowed:
                        del prepared.headers[name]
                return prepared

            def send(self, request, **kwargs):
                kwargs['allow_redirects'] = False
                return super().send(request, **kwargs)

        def exporter(cls, path):
            session = OperationalSession()
            session.trust_env = False
            return cls(endpoint=endpoint + path, timeout=2,
                       headers={'User-Agent': 'GameForge-operational-telemetry'}, session=session)

        self.traces = TracerProvider(resource=resource_data, sampler=TraceIdRatioBased(sample),
                                    span_limits=SpanLimits(max_attributes=32, max_attribute_length=160), shutdown_on_exit=False)
        self.traces.add_span_processor(BatchSpanProcessor(exporter(OTLPSpanExporter, '/v1/traces'),
                                                        max_queue_size=2048, schedule_delay_millis=1000))
        self.tracer = self.traces.get_tracer('gameforge.operations', '1')
        self.metrics = MeterProvider(resource=resource_data, shutdown_on_exit=False,
            metric_readers=[PeriodicExportingMetricReader(exporter(OTLPMetricExporter, '/v1/metrics'), export_interval_millis=interval)],
            views=[View(instrument_type=Histogram, instrument_name='gameforge_*seconds', aggregation=ExplicitBucketHistogramAggregation(BUCKETS))])
        self.meter = self.metrics.get_meter('gameforge.operations', '1')
        self.logs = LoggerProvider(resource=resource_data, shutdown_on_exit=False)
        self.logs.add_log_record_processor(BatchLogRecordProcessor(exporter(OTLPLogExporter, '/v1/logs'),
                                                                 max_queue_size=2048, schedule_delay_millis=1000))
        self.logger = self.logs.get_logger('gameforge.operations', '1')
        self.counters = {n: self.meter.create_counter('gameforge_' + n, unit='1') for n in COUNTERS}
        self.histograms = {n: self.meter.create_histogram('gameforge_' + n, unit='s') for n in HISTOGRAMS}
        self.samples: dict[str, list] = {n: [] for n in GAUGES}
        self.guard = threading.RLock()
        self.observable = []
        for name in GAUGES:
            def observe(_options, name=name):
                with self.guard:
                    return [Observation(value, attrs) for value, attrs in self.samples[name]]
            self.observable.append(self.meter.create_observable_gauge('gameforge_' + name, callbacks=[observe]))
        self.observable.append(self.meter.create_observable_gauge('gameforge_telemetry_heartbeat_timestamp_seconds',
            callbacks=[lambda _: [Observation(time.time())]]))
        self.observable.append(self.meter.create_observable_gauge('gameforge_process_uptime_seconds',
            callbacks=[lambda _: [Observation(time.monotonic() - self.started)]]))
        self.observable.append(self.meter.create_observable_counter('gameforge_process_cpu_seconds', unit='s',
            callbacks=[lambda _: [Observation(resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime)]]))
        def resident_bytes(_):
            with open('/proc/self/statm') as handle:
                return [Observation(int(handle.read().split()[1]) * os.sysconf('SC_PAGE_SIZE'))]

        if os.path.isdir('/proc/self/fd'):
            self.observable.append(self.meter.create_observable_gauge('gameforge_process_open_fds',
                callbacks=[lambda _: [Observation(len(os.listdir('/proc/self/fd')))]]))
            self.observable.append(self.meter.create_observable_gauge('gameforge_process_resident_memory_bytes', unit='By',
                callbacks=[resident_bytes]))


def get_state():
    global _state, _failed_pid
    if not enabled() or _failed_pid == os.getpid():
        return None
    if _state is not None and _state.pid == os.getpid():
        return _state
    with _lock:
        try:
            if _state is None or _state.pid != os.getpid():
                _state = State()
            return _state
        except Exception:
            # Telemetry never changes admission, accounting or delivery outcomes.
            import logging
            logging.getLogger(__name__).warning('Operational telemetry initialization failed; application continues.')
            _failed_pid = os.getpid()
            return None


def capture():
    if get_state() is None:
        return {}
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return {'traceparent': carrier['traceparent']} if 'traceparent' in carrier else {}


def trace_id():
    if not enabled():
        return ''
    from opentelemetry.trace import get_current_span
    ctx = get_current_span().get_span_context()
    return format(ctx.trace_id, '032x') if ctx.is_valid else ''


def counter(name, value=1, attributes=None):
    try:
        state = get_state()
        if state and name in COUNTERS and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            state.counters[name].add(value, clean(attributes))
    except Exception:
        pass


def histogram(name, value, attributes=None):
    try:
        state = get_state()
        if state and name in HISTOGRAMS and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            state.histograms[name].record(value, clean(attributes))
    except Exception:
        pass


def gauge(name, samples, *, replace=True):
    try:
        state = get_state()
        if state and name in GAUGES:
            values = [(float(v), clean(a)) for v, a in samples if math.isfinite(float(v))]
            with state.guard:
                incoming = {tuple(sorted(a.items())) for _, a in values}
                previous = [(0 if replace else v, a) for v, a in state.samples[name]
                            if tuple(sorted(a.items())) not in incoming]
                state.samples[name] = previous + values
    except Exception:
        pass


def event(name, attributes=None):
    try:
        state = get_state()
        if state and name in {'http.finished', 'task.finished', 'run.created', 'run.finished', 'run.cancelled',
                              'invocation.sent', 'invocation.resolved', 'operation.finished', 'state.refresh_failed'}:
            from opentelemetry._logs import SeverityNumber
            attrs = clean(attributes, trace=True)
            state.logger.emit(body=json.dumps({'event': name, 'trace_id': trace_id(), **attrs}, separators=(',', ':')),
                              severity_number=SeverityNumber.INFO, severity_text='INFO', attributes=attrs)
    except Exception:
        pass


@contextlib.contextmanager
def span(name, attributes=None, parent=None):
    state, manager, active = get_state(), None, None
    if state:
        try:
            from opentelemetry.trace import get_current_span
            from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
            context = None
            if parent and isinstance(parent.get('traceparent'), str):
                candidate = TraceContextTextMapPropagator().extract({'traceparent': parent['traceparent']})
                saved, current = get_current_span(candidate).get_span_context(), get_current_span().get_span_context()
                if saved.is_valid and saved.trace_id != current.trace_id:
                    context = candidate
            manager = state.tracer.start_as_current_span(name, context=context, attributes=clean(attributes, trace=True),
                                                        record_exception=False, set_status_on_exception=False)
            active = manager.__enter__()
        except Exception:
            manager = None
    try:
        yield active
    except BaseException as exc:
        if active and type(exc).__name__ not in {'GenerationPending', 'ValidationCancelled'}:
            try:
                from opentelemetry.trace import StatusCode
                active.set_status(StatusCode.ERROR)
            except Exception:
                pass
        raise
    finally:
        if manager:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                pass


def observed(component, attributes=None, outcome=None, parent=None):
    def decorate(fn):
        @functools.wraps(fn)
        def call(*args, **kwargs):
            if get_state() is None:
                return fn(*args, **kwargs)
            try:
                attrs = {**(attributes(*args, **kwargs) if attributes else {}), 'component': component}
            except Exception:
                attrs = {'component': component}
            started = time.monotonic()
            result_status = 'error'
            try:
                saved_parent = parent(*args, **kwargs) if parent else None
            except Exception:
                saved_parent = None
            with span('gameforge.' + component, attrs, saved_parent) as active:
                try:
                    result = fn(*args, **kwargs)
                    result_status = 'ok'
                    if outcome:
                        try:
                            result_status = outcome(result)
                        except Exception:
                            pass
                    return result
                except BaseException as exc:
                    result_status = ('pending' if type(exc).__name__ == 'GenerationPending' else
                                     'cancelled' if type(exc).__name__ == 'ValidationCancelled' else 'error')
                    raise
                finally:
                    final = {**attrs, 'outcome': result_status}
                    if active:
                        try:
                            active.set_attributes(clean(final))
                            if result_status in {'error', 'failed', 'infrastructure_error'}:
                                from opentelemetry.trace import StatusCode
                                active.set_status(StatusCode.ERROR)
                        except Exception:
                            pass
                    counter('operations', attributes=final)
                    histogram('operation_seconds', time.monotonic() - started, final)
                    event('operation.finished', final)
        return call
    return decorate


def flush():
    state = get_state()
    if state:
        for provider in (state.traces, state.metrics, state.logs):
            try:
                provider.force_flush(timeout_millis=5000)
            except Exception:
                pass


def shutdown():
    global _state
    if _state and _state.pid == os.getpid():
        for provider in (_state.traces, _state.metrics, _state.logs):
            try:
                provider.shutdown()
            except Exception:
                pass
        _state = None


def after_fork():
    global _state, _failed_pid, _lock
    _state, _failed_pid, _lock = None, None, threading.RLock()


atexit.register(shutdown)
if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=after_fork)
