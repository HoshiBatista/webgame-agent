"""Complete durable candidate intents after coordinator interruption."""

import json

from django.core.management.base import BaseCommand, CommandError

from prompt2play.adapters.django.forge.workflow import recover_pending


class Command(BaseCommand):
    help = "Recover immutable artifact commits; never retry model invocations."

    def handle(self, *args, **options):
        result = recover_pending()
        self.stdout.write(json.dumps(result))
        if result["errors"]:
            raise CommandError("Some pending artifacts require operator investigation.")
