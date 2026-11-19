"""Durable fan-out/fan-in for the explicitly selected Pro experiment.

Remote jobs run concurrently; delivery/polling uses their stable UUIDs, not host
threads or speculative retries. Every response and charge is a normal Invocation.
"""

import hashlib
import time

from django.db import transaction
from django.utils import timezone

from generation.errors import ContractError, GenerationPending
from generation.pro_parallel import assemble, author, branches, validate_reply
from generation.prompts import system_prompt
from generation.requirements import digest, policy_snapshot
from generation.schema import response_schema

from .continuations import pending_invocations, unacknowledged_unknowns
from .models import Invocation, Run
from .services import DomainError, event, finish_run, reserve_invocation, settle_invocation


def branch_request(run, role, error=None, *, responses=None, previous=None):
    from .tasks import request_for

    request = request_for(run, None, [], error)
    request.pop('response_completion', None)
    request.update(pro_parallel=run.pro_parallel_version, pro_parallel_branch=role,
                   pro_parallel_plan_hash=digest(run.game_plan),
                   operation='create' if role in {'gameplay', 'scene'} else 'pro_' + role,
                   reasoning_effort='high')
    if run.pro_parallel_version in {4, 5} and role in {'gameplay', 'scene'}:
        from generation.pro_staged import completion_policy

        request['reasoning_effort'] = 'medium'
        completion = completion_policy(previous)
        if completion:
            request['response_completion'] = completion
    if run.pro_parallel_version == 5 and role == 'audio':
        request['reasoning_effort'] = 'medium'
    if run.pro_parallel_version in {4, 5} and role == 'checks':
        from generation.pro_staged import source_context

        request.update(source_context(responses, run.game_plan, run.pro_parallel_version))
        if (run.pro_parallel_version == 5 and run.model == 'gpt-6.2-sol'
                and request['assets'].get('sounds')):
            request['pro_audio_check_timing'] = 1
    if role in {'mechanics', 'scene'}:
        from generation.pro_partition import interface_hash

        request['mechanics_interface_hash'] = interface_hash(run.game_plan)
    request['generation_contract'].update(
        system_prompt_sha256=hashlib.sha256(system_prompt(request).encode()).hexdigest(),
        response_schema_sha256=digest(response_schema(request)),
    )
    return request


def calls_for(run):
    return pending_invocations(run, None, states=('reserved', 'sent', 'returned', 'settled', 'failed', 'unknown')).filter(
        request__pro_parallel=run.pro_parallel_version, request__pro_parallel_plan_hash=digest(run.game_plan),
        request__pro_parallel_branch__in=branches(run.game_plan, run.pro_parallel_version),
    )


@transaction.atomic
def consume(run):
    """Cancellation reconciliation stores raw receipts; validate those here too."""
    from .tasks import error_data

    current = Run.objects.select_for_update().get(pk=run.id)
    if current.fence != run.fence or current.cancel_requested or current.status not in Run.ACTIVE:
        return
    for call in calls_for(run).filter(state='returned'):
        try:
            validate_reply(call.response, call.request)
            call.state = 'settled'
        except ContractError as exc:
            call.state, call.error = 'failed', error_data(exc)
        call.save(update_fields=['state', 'error'])


