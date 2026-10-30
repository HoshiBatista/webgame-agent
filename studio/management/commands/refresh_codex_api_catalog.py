from django.core.management.base import BaseCommand, CommandError

from generation.providers.codex_api import refresh_catalog


class Command(BaseCommand):
    help = "Refresh the non-secret Pro API catalog. Does not submit a model job."

    def handle(self, *args, **options):
        try:
            snapshot = refresh_catalog()
        except Exception as exc:
            raise CommandError(f"Pro API catalog unavailable ({type(exc).__name__})") from None
        self.stdout.write("Pro API catalog saved: " + ", ".join(item["id"] for item in snapshot["models"]))
