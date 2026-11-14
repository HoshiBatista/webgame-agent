"""Create/update a metadata-only PostgreSQL login from a mounted secret."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from psycopg import sql

from studio.observability import MONITOR_COLUMNS

ROLE = 'gameforge_metrics'


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--password-file', default='/run/secrets/metrics_db_password')

    @transaction.atomic
    def handle(self, *args, **options):
        password = Path(options['password_file']).read_text().strip()
        if len(password) < 24:
            raise CommandError('Monitoring password must be at least 24 characters.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=%s', [ROLE])
            existing = cursor.fetchone()
            if existing and any(existing):
                raise CommandError('Refusing to reuse a privileged monitoring role.')
            if not existing:
                cursor.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(ROLE)))
            cursor.execute('SELECT parent.rolname FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid '
                           'JOIN pg_roles child ON child.oid=m.member WHERE child.rolname=%s', [ROLE])
            if any(name != 'pg_monitor' for (name,) in cursor.fetchall()):
                raise CommandError('Monitoring role has unexpected inherited privileges.')
            cursor.execute('SELECT EXISTS(SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s))', [ROLE])
            if cursor.fetchone()[0]:
                raise CommandError('Monitoring role owns database objects; refusing to reuse it.')
            # Literal quoting by psycopg, never shell interpolation or a printed password.
            cursor.execute(sql.SQL('ALTER ROLE {} PASSWORD {} CONNECTION LIMIT 3').format(sql.Identifier(ROLE), sql.Literal(password)))
            cursor.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only = on').format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL('ALTER ROLE {} SET statement_timeout = \'5s\'').format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(connection.settings_dict['NAME']), sql.Identifier(ROLE)))
            cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL('GRANT pg_monitor TO {}').format(sql.Identifier(ROLE)))
            for table, columns in MONITOR_COLUMNS.items():
                cursor.execute(sql.SQL('REVOKE ALL ON {} FROM {}').format(sql.Identifier(table), sql.Identifier(ROLE)))
                cursor.execute(sql.SQL('GRANT SELECT ({}) ON {} TO {}').format(
                    sql.SQL(', ').join(map(sql.Identifier, columns)), sql.Identifier(table), sql.Identifier(ROLE)))
            cursor.execute("SELECT c.relname, a.attname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "JOIN pg_attribute a ON a.attrelid=c.oid WHERE n.nspname='public' AND c.relkind IN ('r','p') "
                           "AND a.attnum>0 AND NOT a.attisdropped AND has_column_privilege(%s,c.oid,a.attnum,'SELECT')", [ROLE])
            if any(column not in MONITOR_COLUMNS.get(table, ()) for table, column in cursor.fetchall()):
                raise CommandError('Monitoring role can read private columns through existing grants; refusing configuration.')
            cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname='public' AND c.relkind IN ('r','p') "
                           "AND has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))", [ROLE])
            if cursor.fetchone()[0]:
                raise CommandError('Monitoring role has write privileges; refusing configuration.')
        self.stdout.write('Metadata-only monitoring role configured.')
