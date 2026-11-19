"""Summarize first choices and directly published games in the ordinary Pro four-variant trial."""

import json
from collections import Counter, defaultdict
from uuid import UUID

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Count, F, Prefetch, Q, Sum
from django.db.models.fields.json import KT

from generation.schema import CONTRACT_VERSION
from studio.models import (
    PlaySession,
    Publication,
    PublicationRating,
    VariantAnalyticsExperiment,
    VariantAnalyticsHint,
)
from studio.publication_analytics import MIN_AVERAGED_SESSION_MS


def share(numerator, denominator):
    return numerator / denominator if denominator else None


def public_slots(query, prefix=""):
    run = prefix + "revision__run__"
    return query.filter(**{
        prefix + "unavailable_at__isnull": True,
        prefix + "revision__pipeline_version": CONTRACT_VERSION,
        run + "variant_batch__analytics_experiment__isnull": False,
    }).order_by().values(batch_id=F(run + "variant_batch_id"), slot=F(run + "variant_index"))


def public_outcomes():
    # Each query groups independently so joining sessions and ratings cannot multiply rows.
    publications = public_slots(Publication.objects.all()).annotate(publications=Count("pk"))
    sessions = public_slots(PlaySession.objects.filter(
        revision_id_snapshot=F("publication__revision_id"), artifact_hash=F("publication__revision__artifact_hash"),
    ), "publication__").annotate(
        sessions=Count("pk"), sessions_30s=Count("pk", filter=Q(visible_ms__gte=MIN_AVERAGED_SESSION_MS)),
    )
    # Votes before a publication changed revisions cannot be attributed to its current version.
    ratings = public_slots(PublicationRating.objects.filter(
        updated_at__gte=F("publication__updated_at"),
    ), "publication__").annotate(ratings=Count("pk"), stars=Sum("rating"))
    totals: defaultdict[tuple[UUID, int], Counter[str]] = defaultdict(Counter)
    for rows in (publications, sessions, ratings):
        for row in rows.iterator():
            totals[row.pop("batch_id"), row.pop("slot")].update(row)
    return totals


def outcome_metrics(counts):
    return {
        "publications": counts["publications"], "sessions": counts["sessions"], "sessions_30s": counts["sessions_30s"],
        "share_30s": share(counts["sessions_30s"], counts["sessions"]),
        "ratings": counts["ratings"], "mean_rating": share(counts["stars"], counts["ratings"]),
    }


def assignments(trial):
    # A v1 application can also write these fields during a rollout or after a rollback.
    if trial.protocol_version == 1:
        return {trial.hint_variant_index: trial.legacy_key or "unclassified"} if trial.hint_variant_index else {}
    return {a.variant_index: a.key or "unclassified" for a in trial.assigned_slots}


class Command(BaseCommand):
    help = "Compare first choices with their random baselines and report outcomes of directly published Pro variants."

    def handle(self, *args, **options):
        standalone = transaction.get_autocommit()
        with transaction.atomic():
            if standalone:
                # All grouped queries and prefetched chunks must see the same choices and publications.
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            report = self.build_report()
        self.stdout.write(json.dumps(report, indent=2))

    def build_report(self):
        public = public_outcomes()
        public_by_group: defaultdict[str, Counter[str]] = defaultdict(Counter)
        public_by_mechanic: defaultdict[str, Counter[str]] = defaultdict(Counter)
        mechanics: defaultdict[str, Counter[str]] = defaultdict(Counter)
        cohorts: defaultdict[tuple[int, int], Counter[str]] = defaultdict(
            lambda: Counter(batches=0, all_four_choices=0, hinted_choices=0)
        )
        choices = dict.fromkeys(("opted_in", "without_hint", "assigned_without_choice", "choices_without_ready_snapshot",
                                 "early_choices", "comparable_choices", "hinted_choices"), 0)
        hinted_slots_shown = 0
        slots = VariantAnalyticsHint.objects.only("experiment_id", "variant_index").annotate(key=KT("hint__hint_key"))
        trials = VariantAnalyticsExperiment.objects.only(
            "batch_id", "protocol_version", "hint_variant_index", "first_choice_index", "ready_at_first_choice"
        ).annotate(legacy_key=KT("hint__hint_key")).prefetch_related(
            Prefetch("assignments", queryset=slots, to_attr="assigned_slots")
        )
        for trial in trials.iterator(chunk_size=500):
            hints = assignments(trial)
            count = len(hints)
            chosen = trial.first_choice_index
            all_four = chosen is not None and trial.ready_at_first_choice == 4
            cohort = cohorts[trial.protocol_version, count]
            cohort["batches"] += 1
            choices["opted_in"] += 1
            if all_four:
                cohort["all_four_choices"] += 1
                cohort["hinted_choices"] += int(chosen in hints)
            if not count:
                choices["without_hint"] += 1
                continue
            if chosen is None:
                choices["assigned_without_choice"] += 1
            elif trial.ready_at_first_choice is None:
                choices["choices_without_ready_snapshot"] += 1
            elif not all_four:
                choices["early_choices"] += 1
            else:
                choices["comparable_choices"] += 1
                choices["hinted_choices"] += int(chosen in hints)
                hinted_slots_shown += count
            for slot in range(1, 5):
                key = hints.get(slot)
                if key is not None:
                    exposure = mechanics[key]
                    exposure["assigned"] += 1
                    exposure["comparable_exposures"] += int(all_four)
                    exposure["first_choices"] += int(all_four and slot == chosen)
                outcomes = public.get((trial.pk, slot))
                if outcomes:
                    public_by_group["hinted" if key is not None else "ordinary"].update(outcomes)
                    if key is not None:
                        public_by_mechanic[key].update(outcomes)

        comparable = choices["comparable_choices"]
        return {
            "first_choices": {
                **choices, "hinted_choice_share": share(choices["hinted_choices"], comparable),
                "random_choice_share": share(hinted_slots_shown, 4 * comparable),
            },
            "cohorts": [
                {
                    "protocol_version": protocol, "hint_count": count, **cohort,
                    "hinted_choice_share": share(cohort["hinted_choices"], cohort["all_four_choices"]),
                    "random_choice_share": count / 4,
                }
                for (protocol, count), cohort in sorted(cohorts.items())
            ],
            "mechanics": {
                key: {
                    **counts, "choice_share": share(counts["first_choices"], counts["comparable_exposures"]),
                    "random_choice_share": 0.25, "published": outcome_metrics(public_by_mechanic[key]),
                }
                for key, counts in sorted(mechanics.items())
            },
            "published_variants": {
                group: outcome_metrics(public_by_group[group]) for group in ("hinted", "ordinary")
            },
        }
