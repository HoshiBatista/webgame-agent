"""Celery headers contain only W3C traceparent and a timestamp; no task arguments."""
import contextvars
import time

from celery import signals

from . import telemetry as t

_scope = contextvars.ContextVar('gameforge_task_telemetry', default=None)


def task_name(sender):
    return str(sender).rsplit('.', 1)[-1]


@signals.before_task_publish.connect(weak=False)
def before_publish(sender=None, headers=None, **_):
    if not t.enabled() or headers is None:
        return
    headers['gameforge_trace'] = t.capture()
    headers['gameforge_enqueued'] = time.time()
    if sender == 'studio.tasks.dispatch_outbox':
        t.gauge('beat_publish_timestamp_seconds', [(time.time(), {})])


@signals.task_prerun.connect(weak=False)
def before_task(task=None, **_):
    if not t.enabled():
        return
    try:
        headers = getattr(task.request, 'headers', None) or {}
        attrs = t.clean({'task': task_name(task.name)})
        manager = t.span('celery.' + attrs['task'], attrs, headers.get('gameforge_trace'))
        manager.__enter__()
        _scope.set((manager, time.monotonic(), attrs))
        queued = time.time() - float(headers.get('gameforge_enqueued', time.time()))
        if 0 <= queued <= 86400:
            t.histogram('task_queue_seconds', queued, attrs)
    except Exception:
        pass


@signals.task_postrun.connect(weak=False)
def after_task(state=None, **_):
    scope = _scope.get()
    if scope:
        manager, started, attrs = scope
        attrs = {**attrs, 'outcome': 'ok' if state == 'SUCCESS' else 'error'}
        t.counter('tasks', attributes=attrs)
        t.histogram('task_seconds', time.monotonic() - started, attrs)
        if state != 'SUCCESS':
            t.event('task.finished', attrs)
        manager.__exit__(None, None, None)
        _scope.set(None)


@signals.heartbeat_sent.connect(weak=False)
def heartbeat(**_):
    t.gauge('worker_heartbeat_timestamp_seconds', [(time.time(), {})])


@signals.worker_process_init.connect(weak=False)
def worker_init(**_):
    t.get_state()
