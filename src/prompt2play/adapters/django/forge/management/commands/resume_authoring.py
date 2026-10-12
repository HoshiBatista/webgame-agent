"""Continue a generation blocked by an obsolete operation/turn limit."""

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import APIException

from prompt2play.adapters.django.forge.authoring_recovery import resume_authoring
from prompt2play.adapters.django.forge.models import Job


class Command(BaseCommand):
    help = "Recover saved authoring progress from an obsolete limit; preserve the original budget."

    def add_arguments(self, parser):
        parser.add_argument("job_id")

    def handle(self, *args, **options):
        try:
            job = resume_authoring(options["job_id"])
        except (APIException, ValueError, Job.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Resumed {job.pk} from its saved draft; original ledger retained.")
