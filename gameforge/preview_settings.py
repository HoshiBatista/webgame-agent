from . import settings as base_settings
from .settings import *  # noqa: F403

ROOT_URLCONF = "gameforge.preview_urls"
# Preview never initializes sessions or authentication, nor sets their cookies.
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware"]

INSTALLED_APPS = [
    app
    for app in base_settings.INSTALLED_APPS
    if app not in ("django.contrib.admin", "django.contrib.messages")
]
