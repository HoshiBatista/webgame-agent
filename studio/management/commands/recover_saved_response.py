import json

from django.core.management.base import BaseCommand, CommandError

from generation.errors import GenerationError
from studio.models import Invocation
from studio.recovery import recover_saved_response
from studio.services import DomainError


class Command(BaseCommand):
    help = "Validate a stored reply; --apply saves a candidate and checks it with model calls forbidden."

    def add_arguments(self, parser):
        parser.add_argument("invocation_id")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = recover_saved_response(options["invocation_id"], apply=options["apply"])
        except (DomainError, GenerationError, Invocation.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False))
