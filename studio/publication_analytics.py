"""Small public-player counters. Games never call these APIs or receive write tokens."""

import hashlib
import hmac
import re
from datetime import timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import PlaySession, Publication, PublicationRating, PublicationStats
from .services import DomainError

MAX_SESSION_MS = 60 * 60 * 1000
MAX_RECEIPT_GAP_MS = 15_000
HEX = re.compile(r"^[0-9a-f]{64}$")


def annotated_publications(queryset, user):
    ratings = PublicationRating.objects.filter(publication_id=OuterRef("pk")).order_by().values("publication")
    queryset = queryset.select_related("stats").annotate(
        rating_average=Subquery(ratings.annotate(value=Avg("rating")).values("value")[:1]),
        ratings_count=Coalesce(Subquery(ratings.annotate(value=Count("pk")).values("value")[:1]),
                               Value(0), output_field=IntegerField()),
    )
    if user and user.is_authenticated:
        queryset = queryset.annotate(viewer_rating=Subquery(
            PublicationRating.objects.filter(publication_id=OuterRef("pk"), user=user).values("rating")[:1]))
    else:
        queryset = queryset.annotate(viewer_rating=Value(None, output_field=IntegerField()))
    return queryset


def rating_data(publication, user=None):
    if hasattr(publication, "rating_average"):
        average, count = publication.rating_average, publication.ratings_count
        own = publication.viewer_rating
    else:
        values = publication.ratings.aggregate(average=Avg("rating"), count=Count("pk"))
        average, count = values["average"], values["count"]
        own = (publication.ratings.filter(user=user).values_list("rating", flat=True).first()
               if user and user.is_authenticated else None)
    return {"average_rating": round(average, 2) if average is not None else None,
            "rating_count": count, "user_rating": own}


def analytics_data(publication):
    stats = getattr(publication, "stats", None)
    return {"opens": stats.opens if stats else 0,
            "average_duration_seconds": round(stats.visible_ms / stats.opens / 1000, 1)
            if stats and stats.opens else None,
            "successful_completions": stats.successful_completions if stats else None}


def token_hash(value):
    if not isinstance(value, str) or HEX.fullmatch(value) is None:
        raise DomainError("invalid_play_session", "Некорректный ключ игрового сеанса.")
    return hashlib.sha256(value.encode()).hexdigest()


def uuid_value(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DomainError("invalid_play_session", "Некорректный идентификатор игрового сеанса.") from exc


def available(publication):
    # Import lazily: the existing publication admission owns supported game formats.
    from .views import require_available_publication

    require_available_publication(publication)


def session_data(session):
    return {"session_id": str(session.pk), "visible_ms": session.visible_ms,
            "expires_at": (session.created_at + timedelta(milliseconds=MAX_SESSION_MS)).isoformat()}


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
@transaction.atomic
def open_session_view(request, ident):
    publication = get_object_or_404(Publication.objects.select_for_update(), pk=ident)
    available(publication)
    data = request.data
    if not isinstance(data, dict):
        raise DomainError("invalid_play_session", "Некорректный игровой сеанс.")
    session_id, secret = uuid_value(data.get("session_id")), token_hash(data.get("token"))
    revision_id, artifact_hash = uuid_value(data.get("revision_id")), data.get("artifact_hash")
    if not isinstance(artifact_hash, str) or HEX.fullmatch(artifact_hash) is None:
        raise DomainError("invalid_play_session", "Некорректная версия игры.")
    existing = PlaySession.objects.filter(pk=session_id).first()
    if existing:
        if (existing.publication_id != publication.pk or existing.revision_id_snapshot != revision_id
                or existing.artifact_hash != artifact_hash or not hmac.compare_digest(existing.token_hash, secret)):
            raise DomainError("play_session_conflict", "Этот сеанс относится к другому открытию игры.", 409)
        return Response(session_data(existing))
    if revision_id != publication.revision_id or artifact_hash != publication.revision.artifact_hash:
        raise DomainError("publication_changed", "Версия публикации обновилась. Откройте игру заново.", 409)
    now = timezone.now()
    try:
        # The publication lock serializes opens within a publication; the primary key
        # additionally protects a conflicting UUID submitted to different publications.
        with transaction.atomic():
            session = PlaySession.objects.create(id=session_id, publication=publication,
                revision_id_snapshot=revision_id, artifact_hash=artifact_hash, token_hash=secret,
                created_at=now, last_received_at=now)
    except IntegrityError as exc:
        raise DomainError("play_session_conflict", "Этот сеанс уже используется.", 409) from exc
    PublicationStats.objects.get_or_create(publication=publication)
    PublicationStats.objects.filter(publication=publication).update(opens=F("opens") + 1)
    return Response(session_data(session), status=201)


@api_view(["PUT"])
@permission_classes([AllowAny])
@csrf_protect
@transaction.atomic
def update_session_view(request, ident, session_id):
    publication = get_object_or_404(Publication.objects.select_for_update(), pk=ident)
    available(publication)
    data = request.data
    if not isinstance(data, dict):
        raise DomainError("invalid_play_session", "Некорректный игровой сеанс.")
    secret = token_hash(data.get("token"))
    session = get_object_or_404(PlaySession.objects.select_for_update(), pk=session_id, publication=publication)
    if not hmac.compare_digest(session.token_hash, secret):
        raise DomainError("invalid_play_session", "Ключ игрового сеанса не совпадает.", 403)
    now = timezone.now()
    age_ms = max(0, int((now - session.created_at).total_seconds() * 1000))
    if age_ms > MAX_SESSION_MS:
        raise DomainError("play_session_expired", "Игровой сеанс завершён.", 410)
    reported = data.get("visible_ms")
    if type(reported) is not int or not 0 <= reported <= MAX_SESSION_MS:
        raise DomainError("invalid_play_duration", "Некорректная длительность игрового сеанса.")
    if reported > session.reported_ms:
        gap_ms = max(0, int((now - session.last_received_at).total_seconds() * 1000))
        delta = max(0, min(reported - session.reported_ms, gap_ms, MAX_RECEIPT_GAP_MS,
                           age_ms - session.visible_ms))
        session.reported_ms, session.last_received_at = reported, now
        session.visible_ms += delta
        session.save(update_fields=["reported_ms", "last_received_at", "visible_ms"])
        PublicationStats.objects.filter(publication=publication).update(visible_ms=F("visible_ms") + delta)
    return Response(session_data(session))


@api_view(["PUT"])
@transaction.atomic
def rating_view(request, ident):
    publication = get_object_or_404(Publication.objects.select_for_update(), pk=ident)
    available(publication)
    value = request.data.get("rating") if isinstance(request.data, dict) else None
    if type(value) is not int or not 1 <= value <= 5:
        raise DomainError("invalid_rating", "Выберите оценку от 1 до 5.")
    PublicationRating.objects.update_or_create(publication=publication, user=request.user, defaults={"rating": value})
    return Response(rating_data(publication, request.user))
