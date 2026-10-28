"""Durable, append-only review processing, separate from game generation and its chat UI."""

import logging
import threading
import uuid
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

from celery import shared_task
from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from generation.errors import GenerationError, GenerationPending
from generation.preference_extraction import additions
from generation.service import DURABLE_PROVIDERS, PROVIDERS, estimate_reservation, generate

from .feedback import fields
from .models import Budget, Feedback, FeedbackProcessing, Preference
from .preferences import NOTES_LIMIT, add_feedback_notes
from .services import DomainError, budget_snapshot, tariff, usage_cost

ACTIVE = ("queued", "processing", "waiting")
logger = logging.getLogger(__name__)


def dispatch_feedback_jobs():
    """The database is the outbox; a slow/unavailable broker never delays saving a review."""
    now = timezone.now()
    candidates = FeedbackProcessing.objects.filter(status__in=ACTIVE, available_at__lte=now).filter(
        Q(lease_until__isnull=True) | Q(lease_until__lte=now)
    ).filter(Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=now - timedelta(seconds=15)))
    for ident in candidates.order_by("created_at").values_list("pk", flat=True)[:100]:
        with transaction.atomic():
            job = candidates.select_for_update(skip_locked=True).filter(pk=ident).first()
            if job is None:
                continue
            job.dispatched_at = now
            job.save(update_fields=["dispatched_at"])
        try:
            process_feedback.delay(str(ident))
        except Exception as exc:
            FeedbackProcessing.objects.filter(pk=ident, dispatched_at=now).update(dispatched_at=None)
            logger.warning("feedback_dispatch_failed job=%s type=%s", ident, type(exc).__name__)


def latest(job):
    return bool(job.feedback_id and job.user_id and job.user.is_active and
                job.feedback.revision_id and job.feedback.chat.owner_id == job.user_id and
                not job.feedback.chat.deleted_at and
                Feedback.objects.filter(user_id=job.user_id, revision_id=job.feedback.revision_id,
                                        chat_id=job.feedback.chat_id).order_by("-created_at", "-id")
                .values_list("id", flat=True).first() == job.feedback_id)


def finish(job, status, code=""):
    if not job.sent_at and job.invocation_state == "reserved":
        job.invocation_state, job.cost_usd = "failed", Decimal(0)
    job.status = status
    job.error = {"code": code} if code else {}
    job.fence, job.lease_until = None, None
    job.finished_at = timezone.now()
    job.save()


def defer(job, seconds=15):
    job.status = "waiting"
    job.available_at = timezone.now() + timedelta(seconds=seconds)
    job.fence, job.lease_until = None, None
    job.dispatched_at = None
    job.save()


def authorized(job):
    if not job.user_id or not job.user.is_active:
        return False
    if job.provider not in {"codex", "codex_api"}:
        return True
    if not settings.GAMEFORGE_PRO_ENABLED:
        return False
    origin = urlparse(settings.GAMEFORGE_APP_ORIGIN)
    if settings.GAMEFORGE_PRO_ACCESS == "local":
        return settings.GAMEFORGE_LOCAL_ONLY and origin.hostname in {"localhost", "127.0.0.1", "::1"}
    return (not settings.GAMEFORGE_LOCAL_ONLY and origin.scheme == "https" and
            (settings.GAMEFORGE_PRO_ACCESS == "authenticated" or
             settings.GAMEFORGE_PRO_ACCESS == "restricted" and job.user_id in settings.GAMEFORGE_PRO_USER_IDS))


