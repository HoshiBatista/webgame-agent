import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == "replace-with-a-random-secret":
    raise ImproperlyConfigured("Set a private random DJANGO_SECRET_KEY in .env before starting GameForge.")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "studio",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "gameforge.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "web" / "dist"],
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
WSGI_APPLICATION = "gameforge.wsgi.application"
_db = urlparse(os.environ.get("DATABASE_URL", "postgresql:///gameforge_mini"))
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db.path.lstrip("/") or "gameforge_mini",
        "USER": unquote(_db.username or ""),
        "PASSWORD": unquote(_db.password or ""),
        "HOST": _db.hostname or "",
        "PORT": _db.port or "",
        "CONN_MAX_AGE": 60,
    }
}
AUTH_USER_MODEL = "studio.User"
AUTHENTICATION_BACKENDS = ["studio.auth.CaseInsensitiveBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}}
]
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "/assets/"
STATIC_ROOT = BASE_DIR / ".data" / "static"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SECURE_COOKIES", "0") == "1"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
# Enable only behind an ingress that replaces this header and keeps app ports private.
if os.environ.get("DJANGO_TRUST_PROXY_HEADERS", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "0") == "1"
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173",
).split(",")
CSRF_FAILURE_VIEW = "studio.views.csrf_failure"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "studio.views.exception_handler",
    "UNAUTHENTICATED_USER": None,
}
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:56379/0")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_IGNORE_RESULT = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_PUBLISH_RETRY = False
CELERY_BROKER_CONNECTION_TIMEOUT = 2
CELERY_BEAT_SCHEDULE = {
    "outbox": {"task": "studio.tasks.dispatch_outbox", "schedule": 2.0, "options": {"expires": 2}},
    "recover": {"task": "studio.tasks.recover_expired", "schedule": 15.0, "options": {"expires": 15}},
    "relay-cancel": {"task": "studio.tasks.reconcile_relay_cancellations", "schedule": 15.0,
                     "options": {"expires": 15}},
    "codex-api-catalog": {"task": "studio.tasks.refresh_codex_api_catalog", "schedule": 60.0,
                          "options": {"expires": 60}},
}
GAMEFORGE_PROVIDER = os.environ.get("GAMEFORGE_PROVIDER", "fake")
GAMEFORGE_MODEL = os.environ.get("GAMEFORGE_MODEL") or (
    "fixture"
    if GAMEFORGE_PROVIDER == "fake"
    else (os.environ.get("GAMEFORGE_VLLM_MODEL") or os.environ.get("LLM_MODEL", ""))
    if GAMEFORGE_PROVIDER in {"vllm", "relay"}
    else "gpt-6-sol" if GAMEFORGE_PROVIDER == "codex_api" else "gpt-6-luna"
)
GAMEFORGE_PREVIEW_ORIGIN = os.environ.get("GAMEFORGE_PREVIEW_ORIGIN", "http://localhost:8001").rstrip("/")
GAMEFORGE_APP_ORIGIN = os.environ.get("GAMEFORGE_APP_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
GAMEFORGE_BUDGET_USD = os.environ.get("GAMEFORGE_BUDGET_USD", "50")
GAMEFORGE_PROVIDER_CONCURRENCY = int(os.environ.get("GAMEFORGE_PROVIDER_CONCURRENCY", "1"))
GAMEFORGE_CODEX_API_CONCURRENCY = int(os.environ.get("GAMEFORGE_CODEX_API_CONCURRENCY", "2"))
if not 1 <= GAMEFORGE_CODEX_API_CONCURRENCY <= 4:
    raise ValueError("GAMEFORGE_CODEX_API_CONCURRENCY must be between 1 and 4")
GAMEFORGE_MAX_REPAIR_ATTEMPTS = int(os.environ.get("GAMEFORGE_MAX_REPAIR_ATTEMPTS", "3"))
GAMEFORGE_COMPACT_LITE_ENABLED = os.environ.get("GAMEFORGE_COMPACT_LITE_ENABLED", "0") == "1"
if GAMEFORGE_MAX_REPAIR_ATTEMPTS not in (2, 3):
    raise ValueError("GAMEFORGE_MAX_REPAIR_ATTEMPTS must be 2 or 3")
GAMEFORGE_LEASE_SECONDS = int(os.environ.get("GAMEFORGE_LEASE_SECONDS", "45"))
GAMEFORGE_LOCAL_ONLY = os.environ.get("GAMEFORGE_LOCAL_ONLY", "1") == "1"
# Pro is opt-in. The default remains local-only; a trusted cloud installation
# must separately allow exact existing account IDs, never every logged-in visitor.
GAMEFORGE_PRO_ENABLED = os.environ.get("GAMEFORGE_PRO_ENABLED", "0") == "1"
GAMEFORGE_PRO_PROVIDER = os.environ.get(
    "GAMEFORGE_PRO_PROVIDER", "codex_api" if GAMEFORGE_PROVIDER == "codex_api" else "codex"
)
if GAMEFORGE_PRO_PROVIDER not in {"codex", "codex_api"}:
    raise ValueError("GAMEFORGE_PRO_PROVIDER must be codex or codex_api")
GAMEFORGE_PRO_ACCESS = os.environ.get("GAMEFORGE_PRO_ACCESS", "local")
if GAMEFORGE_PRO_ACCESS not in {"local", "restricted"}:
    raise ValueError("GAMEFORGE_PRO_ACCESS must be local or restricted")
GAMEFORGE_PRO_USER_IDS = frozenset(
    int(value.strip()) for value in os.environ.get("GAMEFORGE_PRO_USER_IDS", "").split(",") if value.strip()
)
GAMEFORGE_LITE_PROVIDER = os.environ.get("GAMEFORGE_LITE_PROVIDER", "")
GAMEFORGE_LITE_MODEL = os.environ.get("GAMEFORGE_LITE_MODEL", "")
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# Dedicated logger stays visible even when Celery's root log level is WARNING.
# Only numeric/timing/protocol metadata is passed to this formatter; never prompt/key/body.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"transport": {"()": "generation.transport_diagnostics.TransportLogFormatter"}},
    "handlers": {"transport": {"class": "logging.StreamHandler", "formatter": "transport", "level": "INFO"}},
    "loggers": {"generation.transport": {"handlers": ["transport"], "level": "INFO", "propagate": False}},
}
if transport_log := os.environ.get("GAMEFORGE_TRANSPORT_LOG"):
    LOGGING["handlers"]["transport"] = {
        "class": "logging.handlers.RotatingFileHandler", "formatter": "transport", "level": "INFO",
        "filename": transport_log, "maxBytes": 5 * 1024 * 1024, "backupCount": 5, "encoding": "utf-8",
    }

# Share one rotating handler with direct transport diagnostics.
LOGGING["loggers"]["generation.relay_api"] = {
    "handlers": ["transport"], "level": "INFO", "propagate": False,
}
