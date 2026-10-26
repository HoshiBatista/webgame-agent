"""Read stored transport metadata without revealing prompts, responses or credentials."""

import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from studio.models import Invocation


class Command(BaseCommand):
    help = "Show private transport diagnostics for one invocation, or the latest API invocation. No API calls."

    def add_arguments(self, parser):
        parser.add_argument("invocation_id", nargs="?")

    def handle(self, *args, **options):
        rows = Invocation.objects.filter(run__provider__in=["vllm", "relay", "codex_api"])
        if options["invocation_id"]:
            try:
                ident = uuid.UUID(options["invocation_id"])
            except ValueError as exc:
                raise CommandError("Expected an invocation UUID") from exc
            rows = rows.filter(pk=ident)
        inv = rows.order_by("-created_at").first()
        if inv is None:
            raise CommandError("No matching API invocation")
        metadata = inv.provider_metadata or {}
        result = {
            "invocation_id": str(inv.id), "run_id": str(inv.run_id), "state": inv.state,
            "sent_at": inv.sent_at.isoformat() if inv.sent_at else None,
            "finished_at": inv.finished_at.isoformat() if inv.finished_at else None,
            "elapsed_seconds": inv.elapsed_seconds, "error_code": (inv.error or {}).get("code"),
            "metadata": {key: metadata[key] for key in ("trace_id", "request_id", "transport_error", "transport",
                                                      "relay_job_id", "relay_wait", "relay_cancel_wait", "inference_seconds",
                                                      "codex_api_job_id", "codex_api_wait", "codex_api_cancel_wait", "receipt_hash",
                                                      "first_output_seconds")
                         if key in metadata},
        }
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
