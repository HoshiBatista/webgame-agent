"""Receipts and retry consent survive model-free steps in a continuation chain."""

from django.db.models import Case, IntegerField, Q, When

from .models import Invocation, Run, RunEvent


def lineage_ids(run):
    """Nearest first, confined to the same chat; a damaged cycle cannot loop forever."""
    parents = dict(Run.objects.filter(chat_id=run.chat_id).values_list("id", "continued_from_id"))
    seen = set()
    ident = run.id
    while ident in parents and ident not in seen:
        seen.add(ident)
        yield ident
        ident = parents[ident]


def delivery_state(run):
    """One receipt snapshot: sent → unknown cannot fall between two admission queries."""
    runs = list(lineage_ids(run))
    acknowledged, legacy_runs = set(), set()
    for details in RunEvent.objects.filter(run__in=runs, kind="explicit_retry").values_list("details", flat=True):
        if "unknown_invocation_ids" in details:
            acknowledged.update(details["unknown_invocation_ids"])
        elif details.get("previous_run_id"):
            # Older consent covered only the immediate parent's unknown calls.
            legacy_runs.add(details["previous_run_id"])
    calls = list(Invocation.objects.filter(run__in=runs, state__in=["unknown", "reserved", "sent"])
                 .only("id", "run_id", "state"))
    unknown = [call for call in calls if call.state == "unknown" and str(call.id) not in acknowledged
               and str(call.run_id) not in legacy_runs]
    inflight = [call for call in calls if call.run_id != run.id and call.state in {"reserved", "sent"}]
    return unknown, inflight


def unacknowledged_unknowns(run):
    return delivery_state(run)[0]


def pending_invocations(run, base, *, states=("reserved", "sent", "returned")):
    """Use only the exact candidate base; a durable source restart cuts off old replies."""
    runs = list(lineage_ids(run)) if run.allow_model_calls else [run.id]
    barriers = set(RunEvent.objects.filter(run__in=runs, kind="source_restart").values_list("run_id", flat=True))
    eligible = []
    for ident in runs:
        eligible.append(ident)
        if ident in barriers:
            break
    base_id = str(base.id) if base else None
    exact_base = Q(request__base_revision=base_id)
    if base is None:
        exact_base |= Q(request__base_revision__isnull=True)
    ordering = Case(*[When(run_id=ident, then=position) for position, ident in enumerate(eligible)],
                    output_field=IntegerField())
    return Invocation.objects.filter(exact_base, run_id__in=eligible, state__in=states, revision__isnull=True) \
        .annotate(continuation_order=ordering).order_by("continuation_order", "attempt")


def returned_response(run, base):
    return pending_invocations(run, base, states=("returned",)).first()
