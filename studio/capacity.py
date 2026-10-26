"""Provider slots; callers hold the shared Budget row lock during admission."""
from django.conf import settings
from django.db.models import Q

from .models import Run


def provider_limit(provider):
    return (settings.GAMEFORGE_CODEX_API_CONCURRENCY if provider == "codex_api"
            else settings.GAMEFORGE_PROVIDER_CONCURRENCY)


def capacity_full(run):
    # Processing and remote waiting/cancelled jobs may be disjoint. Count the
    # union, once per run, rather than max(two counts) or duplicated SQL joins.
    occupied = Run.objects.filter(provider=run.provider).exclude(pk=run.pk).filter(
        Q(status__in=["generating", "checking"]) | Q(invocations__state__in=["reserved", "sent"])
    ).values("pk").distinct().count()
    return occupied >= provider_limit(run.provider)