def deliver(run, call, lease, generate):
    """Receive sent jobs even after deadline/policy change; never create a new UUID."""
    from .tasks import error_data, mark_invocation_sent, record_relay_pending

    if lease.cancelled():
        return None
    if not call.sent_at:
        reason = None
        if run.policy_snapshot != policy_snapshot():
            reason = {'code': 'generation_policy_changed', 'message': 'Правила генерации обновились.'}
        elif run.model_call_deadline and timezone.now() >= run.model_call_deadline:
            reason = {'code': 'model_deadline', 'message': 'Время новых вызовов истекло.'}
        if reason:
            settle_invocation(call.id, unsent_fence=run.fence, error=reason)
            return None
    if not mark_invocation_sent(run, call):
        return None
    try:
        result = generate(call.request, on_event=lambda _: None, is_cancelled=lease.cancelled)
        metadata = {**(result.get('provider_metadata') or {}), 'execution_id': result.get('invocation_id', '')}
        settle_invocation(call.id, response=result['response'], raw_response=result.get('raw_response'),
            usage=result.get('usage'), elapsed=(timezone.now() - call.sent_at).total_seconds(),
            provider_id=metadata.get('turn_id') or metadata.get('request_id') or '', provider_metadata=metadata)
    except GenerationPending as exc:
        record_relay_pending(call, exc)
        return exc
    except Exception as exc:
        data = error_data(exc)
        if getattr(exc, 'raw_response', None) is not None:
            data['raw_response'] = getattr(exc, 'raw_response')
        metadata = getattr(exc, 'provider_metadata', None) or {}
        settle_invocation(call.id, error=data, usage=getattr(exc, 'usage', None),
            unknown=getattr(exc, 'outcome_unknown', True),
            elapsed=(timezone.now() - call.sent_at).total_seconds(),
            provider_id=metadata.get('turn_id') or metadata.get('request_id') or '', provider_metadata=metadata)
    return None


