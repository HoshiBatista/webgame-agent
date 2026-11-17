"""Provider slots; callers hold the shared Budget row lock during admission."""
from django.conf import settings
from django.db.models import Count, Q

from .models import FeedbackProcessing, Run


def provider_limit(provider):
    return (settings.GAMEFORGE_CODEX_API_CONCURRENCY if provider == "codex_api"
            else settings.GAMEFORGE_PROVIDER_CONCURRENCY)


def run_slots(provider, *, exclude=None):
    # Ordinary runs still occupy one slot. Parallel runs occupy one per admitted
    # inference, including cancelled/waiting jobs whose receipt is outstanding.
    runs = Run.objects.filter(provider=provider).exclude(pk=exclude).annotate(
        pending_calls=Count('invocations', filter=Q(invocations__state__in=['reserved', 'sent']))
    ).values_list('status', 'pending_calls')
    return sum(max(int(status in ['generating', 'checking']), calls) for status, calls in runs)


def capacity_full(run, *, include_current_calls=False):
    occupied = run_slots(run.provider, exclude=run.pk)
    if include_current_calls:
        occupied += run.invocations.filter(state__in=['reserved', 'sent']).count()
    occupied += FeedbackProcessing.objects.filter(provider=run.provider).filter(
        Q(status="processing") | Q(invocation_state__in=["reserved", "sent"])
    ).count()
    return occupied >= provider_limit(run.provider)


def feedback_capacity_full(job):
    occupied = run_slots(job.provider)
    occupied += FeedbackProcessing.objects.filter(provider=job.provider).exclude(pk=job.pk).filter(
        Q(status="processing") | Q(invocation_state__in=["reserved", "sent"])
    ).count()
    return occupied >= provider_limit(job.provider)
