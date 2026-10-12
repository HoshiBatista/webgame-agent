"""One installation is one trusted team. Configuration comes from environment."""

import os
from copy import deepcopy
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from django.utils.log import DEFAULT_LOGGING
from prompt2play.adapters.django.forge.middleware import static_headers
from prompt2play.paths import RESOURCE_ROOT

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
DEBUG = os.environ.get("DJANGO_DEBUG", "1").lower() in {"1", "true", "yes"}
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.")
    SECRET_KEY = "game-forge-local-development-only-replace-before-sharing"


def csv_env(name, default=""):
    return [part.strip() for part in os.environ.get(name, default).split(",") if part.strip()]


ALLOWED_HOSTS = csv_env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = csv_env("DJANGO_CSRF_TRUSTED_ORIGINS")
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "prompt2play.adapters.django.forge",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "prompt2play.adapters.django.forge.middleware.APIResponseMiddleware",
]
ROOT_URLCONF = "prompt2play.adapters.django.config.urls"
WSGI_APPLICATION = "prompt2play.adapters.django.config.wsgi.application"
ASGI_APPLICATION = "prompt2play.adapters.django.config.asgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
DATA_DIR = Path(
    os.environ.get("PROMPT2PLAY_DATA_DIR", str(Path.cwd() / ".prompt2play"))
).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_ROOT = Path(os.environ.get("PROMPT2PLAY_ARTIFACT_ROOT", str(DATA_DIR / "artifacts")))
PREVIEW_ORIGIN = os.environ.get("PROMPT2PLAY_PREVIEW_ORIGIN", "http://127.0.0.1:8001").rstrip("/")
APP_ORIGIN = os.environ.get("PROMPT2PLAY_APP_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
db_path = Path(os.environ.get("DJANGO_DB_PATH", str(DATA_DIR / "db.sqlite3"))).expanduser()
database_url = os.environ.get("DATABASE_URL", "").strip()
if not database_url and os.environ.get("DB_HOST"):
    # Compose/operator secrets are literal values, not URL components: @:/#%
    # in a password must survive without percent-encoding requirements.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["DB_HOST"],
            "PORT": os.environ.get("DB_PORT", "5432"),
            "NAME": os.environ.get("DB_NAME", "gameforge"),
            "USER": os.environ.get("DB_USER", "gameforge"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": dj_database_url.parse(
            database_url or f"sqlite:///{db_path}",
            conn_max_age=0,
            conn_health_checks=True,
        )
    }
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 20
AUTH_USER_MODEL = "forge.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = DATA_DIR / "staticfiles"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
local_dist = Path.cwd() / "web" / "dist"
default_dist = local_dist if (local_dist / "index.html").is_file() else RESOURCE_ROOT / "studio"
FRONTEND_DIST = Path(os.environ.get("PROMPT2PLAY_WEB_DIST", str(default_dist)))
WHITENOISE_ROOT = FRONTEND_DIST
WHITENOISE_INDEX_FILE = False  # / is served by Django with the parent preview CSP.
WHITENOISE_MAX_AGE = 3600
WHITENOISE_ADD_HEADERS_FUNCTION = static_headers
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# App-specific names avoid collisions with other Django apps on the same host.
SESSION_COOKIE_NAME = "prompt2play_sessionid"
CSRF_COOKIE_NAME = "prompt2play_csrftoken"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_PATH = "/api/"
CSRF_COOKIE_PATH = "/api/"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SECURE_COOKIES", "0" if DEBUG else "1").lower() in {
    "1",
    "true",
    "yes",
}
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_FAILURE_VIEW = "prompt2play.adapters.django.forge.errors.csrf_failure"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
# Enable only when a trusted reverse proxy overwrites this header.
if os.environ.get("DJANGO_TRUST_PROXY", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "0") == "1"
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "prompt2play.adapters.django.forge.authentication.TeamSessionAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["prompt2play.adapters.django.forge.parsers.BoundedJSONParser"],
    "EXCEPTION_HANDLER": "prompt2play.adapters.django.forge.errors.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"team": "1200/min", "worker": "1200/min", "login": "30/min"},
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}
FORGE_LEASE_SECONDS = 120
FORGE_PIPELINE_VERSION = os.environ.get("PROMPT2PLAY_PIPELINE_VERSION", "legacy-v1")

# Preserve Django's normal error handlers; sanitize before every handler can emit
# a scoped preview URL. Dedicated preview settings inherit this configuration.
LOGGING = deepcopy(DEFAULT_LOGGING)
LOGGING["filters"]["preview_token"] = {
    "()": "prompt2play.adapters.django.forge.log_filters.PreviewTokenFilter"
}
LOGGING["formatters"]["preview_errors"] = {
    "()": "prompt2play.adapters.django.forge.log_filters.PreviewExceptionFormatter"
}
LOGGING["formatters"]["django.server"]["()"] = (
    "prompt2play.adapters.django.forge.log_filters.PreviewServerFormatter"
)
LOGGING["handlers"]["console"]["formatter"] = "preview_errors"
LOGGING["handlers"]["auth_audit"] = {
    "class": "logging.StreamHandler",
    "formatter": "preview_errors",
}
LOGGING["loggers"]["prompt2play.auth"] = {
    "handlers": ["auth_audit"],
    "level": "WARNING",
    "propagate": False,
}
for logging_handler in LOGGING["handlers"].values():
    logging_handler.setdefault("filters", []).append("preview_token")
LOGGING["loggers"]["django.server"]["filters"] = ["preview_token"]
LOGGING["loggers"]["django.request"] = {
    "filters": ["preview_token"],
    "propagate": True,
}
DEFAULT_EXCEPTION_REPORTER_FILTER = (
    "prompt2play.adapters.django.forge.log_filters.PreviewExceptionReporterFilter"
)
DEFAULT_EXCEPTION_REPORTER = (
    "prompt2play.adapters.django.forge.log_filters.PreviewExceptionReporter"
)