def advance(run, lease, generate, materialize):
    from .tasks import defer_relay, error_data, store_candidate

    waiting = None
    roles = branches(run.game_plan, run.pro_parallel_version)
    source_author = author(run.game_plan, run.pro_parallel_version)
    progress = ('Создаём механику, сцену, графику и звук.' if source_author == 'scene'
                else 'Создаём геймплей, графику и звук.')
    # Poll all existing jobs before admitting replacements; a capacity reduction,
    # deadline or failed sibling must not strand another branch's paid receipt.
    for call in run.invocations.filter(state__in=['reserved', 'sent']).order_by('attempt'):
        pending = deliver(run, call, lease, generate)
        if pending and (waiting is None or pending.operator_required):
            waiting = pending
    if lease.cancelled():
        return None
    # The validated branch result is durably consumed, though it does not yet
    # constitute an assembled game. Keep it available across explicit continuations.
    consume(run)
    calls = list(calls_for(run))
    valid: dict[str, Invocation] = {}
    for call in calls:
        if call.state == 'settled':
            valid.setdefault(call.request['pro_parallel_branch'], call)
    refusal = valid.get(source_author) and valid[source_author].response.get('status') == 'scope_refusal'
    unknown = unacknowledged_unknowns(run)
    blocked = None
    # Fresh branches take priority over repairs. An unavailable slot may defer a
    # branch, but can never turn the already sent siblings into new inferences.
    missing = [role for role in roles if role not in valid and not any(
        c.request['pro_parallel_branch'] == role and c.state in {'reserved', 'sent'} for c in calls)]
    missing.sort(key=lambda role: any(c.request['pro_parallel_branch'] == role for c in calls))
    if not unknown and not refusal:
        for role in missing:
            if lease.cancelled():
                return None
            if role == 'checks' and any(r not in valid for r in roles if r != 'checks'):
                continue
            failures = [c for c in calls if c.request['pro_parallel_branch'] == role and c.state == 'failed']
            if run.pro_parallel_version in {4, 5} and (len(failures) >= 3 or any(
                c.request.get('response_completion') for c in failures
            ) or sum(
                (c.error or {}).get('code') == 'response_output_limit' for c in failures
            ) >= 2):
                blocked = DomainError('parallel_branch_exhausted',
                    'Этап повторно не завершился. Готовые части и ответы сохранены; одинаковые повторы остановлены.')
                break
            previous = next((c for c in sorted(calls, key=lambda c: c.created_at, reverse=True)
                             if c.request['pro_parallel_branch'] == role and c.error), None)
            # Keep raw rejected content private; error is sufficient for a new
            # bounded branch response under the same frozen IDs/requirements.
            error = {k: v for k, v in previous.error.items() if k != 'raw_response'} if previous else None
            try:
                request = branch_request(run, role, error, responses={r: c.response for r, c in valid.items()},
                                         previous=previous)
                branch_progress = ('Готовим проверку управления и прохождения.' if role == 'checks' else
                    'Завершаем игровую сцену. Готовые части сохранены.' if request.get('response_completion') else progress)
                with transaction.atomic():
                    call = reserve_invocation(run, request)
                    run.attempts = call.attempt
                    Run.objects.filter(pk=run.id, fence=run.fence).update(attempts=call.attempt,
                        status='generating', stage='parallel', message=branch_progress)
                    event(run, 'parallel_branch', branch_progress,
                          {'branch': role, 'attempt': call.attempt, 'max_model_calls': run.max_model_calls})
            except DomainError as exc:
                blocked = exc
                break
            pending = deliver(run, call, lease, generate)
            if pending and (waiting is None or pending.operator_required):
                waiting = pending
    if lease.cancelled():
        return None
    consume(run)
    if run.invocations.filter(state__in=['reserved', 'sent']).exists():
        defer_relay(run, 'Ожидаем ответы исполнителей.', waiting)
        return None
    unknown = unacknowledged_unknowns(run)
    if unknown:
        finish_run(run.id, run.fence, 'unknown', 'Исход одного из запросов неизвестен. Полученные ответы сохранены.',
                   error={'code': 'outcome_unknown', 'message': 'Новый вызов требует отдельного подтверждения.'})
        return None
    valid = {}
    for call in calls_for(run):
        if call.state == 'settled':
            valid.setdefault(call.request['pro_parallel_branch'], call)
    if valid.get(source_author) and valid[source_author].response['status'] == 'scope_refusal':
        finish_run(run.id, run.fence, 'needs_attention', valid[source_author].response['message'],
                   error={'code': 'scope_refusal', 'message': valid[source_author].response['message']})
        return None
    if len(valid) != len(roles):
        if blocked and blocked.code != 'provider_busy':
            finish_run(run.id, run.fence, 'needs_attention', blocked.message, error=error_data(blocked))
        else:
            defer_relay(run, 'Сохранили готовые части. Продолжаем оставшиеся этапы.')
        return None
    packaging_started = time.monotonic()
    try:
        response = assemble({role: call.response for role, call in valid.items()}, run.game_plan, run.pro_parallel_version)
        request = valid[source_author].request
        artifact = materialize(response, operation='create', generation_contract=request['generation_contract'],
            generation_strategy='pro', requirement_manifest=run.requirement_manifest,
            helper_catalog=run.helper_catalog, generation_profile='full', source_format='string')
        packaging_seconds = time.monotonic() - packaging_started
    except ContractError as exc:
        # Source packaging may fail although the reply schema was correct. Keep
        # both validated resource branches and retry only the gameplay author.
        with transaction.atomic():
            current = Run.objects.select_for_update().get(pk=run.id)
            if current.fence != run.fence or current.cancel_requested:
                return None
            call = valid[source_author]
            call.state, call.error = 'failed', error_data(exc)
            call.save(update_fields=['state', 'error'])
            if run.pro_parallel_version in {4, 5} and 'checks' in valid:
                check_call = valid['checks']
                check_call.state = 'failed'
                check_call.error = {'code': 'parallel_source_changed', 'message': 'Исходники будут исправлены.'}
                check_call.save(update_fields=['state', 'error'])
        defer_relay(run, 'Ресурсы сохранены. Исправляем сборку игры.')
        return None
    with transaction.atomic():
        revision = store_candidate(run, artifact, None)
        if revision is None:
            return None
        Invocation.objects.filter(pk__in=[c.pk for c in valid.values()], state='settled').update(
            revision=revision, state='settled')
        current = Run.objects.select_for_update().get(pk=run.id)
        current.metrics = {**current.metrics,
            'packaging_seconds': current.metrics.get('packaging_seconds', 0) + packaging_seconds,
            'pro_parallel': {
            'version': run.pro_parallel_version, 'plan_hash': digest(run.game_plan),
            'gameplay_mode': 'split' if source_author == 'scene' else 'single',
            'assembled_revision': str(revision.id),
            'invocations': {role: str(call.id) for role, call in valid.items()},
        }}
        current.save(update_fields=['metrics'])
    return revision
