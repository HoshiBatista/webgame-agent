"""Read-only operational snapshots. Select metadata columns explicitly; never game/model data."""
import os
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import redis
from django.conf import settings
from django.db import connection
from django.db.models import Count, Min
from django.utils import timezone

from gameforge import telemetry as t

from .models import FeedbackProcessing, Invocation, Outbox, Run, ValidationTask
from .services import budget_snapshot

# Least privilege: not table-level SELECT. Updating this list requires privacy/role tests.
MONITOR_COLUMNS = {
    'studio_budget': ('id', 'limit_usd'),
    'studio_run': ('id', 'provider', 'model_profile', 'operation', 'status', 'created_at', 'lease_until'),
    'studio_invocation': ('id', 'state', 'run_id', 'cost_usd', 'reservation_usd', 'sent_at'),
    'studio_feedbackprocessing': ('id', 'status', 'invocation_state', 'cost_usd', 'reservation_usd', 'lease_until'),
    'studio_validationtask': ('id', 'status', 'origin', 'lease_until'),
    'studio_outbox': ('id', 'run_id', 'created_at', 'dispatched_at'),
}


def grouped(model, fields, attributes):
    return [(row['n'], {target: row[source] for source, target in attributes.items()})
            for row in model.objects.values(*fields).annotate(n=Count('id')).order_by()]


def collect_database():
    now = timezone.now()
    # One snapshot for all ledger buckets, including an uninitialised (empty) budget.
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    budget = budget_snapshot(create=False)
    t.gauge('runs', grouped(Run, ['provider', 'model_profile', 'operation', 'status'],
            {'provider': 'provider', 'model_profile': 'profile', 'operation': 'operation', 'status': 'status'}))
    t.gauge('invocations', grouped(Invocation, ['state'], {'state': 'status'}))
    t.gauge('feedback_jobs', grouped(FeedbackProcessing, ['status'], {'status': 'status'}))
    t.gauge('validation_jobs', grouped(ValidationTask, ['status', 'origin'], {'status': 'status', 'origin': 'source'}))
    for key, value in budget.items():
        t.gauge('budget_' + key, [(value, {})])
    pending = Outbox.objects.filter(run__status='queued')
    oldest = pending.aggregate(n=Min('created_at'))['n']
    t.gauge('outbox_pending', [(pending.count(), {})])
    t.gauge('outbox_oldest_seconds', [(max(0, (now - oldest).total_seconds()) if oldest else 0, {})])
    oldest = Run.objects.filter(status='queued').aggregate(n=Min('created_at'))['n']
    t.gauge('run_oldest_queued_seconds', [(max(0, (now - oldest).total_seconds()) if oldest else 0, {})])
    expired = Run.objects.filter(status__in=Run.ACTIVE, lease_until__lt=now).count()
    expired += ValidationTask.objects.filter(status__in=ValidationTask.ACTIVE, lease_until__lt=now).count()
    expired += FeedbackProcessing.objects.filter(status__in=['queued', 'processing', 'waiting'], lease_until__lt=now).count()
    t.gauge('expired_leases', [(expired, {})])
    with connection.cursor() as cursor:
        cursor.execute("SELECT state, count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' GROUP BY state")
        t.gauge('postgres_connections', [(count, {'state': state}) for state, count in cursor.fetchall()])
        cursor.execute("SELECT current_setting('max_connections')::integer, pg_database_size(current_database())")
        maximum, size = cursor.fetchone()
        t.gauge('postgres_max_connections', [(maximum, {})])
        t.gauge('postgres_database_bytes', [(size, {})])
        cursor.execute('SELECT deadlocks, xact_commit, xact_rollback, blks_hit, blks_read FROM pg_stat_database WHERE datname = current_database()')
        for name, value in zip(['deadlocks', 'commits', 'rollbacks', 'cache_hits', 'disk_reads'], cursor.fetchone()):
            t.gauge('postgres_' + name, [(value, {})])
    t.gauge('state_snapshot_timestamp_seconds', [(time.time(), {})])


def collect_redis():
    client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1, socket_timeout=1)
    try:
        info = client.info()
        for name, key in [('memory_used_bytes', 'used_memory'), ('memory_max_bytes', 'maxmemory'),
                          ('clients', 'connected_clients'), ('blocked_clients', 'blocked_clients'),
                          ('evicted_keys', 'evicted_keys'), ('hits', 'keyspace_hits'),
                          ('misses', 'keyspace_misses'), ('commands', 'total_commands_processed')]:
            t.gauge('redis_' + name, [(info.get(key, 0), {})])
        count = sum(client.llen('celery' + suffix) for suffix in ['', '\x06\x163', '\x06\x166', '\x06\x169'])
        t.gauge('redis_queue_messages', [(count, {})])
    finally:
        client.close()


def collect_probes():
    from validation.service import environment_identity

    try:
        up = not environment_identity().endswith(':unavailable')
    except Exception:
        up = False
    t.gauge('dependency_up', [(int(up), {'dependency': 'validator'})], replace=False)
    # Only fixed internal targets. No cookies/credentials, redirects or arbitrary URL parameters.
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    opener = build_opener(ProxyHandler({}), NoRedirect())
    for name, url in [('app', os.environ.get('GAMEFORGE_OBSERVER_APP_URL', 'http://app:8000/api/health/')),
                      ('preview', os.environ.get('GAMEFORGE_OBSERVER_PREVIEW_URL', 'http://preview:8000/health/'))]:
        try:
            with opener.open(Request(url, headers={'X-Forwarded-Proto': 'https'}), timeout=2) as response:
                status = response.status
            up = status == 200
        except Exception:
            up = False
        t.gauge('dependency_up', [(int(up), {'dependency': name})], replace=False)


def collect():
    from django.db import transaction

    for name, operation in [('postgres', lambda: _database(transaction)), ('redis', collect_redis)]:
        try:
            operation()
            up = True
        except Exception:
            up = False
            t.event('state.refresh_failed', {'dependency': name})
            connection.close()
        t.gauge('dependency_up', [(int(up), {'dependency': name})], replace=False)
        if name == 'postgres':
            t.gauge('state_collection_success', [(int(up), {})])
    collect_probes()


def _database(transaction):
    with transaction.atomic():
        collect_database()
