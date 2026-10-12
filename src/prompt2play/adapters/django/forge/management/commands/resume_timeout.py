"""Resume one failed local timeout, preserving all spending and saved answers."""

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import APIException

from prompt2play.adapters.django.forge.models import Job
from prompt2play.adapters.django.forge.timeout_recovery import resume_timeout


class Command(BaseCommand):
    help = "Resume an eligible Codex timeout once; permits a new budgeted model call."

    def add_arguments(self, parser):
        parser.add_argument("job_id")

    def handle(self, *args, **options):
        try:
            job = resume_timeout(options["job_id"])
        except (APIException, ValueError, Job.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Resumed {job.pk}; spending, reservations and completed answers retained."
        )
