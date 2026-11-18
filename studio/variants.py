"""Four independent ordinary Pro runs with an explicit choice of working revision."""

import uuid
from copy import copy

from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from . import services
from .acceptance import confirmation_report
from .models import Chat, Run, VariantBatch
from .serialization import preview_url


@transaction.atomic
def create_batch(chat, data, *, authorize):
    chat = Chat.objects.select_for_update().get(pk=chat.pk, deleted_at__isnull=True)
    if data.get("model_profile") != "pro":
        raise services.DomainError("invalid_model_profile", "Режим 4× доступен для обычной Pro.")
    key = data.get("idempotency_key")
    if not isinstance(key, str) or not key.strip() or len(key) > 100:
        raise services.DomainError("idempotency_required", "Укажите ключ запроса для защиты от повторной отправки.")
    previous = chat.runs.select_related("variant_batch").filter(idempotency_key=key).first()
    if previous and (previous.variant_index != 1 or previous.continued_from_id):
        raise services.DomainError("idempotency_conflict", "Этот ключ уже использован для другого запроса.", 409)
    batch = previous.variant_batch if previous else VariantBatch.objects.create(chat=chat)
    if previous and "audience" not in data:
        data = {**data, "audience": previous.audience}
    # Resolve access, source identity and model settings once under the chat lock.
    # The ordinary run's exact request fingerprint also handles lost responses.
    first = services.create_run(chat, data, authorize=authorize, variant_batch=batch)
    if previous:
        return batch
    for index in range(2, 5):
        sibling = copy(first)
        sibling.pk = uuid.uuid4()
        sibling.idempotency_key = f"variant-{sibling.pk}"
        sibling.variant_index = index
        sibling.save(force_insert=True)
        services.event(sibling, "queued", "Запрос принят. Ожидаем свободное место для генерации.")
        services.schedule(sibling)
    return batch


def batches_for(chat):
    revision_fields = ("id", "title", "artifact_hash", "accepted")
    runs = Run.objects.select_related("candidate_revision", "result_revision").only(
        "id", "variant_batch_id", "variant_index", "prompt", "status", "stage", "message",
        *(f"{rel}__{field}" for rel in ("candidate_revision", "result_revision") for field in revision_fields),
    ).order_by("variant_index", "created_at", "id")
    return chat.variant_batches.order_by("-created_at", "-id").prefetch_related(Prefetch("runs", queryset=runs))


def batch_data(batch):
    latest = {}
    roots = {}
    prompt = ""
    for run in batch.runs.all():
        if run.variant_index not in latest:
            roots[run.variant_index] = str(run.id)
            if run.variant_index == 1:
                prompt = run.prompt
        latest[run.variant_index] = run
    variants = []
    for index, run in sorted(latest.items()):
        revision = run.result_revision or run.candidate_revision
        variants.append({
            "index": index, "root_run_id": roots[index], "run_id": str(run.id),
            "status": run.status, "stage": run.stage, "message": run.message,
            "can_confirm": confirmation_report(run) is not None,
            "revision": {
                "id": str(revision.id), "title": revision.title, "accepted": revision.accepted,
                "artifact_hash": revision.artifact_hash, "preview_url": preview_url(revision),
                "export_url": f"/api/revisions/{revision.id}/export/",
            } if revision else None,
        })
    return {
        "id": str(batch.id), "prompt": prompt, "created_at": batch.created_at.isoformat(),
        "selected_revision_id": str(batch.selected_revision_id) if batch.selected_revision_id else None,
        "variants": variants,
    }


@transaction.atomic
def select_variant(chat, batch_id, data):
    chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.id, deleted_at__isnull=True)
    batch = get_object_or_404(VariantBatch, pk=batch_id, chat=chat)
    try:
        revision_id = uuid.UUID(str(data.get("revision_id")))
    except ValueError as exc:
        raise services.DomainError("invalid_revision", "Укажите сохранённый вариант игры.") from exc
    revision = get_object_or_404(chat.revisions, pk=revision_id, accepted=True,
                                 run__variant_batch=batch)
    # An accepted candidate from a previous run can also be confirmed in a continuation.
    if (data.get("artifact_hash") != revision.artifact_hash
            or not batch.runs.filter(status="succeeded", result_revision=revision).exists()):
        raise services.DomainError("source_changed", "Вариант изменился. Обновите список версий.", 409)
    if chat.current_revision_id != revision.pk:
        current_id = str(chat.current_revision_id) if chat.current_revision_id else None
        if "expected_current_revision_id" not in data or data["expected_current_revision_id"] != current_id:
            raise services.DomainError("source_changed", "Рабочая версия изменилась. Обновите чат.", 409)
        if chat.runs.filter(status__in=Run.ACTIVE).exclude(variant_batch=batch).exists():
            raise services.DomainError("chat_busy", "Дождитесь завершения текущего задания.", 409)
        services.choose_working_revision(chat, revision)
    if batch.selected_revision_id != revision.pk:
        batch.selected_revision = revision
        batch.save(update_fields=["selected_revision"])
    return chat
