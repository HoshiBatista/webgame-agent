"""Dedicated preview listener with no sessions, authentication or API routes."""

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

if PREVIEW_ORIGIN == APP_ORIGIN:  # noqa: F405
    raise ImproperlyConfigured("Preview origin must differ from the coordinator origin.")
ROOT_URLCONF = "prompt2play.adapters.django.config.preview_urls"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "prompt2play.adapters.django.forge",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "prompt2play.adapters.django.forge.preview.IsolationMiddleware",
]
WHITENOISE_ROOT = None
SECURE_SSL_REDIRECT = False