@transaction.atomic
def claim(ident):
    Budget.objects.get_or_create(pk=1, defaults={"limit_usd": settings.GAMEFORGE_BUDGET_USD})
    Budget.objects.select_for_update().get(pk=1)
    job = FeedbackProcessing.objects.select_for_update(of=("self",)).select_related(
        "feedback__chat", "user").filter(pk=ident).first()
    now = timezone.now()
    if job is None or job.status not in ACTIVE or job.available_at > now or (
        job.lease_until and job.lease_until > now
    ):
        return None
    if job.invocation_state == "sent" and job.provider not in DURABLE_PROVIDERS:
        job.invocation_state = "unknown"
        finish(job, "failed", "outcome_unknown")
        return None
    # Once sent, retrieve the receipt even if the review/account/preferences were changed.
    if not job.sent_at:
        if not latest(job):
            finish(job, "superseded")
            return None
        if not authorized(job):
            finish(job, "failed", "model_unavailable")
            return None
        others = FeedbackProcessing.objects.filter(user_id=job.user_id).exclude(pk=job.pk)
        if others.filter(Q(invocation_state="unknown") | Q(invocation_state="returned", cost_usd__isnull=True)).exists():
            finish(job, "failed", "previous_outcome_unknown")
            return None
        if others.filter(status__in=ACTIVE).filter(
            Q(invocation_state__in=["reserved", "sent", "returned"]) | Q(created_at__lt=job.created_at)
        ).exists():
            defer(job)
            return None
        from .capacity import feedback_capacity_full

        if feedback_capacity_full(job):
            defer(job)
            return None
        pref = Preference.objects.select_for_update().get(user_id=job.user_id)
        existing = list(pref.notes)
        if job.request and (pref.notes_version != job.notes_version or
                            existing != job.request["preference_extraction"]["existing_notes"]):
            job.invocation_state, job.cost_usd = "failed", Decimal(0)
            finish(job, "stale")
            return None
        if len("\n".join(existing)) >= NOTES_LIMIT:
            finish(job, "full")
            return None
        if not job.request:
            selected, custom = fields(job.feedback)
            context = {"existing_notes": existing, "selected_reasons": selected, "custom_reason": custom,
                       "remaining_characters": NOTES_LIMIT - len("\n".join(existing))}
            job.notes_version = pref.notes_version
            job.price = tariff(job.provider, job.model)
            request = {"operation": "extract_preferences", "provider": job.provider, "model": job.model,
                       "reasoning_effort": "medium", "preference_extraction": context,
                       "execution_limits": {"context_window": job.price.get("context_window"),
                                            "max_output_tokens": min(job.price.get("max_output_tokens") or 8192, 8192)}}
            try:
                if job.provider != "fake" and not job.price:
                    raise DomainError("pricing_unavailable", "Нет проверенного тарифа.")
                if job.provider not in PROVIDERS:
                    raise DomainError("model_unavailable", "Модель недоступна.")
                if job.provider in DURABLE_PROVIDERS:
                    request[job.provider] = PROVIDERS[job.provider].prepare(request, str(job.pk))
                amount = estimate_reservation(request, job.price)
                if Decimal(str(budget_snapshot()["available_usd"])) < amount:
                    raise DomainError("budget_exhausted", "Недостаточно бюджета.")
            except (GenerationError, DomainError) as exc:
                finish(job, "failed", exc.code)
                return None
            job.request, job.reservation_usd = request, amount
            job.invocation_state = "reserved"
    job.fence = uuid.uuid4()
    job.lease_until = now + timedelta(seconds=90)
    job.status = "processing"
    job.save()
    return job


@contextmanager
def lease(job):
    stop = threading.Event()

    def renew():
        try:
            while not stop.wait(20):
                close_old_connections()
                if not FeedbackProcessing.objects.filter(pk=job.pk, fence=job.fence, status="processing").update(
                    lease_until=timezone.now() + timedelta(seconds=90)
                ):
                    return
        finally:
            close_old_connections()

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


@transaction.atomic
def mark_sent(job):
    # Shared budget lock gives admission, recovery and completion one lock order.
    Budget.objects.select_for_update().get(pk=1)
    current = FeedbackProcessing.objects.select_for_update(of=("self",)).select_related(
        "feedback__chat", "user").get(pk=job.pk)
    if current.fence != job.fence or current.status != "processing":
        return False
    if not current.sent_at and (not latest(current) or not authorized(current)):
        current.invocation_state, current.cost_usd = "failed", Decimal(0)
        finish(current, "superseded")
        return False
    if not current.sent_at:
        current.sent_at = timezone.now()
    current.invocation_state = "sent"
    current.save()
    return True


