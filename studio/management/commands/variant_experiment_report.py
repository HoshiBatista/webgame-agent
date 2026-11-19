"""Summarize the opt-in four-variant trial without exposing games or individual players."""

import json

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, F, Q

from generation.schema import CONTRACT_VERSION
from studio.models import PlaySession, Publication, PublicationRating, VariantAnalyticsExperiment
from studio.publication_analytics import MIN_AVERAGED_SESSION_MS


def public_outcomes(publications):
    sessions = PlaySession.objects.filter(
        publication__in=publications,
        revision_id_snapshot=F("publication__revision_id"),
        artifact_hash=F("publication__revision__artifact_hash"),
    ).aggregate(
        sessions=Count("pk"),
        sessions_30s=Count("pk", filter=Q(visible_ms__gte=MIN_AVERAGED_SESSION_MS)),
    )
    # A rating belongs to a publication, which can later point to another version.
    # Ratings submitted since the latest publication update refer to the current version.
    ratings = PublicationRating.objects.filter(
        publication__in=publications, updated_at__gte=F("publication__updated_at")
    ).aggregate(ratings=Count("pk"), mean_rating=Avg("rating"))
    return {
        "publications": publications.count(),
        **sessions,
        "share_30s": sessions["sessions_30s"] / sessions["sessions"] if sessions["sessions"] else None,
        **ratings,
    }


class Command(BaseCommand):
    help = "Report first choices in opted-in Pro batches and public outcomes for directly published variants."

    def handle(self, *args, **options):
        assigned = Q(hint_variant_index__isnull=False)
        chosen = Q(first_choice_index__isnull=False)
        comparable = assigned & chosen & Q(ready_at_first_choice=4)
        choices = VariantAnalyticsExperiment.objects.aggregate(
            opted_in=Count("pk"),
            without_hint=Count("pk", filter=~assigned),
            assigned_without_choice=Count("pk", filter=assigned & ~chosen),
            choices_without_ready_snapshot=Count("pk", filter=assigned & chosen & Q(ready_at_first_choice__isnull=True)),
            early_choices=Count("pk", filter=assigned & chosen & Q(ready_at_first_choice__lt=4)),
            comparable_choices=Count("pk", filter=comparable),
            hinted_choices=Count("pk", filter=comparable & Q(first_choice_index=F("hint_variant_index"))),
        )
        comparable_count = choices["comparable_choices"]
        choices["hinted_choice_share"] = choices["hinted_choices"] / comparable_count if comparable_count else None
        publications = Publication.objects.filter(
            unavailable_at__isnull=True,
            revision__pipeline_version=CONTRACT_VERSION,
            revision__run__variant_batch__analytics_experiment__hint_variant_index__isnull=False,
        )
        hinted = Q(revision__run__variant_index=F("revision__run__variant_batch__analytics_experiment__hint_variant_index"))
        report = {
            "first_choices": choices,
            "published_variants": {
                "hinted": public_outcomes(publications.filter(hinted)),
                "other_three": public_outcomes(publications.exclude(hinted)),
            },
        }
        self.stdout.write(json.dumps(report, indent=2))
