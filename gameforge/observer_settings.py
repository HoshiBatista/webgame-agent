"""Dedicated settings: password file, read-only PG role, no end-user/model credentials."""
import os
from pathlib import Path

from .settings import *  # noqa: F403

DATABASES['default'].update(  # noqa: F405
    USER='gameforge_metrics',
    PASSWORD=Path(os.environ.get('GAMEFORGE_METRICS_DB_PASSWORD_FILE', '/run/secrets/metrics_db_password')).read_text().strip(),
    OPTIONS={'options': '-c default_transaction_read_only=on -c statement_timeout=5000'},
)
