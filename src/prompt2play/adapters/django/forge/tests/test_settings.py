import os
import runpy
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase


class DatabaseConfigurationTests(SimpleTestCase):
    def load(self, **environment):
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(Path(settings.BASE_DIR) / "config" / "settings.py"))

    def test_postgres_components_preserve_literal_password(self):
        database = self.load(
            DB_HOST="database",
            DB_PORT="5433",
            DB_NAME="prompt2play.adapters.django.forge",
            DB_USER="builder",
            DB_PASSWORD="test:@/#%password",
        )["DATABASES"]["default"]
        self.assertEqual(database["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(database["HOST"], "database")
        self.assertEqual(database["PORT"], "5433")
        self.assertEqual(database["NAME"], "forge")
        self.assertEqual(database["USER"], "builder")
        self.assertEqual(database["PASSWORD"], "test:@/#%password")

    def test_explicit_url_takes_precedence_and_blank_url_uses_sqlite(self):
        database = self.load(DB_HOST="database", DATABASE_URL="sqlite:////tmp/override.sqlite3")[
            "DATABASES"
        ]["default"]
        self.assertEqual(database["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(database["NAME"], "/tmp/override.sqlite3")
        database = self.load(DATABASE_URL="", DJANGO_DB_PATH="/tmp/local.sqlite3")["DATABASES"][
            "default"
        ]
        self.assertEqual(database["NAME"], "/tmp/local.sqlite3")

    def test_shared_deployment_requires_secret_and_defaults_secure_cookies(self):
        with self.assertRaises(ImproperlyConfigured):
            self.load(DJANGO_DEBUG="0")
        configured = self.load(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="test-secret")
        self.assertTrue(configured["SESSION_COOKIE_SECURE"])
        self.assertTrue(configured["CSRF_COOKIE_SECURE"])
