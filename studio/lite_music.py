"""Persisted Lite-only music admission; delivery uses the normal Invocation path."""

from django.utils import timezone

from generation.experience import RECIPE
from generation.lite import eligible
from generation.music import MARKER


def enabled(run):
    return (run.operation == 'create' and run.requirement_manifest.get(MARKER) == 1
            and eligible({'provider': run.provider, 'generation_strategy': run.generation_strategy,
                          'generation_profile': run.generation_profile}))


def due(run, base):
    return (enabled(run) and run.allow_model_calls and base is not None and RECIPE not in base.files
            and run.attempts < run.max_model_calls
            and (not run.model_call_deadline or timezone.now() < run.model_call_deadline)
            and not run.invocations.filter(request__operation='music').exists())
