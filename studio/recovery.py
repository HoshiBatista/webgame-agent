"""Local operator recovery of a complete stored reply. Never contacts a provider."""

import json
import uuid

from django.db import transaction

from generation.artifacts import materialize
from generation.normalization import VERSION, normalize_response
from generation.schema import response_schema, validate_response

from .models import Chat, Invocation, Run
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
    source = Invocation.objects.select_for_update().get(pk=source.id)
    if (source.state != "failed" or not source.finished_at or source.revision_id
            or (source.error or {}).get("code") != "invalid_schema"
            or parent.status not in {"failed", "needs_attention"} or parent.cancel_requested):
        raise DomainError("not_recoverable", "Нужен завершённый ответ с известной ошибкой формата.", 409)
    if chat.deleted_at or chat.runs.filter(status__in=Run.ACTIVE).exists():
        raise DomainError("chat_busy", "Чат удалён или уже выполняет другое задание.", 409)
    base_id = source.request.get("base_revision")
    if (str(chat.current_revision_id) if chat.current_revision_id else None) != base_id:
        raise DomainError("base_changed", "Рабочая версия изменилась после сохранённого ответа.", 409)
    raw = source.raw_response if source.raw_response is not None else (source.error or {}).get("raw_response")
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError) as exc:
        raise DomainError("invalid_saved_json", "Сохранённый ответ не является полным JSON.") from exc
    response, paths = normalize_response(decoded)
    # Pre-versioned stored calls used the v2 wire contract.
    saved_request = {"generation_contract": {"pipeline_version": 2}, **source.request}
    validate_response(response, operation=source.request["operation"], schema=response_schema(saved_request))
    base = chat.current_revision
    artifact = materialize(
        response, operation=source.request["operation"], base_revision=base_id,
        files=base.files if base else None, previous_checks=base.checks if base else None,
    )
    if artifact.get("status") == "unchanged":
        raise DomainError("no_saved_candidate", "Ответ не содержит нового кандидата игры.")
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
        provider=parent.provider, model=parent.model, base_revision=base, continued_from=parent,
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
