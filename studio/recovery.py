"""Local operator recovery of a complete stored reply. Never contacts a provider."""

import json
import uuid

from django.db import transaction

from generation.artifacts import materialize
from generation.normalization import VERSION, normalize_response
from generation.schema import CONTRACT_VERSION, response_schema, validate_response

from .models import Chat, Invocation, Revision, Run
from .services import DomainError, event, fingerprint, schedule


@transaction.atomic
def recover_saved_response(invocation_id, *, apply=False):
    source = Invocation.objects.select_related("run").get(pk=invocation_id)
    chat = Chat.objects.select_for_update().get(pk=source.run.chat_id)
    key = f"recover-response:{source.id}"
    existing = Run.objects.filter(chat=chat, idempotency_key=key).first()
    if existing:
        return {"run_id": str(existing.id), "status": existing.status, "existing": True}
    parent = Run.objects.select_for_update().get(pk=source.run_id)
    if parent.pipeline_version != CONTRACT_VERSION or source.request.get('generation_contract', {}).get('pipeline_version') != CONTRACT_VERSION:
        raise DomainError('unsupported_game', 'Старый игровой формат больше не поддерживается.', 409)
    source = Invocation.objects.select_for_update().get(pk=source.id)
    if (source.state != "failed" or not source.finished_at or source.revision_id
            or (source.error or {}).get("code") != "invalid_schema"
            or parent.status not in {"failed", "needs_attention"} or parent.cancel_requested):
        raise DomainError("not_recoverable", "Нужен завершённый ответ с известной ошибкой формата.", 409)
    if chat.deleted_at or chat.runs.filter(status__in=Run.ACTIVE).exists():
        raise DomainError("chat_busy", "Чат удалён или уже выполняет другое задание.", 409)
    base_id = source.request.get("base_revision")
    if chat.current_revision_id != parent.base_revision_id:
        raise DomainError("base_changed", "Рабочая версия изменилась после сохранённого ответа.", 409)
    raw = source.raw_response if source.raw_response is not None else (source.error or {}).get("raw_response")
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError) as exc:
        raise DomainError("invalid_saved_json", "Сохранённый ответ не является полным JSON.") from exc
    response, paths = normalize_response(decoded)
    saved_request = source.request
    if parent.generation_profile == 'compact':
        from generation.compact import validate_wire

        validate_wire(response, saved_request)
    else:
        validate_response(response, operation=source.request["operation"], schema=response_schema(saved_request),
                          defer_check_errors=source.request['operation']=='create')
    base = Revision.objects.filter(pk=base_id, chat=chat).first() if base_id else None
    if base_id and base is None:
        raise DomainError('base_changed', 'Исходная версия больше недоступна.', 409)
    basis = saved_request.get('code_repair_basis')
    if basis:
        from .check_repair import code_repair_basis

        if base is None or code_repair_basis(parent, base) != basis:
            raise DomainError('stale_code_repair_basis', 'Свидетельство для ремонта кода изменилось; нужна повторная проверка.', 409)
    artifact = materialize(
        response, operation=source.request["operation"], base_revision=base_id,
        files=base.files if base else None, previous_checks=base.checks if base else None,
        generation_contract=saved_request["generation_contract"],
        module_repair=source.request.get("module_repair") if base and not base.accepted else None,
        generation_profile=parent.generation_profile, compact_manifest=saved_request.get('compact_manifest'),
        source_format=parent.source_format, check_repair=saved_request.get('check_repair'),
        code_repair_basis=basis,
    )
    if artifact.get("status") in {"unchanged", "scope_refusal"}:
        raise DomainError("no_saved_candidate", "Ответ не содержит нового кандидата игры.")
    if parent.generation_profile == 'compact' and base:
        artifact.update(title=base.title, design=base.design)
    audit = {"source_invocation": str(source.id), "source_run": str(parent.id),
             "raw_sha256": fingerprint(raw), "normalization_version": VERSION, "paths": paths}
    summary = {"source_invocation": str(source.id), "changes": paths,
               "artifact_hash": artifact["artifact_hash"], "files": len(artifact["files"]),
               "checks": len(artifact["checks"]), "model_calls_allowed": False}
    if not apply:
        return {**summary, "dry_run": True}
    # A distinct run preserves original failures, raw receipts, usage and billing.
    # The permanent policy flag also forbids inference after a crash/restart.
    run = Run.objects.create(
        chat=chat, operation=parent.operation, prompt=parent.prompt, audience=parent.audience,
        provider=parent.provider, model=parent.model, model_profile=parent.model_profile,
        base_revision=parent.base_revision, continued_from=parent,
        source_revision=parent.source_revision, game_request=parent.game_request,
        generation_profile=parent.generation_profile, source_format=parent.source_format,
        pipeline_version=parent.pipeline_version,
        idempotency_key=key, request_fingerprint=fingerprint(audit), allow_model_calls=False,
        fence=uuid.uuid4(), metrics={"saved_response_recovery": audit},
    )
    from .tasks import store_candidate

    revision = store_candidate(run, artifact, base)
    if revision is None:
        raise DomainError("recovery_cancelled", "Восстановление было отменено.", 409)
    run.refresh_from_db()
    run.status, run.stage = "queued", "checking"
    run.message = "Ответ восстановлен без новой генерации. Проверяем сохранённую игру."
    run.save(update_fields=["status", "stage", "message", "updated_at"])
    event(run, "response_recovered", run.message, {"source_invocation": str(source.id), "paths": paths})
    schedule(run)
    return {**summary, "run_id": str(run.id), "revision_id": str(revision.id), "status": run.status}
