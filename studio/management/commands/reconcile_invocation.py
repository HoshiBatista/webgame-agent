from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from studio.models import Invocation
from studio.services import usage_cost


class Command(BaseCommand):
    help = (
        "Reconcile an unknown provider request from independently checked usage; never retries the request."
    )

    def add_arguments(self, parser):
        parser.add_argument("invocation_id")
        parser.add_argument("--input", type=int, required=True)
        parser.add_argument("--cached", type=int, required=True)
        parser.add_argument("--output", type=int, required=True)
        parser.add_argument("--evidence", required=True)

    def handle(self, *args, **o):
        with transaction.atomic():
            inv = Invocation.objects.select_for_update().get(pk=o["invocation_id"])
            if inv.state != "unknown":
                raise CommandError("Only unresolved invocations may be reconciled.")
            usage = {
                "input_tokens": o["input"],
                "cached_input_tokens": o["cached"],
                "output_tokens": o["output"],
            }
            cost = usage_cost(usage, inv.price)
            if cost is None:
                raise CommandError("Usage or price invalid.")
            inv.usage = usage
            inv.cost_usd = cost
            inv.state = "settled"
            inv.finished_at = timezone.now()
            inv.error = {**(inv.error or {}), "reconciliation_evidence": o["evidence"]}
            inv.save()
            run = inv.run
            if run.status == "unknown":
                run.status = "failed"
                run.message = "Расход сверен. Можно продолжить с сохранённого черновика."
                run.error = {"code": "reconciled", "message": run.message}
                run.save()
        self.stdout.write("Usage reconciled; no model request sent.")
