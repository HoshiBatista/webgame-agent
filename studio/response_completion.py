"""A single metered completion after a known terminal output limit, never unknown."""

from generation.response_completion import permission

from .continuations import lineage_ids
from .models import Invocation

CONTEXT = ('provider', 'model', 'operation', 'prompt', 'game_request', 'game_plan',
           'generation_profile', 'source_format', 'audience', 'preferences',
           'helper_catalog', 'requirement_manifest', 'generation_strategy')


def pending_permission(run, request):
    if not run.allow_model_calls or request.get('operation') != 'create' or run.provider != 'codex_api':
        return None
    lineage = list(lineage_ids(run))
    if Invocation.objects.filter(run_id__in=lineage, request__response_completion__isnull=False).exists():
        return None
    # A later receipt or changed user request cannot silently reuse an older partial.
    source = None
    for ident in lineage:
        source = Invocation.objects.filter(run_id=ident).order_by('-attempt').first()
        if source:
            break
    if (source is None or source.state != 'failed' or not source.finished_at or source.revision_id
            or (source.error or {}).get('code') not in {'codex_turn_failed', 'response_output_limit'}
            or source.provider_metadata.get('turn_status') != 'failed'
            or source.provider_metadata.get('provider_error', {}).get('incomplete_reason') != 'max_output_tokens'
            or any(source.request.get(k) != request.get(k) for k in CONTEXT)):
        return None
    return permission(source.raw_response, source.request, source.id)


def adopt_completion_policy(run):
    """Explicit continuation may adopt the new completion path, never alter its parent."""
    from generation.helpers import catalog
    from generation.requirements import policy_snapshot
    from generation.schema import CONTRACT_VERSION

    from .services import event, fingerprint

    current = policy_snapshot()
    if (not run.continued_from_id or not run.allow_model_calls or run.policy_snapshot == current
            or run.pipeline_version != CONTRACT_VERSION or run.helper_catalog != catalog()
            or run.candidate_revision_id or run.source_revision_id or run.base_revision_id):
        return
    request = {k: getattr(run, k) for k in CONTEXT if k not in {'operation', 'preferences'}}
    request.update(operation='create', preferences=run.preferences_snapshot)
    policy = pending_permission(run, request)
    if policy:
        previous = fingerprint(run.policy_snapshot)
        run.policy_snapshot = current
        run.save(update_fields=['policy_snapshot'])
        event(run, 'response_completion_policy', 'Продолжение завершит ранее прерванный ответ.',
              {'previous_policy_hash': previous, 'source_invocation': policy['source_invocation'],
               'source_sha256': policy['source_sha256']})
