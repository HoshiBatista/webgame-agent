from django.apps import AppConfig


class StudioConfig(AppConfig):
    name = "studio"

    def ready(self):
        from gameforge import telemetry_signals  # noqa: F401
