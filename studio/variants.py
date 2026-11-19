"""Four independent ordinary Pro runs with an explicit choice of working revision."""

import secrets
import uuid
from copy import copy

from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import services
from .acceptance import confirmation_report
from .models import Chat, Run, VariantAnalyticsExperiment, VariantBatch
from .serialization import preview_url


@transaction.atomic
def create_batch(chat, data, *, authorize):
    chat = Chat.objects.select_for_update().get(pk=chat.pk, deleted_at__isnull=True)
    if data.get("model_profile") != "pro":
        raise services.DomainError("invalid_model_profile", "Режим 4× доступен для обычной Pro.")
    experiment = data.get("analytics_experiment")
    if "analytics_experiment" in data and type(experiment) is not bool:
        raise services.DomainError("invalid_analytics_experiment", "Для эксперимента передайте true или false.")
    key = data.get("idempotency_key")
    if not isinstance(key, str) or not key.strip() or len(key) > 100:
        raise services.DomainError("idempotency_required", "Укажите ключ запроса для защиты от повторной отправки.")
    previous = chat.runs.select_related("variant_batch__analytics_experiment").filter(idempotency_key=key).first()
    if previous and (previous.variant_index != 1 or previous.continued_from_id):
        raise services.DomainError("idempotency_conflict", "Этот ключ уже использован для другого запроса.", 409)
    batch = previous.variant_batch if previous else VariantBatch.objects.create(chat=chat)
    if previous and experiment is not None and experiment != hasattr(batch, "analytics_experiment"):
        raise services.DomainError("idempotency_conflict", "Этот ключ уже использован для другого запроса.", 409)
    if previous and "audience" not in data:
        data = {**data, "audience": previous.audience}
    # Resolve access, source identity and model settings once under the chat lock.
    # The ordinary run's exact request fingerprint also handles lost responses.
    first = services.create_run(chat, data, authorize=authorize, variant_batch=batch)
    if previous:
        return batch
    eligible = first.operation == "create" and first.planning_required
    if experiment and not eligible:
        raise services.DomainError("invalid_analytics_experiment", "Эксперимент доступен при создании новой игры в Pro 4×.")
    if eligible and experiment is not False:
        from .analytics_hints import choose_analytics_hint

        hint = choose_analytics_hint(prompt=first.prompt, audience=first.audience)
        VariantAnalyticsExperiment.objects.create(
            batch=batch, hint=hint, hint_variant_index=secrets.randbelow(4) + 1 if hint else None,
        )
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
        "id", "variant_batch_id", "variant_index", "prompt", "status", "stage", "message", "error",
        *(f"{rel}__{field}" for rel in ("candidate_revision", "result_revision") for field in revision_fields),
    ).order_by("variant_index", "created_at", "id")
    return (chat.variant_batches.select_related("analytics_experiment").order_by("-created_at", "-id")
            .prefetch_related(Prefetch("runs", queryset=runs)))


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
            "error_code": (run.error or {}).get("code", ""),
            "can_confirm": confirmation_report(run) is not None,
            "revision": {
                "id": str(revision.id), "title": revision.title, "accepted": revision.accepted,
                "artifact_hash": revision.artifact_hash, "preview_url": preview_url(revision),
                "export_url": f"/api/revisions/{revision.id}/export/",
            } if revision else None,
        })
    data = {
        "id": str(batch.id), "prompt": prompt, "created_at": batch.created_at.isoformat(),
        "selected_revision_id": str(batch.selected_revision_id) if batch.selected_revision_id else None,
        "variants": variants,
    }
    experiment = getattr(batch, "analytics_experiment", None)
    if experiment is not None:
        data["analytics_experiment"] = {"status": "applied" if experiment.hint_variant_index else "insufficient_data"}
    return data


def _shown_ready_ids(data):
    if "ready_revision_ids" not in data:
        return None
    values = data["ready_revision_ids"]
    error = services.DomainError("invalid_ready_revisions", "Укажите до четырёх разных версий, показанных как готовые.")
    if not isinstance(values, list) or len(values) > 4 or not all(isinstance(value, str) for value in values):
        raise error
    try:
        ids = {uuid.UUID(value) for value in values}
    except ValueError as exc:
        raise error from exc
    if len(ids) != len(values):
        raise error
    return ids


def _record_first_choice(experiment, revision, shown_ready_ids):
    if experiment.first_choice_at is not None:
        return
    if shown_ready_ids is not None:
        # A job can finish between the client's last poll and this click. Only
        # count displayed results still accepted in the newest attempt of their slot.
        slots = experiment.batch.runs.order_by("variant_index", "-created_at", "-id").distinct("variant_index")
        experiment.ready_at_first_choice = sum(
            status == "succeeded" and accepted is True and revision_id in shown_ready_ids
            for status, accepted, revision_id in slots.values_list("status", "result_revision__accepted", "result_revision_id")
        )
    experiment.first_choice_index = revision.run.variant_index
    experiment.first_choice_revision_id = revision.pk
    experiment.first_choice_at = timezone.now()
    experiment.save(update_fields=["ready_at_first_choice", "first_choice_index", "first_choice_revision_id",
                                   "first_choice_at"])


def _choice_revision_id(data):
    try:
        return uuid.UUID(str(data.get("revision_id")))
    except ValueError as exc:
        raise services.DomainError("invalid_revision", "Укажите сохранённый вариант игры.") from exc


@transaction.atomic
def record_draft_choice(chat, batch_id, data):
    chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.pk, deleted_at__isnull=True)
    experiment = get_object_or_404(VariantAnalyticsExperiment.objects.select_related("batch"),
                                   batch_id=batch_id, batch__chat=chat)
    revision_id = _choice_revision_id(data)
    revision = get_object_or_404(chat.revisions.select_related("run"), pk=revision_id,
                                 run__variant_batch_id=batch_id)
    if revision.artifact_hash != data.get("artifact_hash"):
        raise services.DomainError("source_changed", "Вариант изменился. Обновите список версий.", 409)
    shown_ready_ids = _shown_ready_ids(data)
    if experiment.first_choice_revision_id == revision_id:
        return
    latest = (experiment.batch.runs.filter(variant_index=revision.run.variant_index)
              .order_by("-created_at", "-id").first())
    reviewable = latest.status == "needs_attention" and (
        (latest.error or {}).get("code") == "check_review_required" or confirmation_report(latest) is not None
    )
    if revision.accepted or latest.candidate_revision_id != revision.pk or not (latest.status == "unverified" or reviewable):
        raise services.DomainError("unavailable_variant", "Этот черновик недоступен для выбора.", 409)
    _record_first_choice(experiment, revision, shown_ready_ids)


@transaction.atomic
def select_variant(chat, batch_id, data):
    chat = get_object_or_404(Chat.objects.select_for_update(), pk=chat.id, deleted_at__isnull=True)
    batch = get_object_or_404(VariantBatch.objects.select_related("analytics_experiment"), pk=batch_id, chat=chat)
    revision = get_object_or_404(chat.revisions.select_related("run"), pk=_choice_revision_id(data), accepted=True,
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
    experiment = getattr(batch, "analytics_experiment", None)
    if experiment is not None:
        _record_first_choice(experiment, revision, _shown_ready_ids(data))
    return chat