@transaction.atomic
def settle(job, result=None, error=None):
    Budget.objects.select_for_update().get(pk=1)
    current = FeedbackProcessing.objects.select_for_update().get(pk=job.pk)
    if current.invocation_state not in {"sent", "reserved", "unknown"}:
        return
    # A late final receipt is still accounted even if the worker lost its lease.
    current.response = result.get("response") if result else None
    current.raw_response = result.get("raw_response") if result else error.raw_response
    current.usage = result.get("usage") if result else error.usage
    current.provider_metadata = (result.get("provider_metadata") if result else error.provider_metadata) or {}
    unknown = bool(error and error.outcome_unknown)
    current.cost_usd = None if unknown else usage_cost(current.usage, current.price)
    current.invocation_state = "unknown" if unknown else "returned" if result else "failed"
    if current.cost_usd is None and not unknown and error:
        if error.raw_response is not None:
            current.invocation_state = "unknown"
        else:
            current.cost_usd = Decimal(0)
    if error:
        finish(current, "failed", error.code)
    else:
        # Applying is a separate recoverable step; a crash here won't repeat inference.
        current.status = "queued"
        current.available_at = timezone.now()
        current.fence, current.lease_until = None, None
        current.dispatched_at = None
        current.save()


@transaction.atomic
def apply_result(ident):
    # Feedback saves take Chat before Preference; follow that order to avoid races with edits.
    from .models import Chat

    job = FeedbackProcessing.objects.select_related("feedback__chat", "user").get(pk=ident)
    if job.feedback_id:
        Chat.objects.select_for_update().get(pk=job.feedback.chat_id)
    job = FeedbackProcessing.objects.select_for_update(of=("self",)).select_related(
        "feedback__chat", "user").get(pk=ident)
    if job.invocation_state != "returned" or job.status not in ACTIVE:
        return
    if not latest(job):
        finish(job, "superseded")
        return
    pref = Preference.objects.select_for_update().get(user_id=job.user_id)
    context = job.request["preference_extraction"]
    if pref.notes_version != job.notes_version or pref.notes != context["existing_notes"]:
        finish(job, "stale")
        return
    try:
        notes = additions(job.response, context)
    except GenerationError as exc:
        finish(job, "failed", exc.code)
        return
    combined, full = add_feedback_notes(pref.notes, notes)
    job.added_notes = combined[len(pref.notes):]
    if job.added_notes:
        pref.notes = combined
        pref.notes_version += 1
        pref.save(update_fields=["notes", "notes_version"])
    finish(job, "full" if full else "applied" if job.added_notes else "unchanged")


@shared_task(acks_late=False)
def process_feedback(ident):
    # Finish a received answer without claiming a new provider slot.
    if FeedbackProcessing.objects.filter(pk=ident, status__in=ACTIVE, invocation_state="returned").exists():
        apply_result(ident)
        return
    job = claim(ident)
    if job is None:
        return
    if not mark_sent(job):
        return
    try:
        with lease(job):
            result = generate(job.request, on_event=lambda *_args, **_kwargs: None,
                              is_cancelled=lambda: not FeedbackProcessing.objects.filter(
                                  pk=job.pk, fence=job.fence, status="processing").exists())
    except GenerationPending as exc:
        with transaction.atomic():
            current = FeedbackProcessing.objects.select_for_update().get(pk=job.pk)
            if current.fence == job.fence and current.status == "processing":
                current.error = {"code": exc.code}
                defer(current, max(5, min(exc.retry_after, 300)))
        return
    except GenerationError as exc:
        settle(job, error=exc)
        return
    except Exception as exc:
        logger.warning("feedback_processing_failed job=%s type=%s", job.pk, type(exc).__name__)
        if job.provider in DURABLE_PROVIDERS:
            with transaction.atomic():
                current = FeedbackProcessing.objects.select_for_update().get(pk=job.pk)
                if current.fence == job.fence and current.status == "processing":
                    defer(current, 30)
        else:
            settle(job, error=GenerationError("unexpected_error", "Ответ не получен.", outcome_unknown=True))
        return
    settle(job, result=result)
    apply_result(ident)
