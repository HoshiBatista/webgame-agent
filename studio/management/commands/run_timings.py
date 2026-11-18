"""Read-only timing report for a saved or active generation."""

import json
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from studio.models import Run
from studio.run_timings import run_timings


class Command(BaseCommand):
    help = "Show elapsed times for the queue, model roles, packaging and validation."

    def add_arguments(self, parser):
        parser.add_argument("run_id", type=UUID)

    def handle(self, *args, **options):
        try:
            run = Run.objects.get(pk=options["run_id"])
        except Run.DoesNotExist as exc:
            raise CommandError("Generation not found.") from exc
        calls = run.invocations.only("attempt", "state", "sent_at", "finished_at", "request").order_by("attempt")
        self.stdout.write(json.dumps(run_timings(run, calls), indent=2, ensure_ascii=False))
