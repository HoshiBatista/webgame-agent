import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from generation.errors import ContractError
from studio.analytics import import_dataset


class Command(BaseCommand):
    help = "Load the versioned demonstration dataset; never calls a model."

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / "data" / "analytics-demo-v1.json"
        try:
            dataset, created = import_dataset(json.loads(path.read_text()))
        except (ValueError, IntegrityError, ContractError) as exc:
            raise CommandError(f"Набор не активирован: {exc}") from exc
        self.stdout.write(f"Demo analytics {'imported' if created else 'already loaded'}: {dataset.payload_hash}")
