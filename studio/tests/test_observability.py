import io
import uuid
from unittest.mock import patch

import psycopg
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from psycopg import sql

from gameforge import telemetry
from studio.management.commands import observability_role
from studio.models import Budget, Chat, User
from studio.observability import collect_database
from studio.services import budget_snapshot, create_run


@pytest.mark.django_db
def test_empty_budget_read_does_not_materialize_budget():
    assert not Budget.objects.exists()
    with CaptureQueriesContext(connection) as queries:
        state = budget_snapshot(create=False)
    assert state['spent_usd'] == state['reserved_usd'] == state['unknown_usd'] == 0
    assert not Budget.objects.exists()
    assert not any('INSERT' in q['sql'] or 'UPDATE' in q['sql'] for q in queries)


@pytest.mark.django_db
def test_trace_is_saved_outside_model_contract(monkeypatch, settings):
    settings.GAMEFORGE_PROVIDER = 'fake'
    settings.GAMEFORGE_MODEL = 'fixture'
    chat = Chat.objects.create(owner=User.objects.create_user(username='tracing'))
    context = {'traceparent': '00-' + 'a' * 32 + '-' + 'b' * 16 + '-01'}
    monkeypatch.setattr(telemetry, 'capture', lambda: context)
    with patch('studio.services.schedule'):
        run = create_run(chat, {'prompt': 'small game', 'idempotency_key': 'trace'})
    run.refresh_from_db()
    assert run.trace_context == context
    # Contract/fingerprint only contains the existing generation inputs.
    import inspect

    from studio.tasks import request_for
    assert 'trace_context' not in inspect.getsource(request_for)


@pytest.mark.django_db(transaction=True)
def test_monitoring_role_cannot_read_private_data_or_write(tmp_path, monkeypatch):
    role = 'gf_test_metrics_' + uuid.uuid4().hex[:12]
    monkeypatch.setattr(observability_role, 'ROLE', role)
    secret = tmp_path / 'password'
    secret.write_text(uuid.uuid4().hex)
    call_command('observability_role', password_file=str(secret), stdout=io.StringIO())
    cfg = connection.settings_dict
    try:
        with psycopg.connect(dbname=cfg['NAME'], host=cfg['HOST'], port=cfg['PORT'], user=role,
                             password=secret.read_text(), autocommit=True) as monitor:
            assert monitor.execute('SHOW default_transaction_read_only').fetchone()[0] == 'on'
            monitor.execute('SELECT cost_usd, reservation_usd FROM studio_invocation')
            for query in ['SELECT prompt FROM studio_run', 'SELECT request FROM studio_invocation',
                          'SELECT notes FROM studio_preference', 'SELECT response FROM studio_feedbackprocessing']:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    monitor.execute(query)
            monitor.execute('SET default_transaction_read_only=off')
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                monitor.execute('INSERT INTO studio_budget (id,limit_usd) VALUES (1,999)')
        # Reconfiguration is idempotent, but a widened role is rejected.
        call_command('observability_role', password_file=str(secret), stdout=io.StringIO())
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('GRANT pg_read_all_data TO {}').format(sql.Identifier(role)))
        with pytest.raises(CommandError, match='inherited privileges'):
            call_command('observability_role', password_file=str(secret), stdout=io.StringIO())
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('REVOKE pg_read_all_data FROM {}').format(sql.Identifier(role)))
        # Exercise the exact ORM snapshot with the restricted role, no provider/Redis required.
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
        try:
            from django.db import transaction
            with transaction.atomic(), patch('gameforge.telemetry.gauge') as gauge:
                collect_database()
            assert any(call.args[0] == 'budget_unknown_usd' for call in gauge.call_args_list)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('RESET ROLE')
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            cursor.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
