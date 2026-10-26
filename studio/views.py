import json
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .model_profiles import (
    can_use_pro,
    configured_profiles,
    default_profile,
    profile_options,
    unavailable_reason,
)
from .models import Chat, Feedback, Like, Message, Publication, Revision, Run
from .serialization import chat_data, preview_url, publication_data, revision_data, run_data
from .services import (
    DomainError,
    budget_snapshot,
    cancel_run,
    create_run,
    event,
    preference_for,
    rename_chat,
    tariff,
    validate_chat_title,
)


def exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        return Response(
            {"error": {"code": "invalid_request", "message": "Проверьте идентификатор и поля запроса."}},
            status=400,
        )
    if isinstance(exc, DomainError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}, status=exc.status
        )
    response = drf_exception_handler(exc, context)
    if response is not None:
        message = (
            str(response.data.get("detail", "Некорректный запрос."))
            if isinstance(response.data, dict)
            else "Некорректный запрос."
        )
        response.data = {"error": {"code": getattr(exc, "default_code", "request_error"), "message": message}}
    return response


def csrf_failure(request, reason=""):
    return JsonResponse(
        {
            "error": {
                "code": "csrf_failed",
                "message": "Сессия страницы устарела. Обновите её и повторите вход.",
            }
        },
        status=403,
    )


def owned_chat(request, ident):
    chat = Chat.objects.filter(pk=ident, owner=request.user, deleted_at__isnull=True).first()
    if chat is None:
        raise DomainError("chat_not_found", "Этот чат удалён или недоступен. Создайте новую игру.", 404)
    return chat


def owned_run(request, ident):
    return get_object_or_404(Run, pk=ident, chat__owner=request.user, chat__deleted_at__isnull=True)


def owned_revision(request, ident):
    return get_object_or_404(Revision, pk=ident, chat__owner=request.user, chat__deleted_at__isnull=True)


def capabilities(request):
    models = []
    if settings.GAMEFORGE_PROVIDER in {"codex", "codex_api"}:
        try:
            from generation.service import PROVIDERS

            models = PROVIDERS[settings.GAMEFORGE_PROVIDER].available_models()
        except (ImportError, OSError, ValueError):
            pass
    if not models and settings.GAMEFORGE_MODEL:
        models = [{"id": settings.GAMEFORGE_MODEL, "name": settings.GAMEFORGE_MODEL}]
    for model in models:
        model["priced"] = bool(tariff(settings.GAMEFORGE_PROVIDER, model["id"]))
    options = profile_options(request)
    return {
        "provider": settings.GAMEFORGE_PROVIDER,
        "model": settings.GAMEFORGE_MODEL,
        "models": models,
        "local_only": settings.GAMEFORGE_LOCAL_ONLY,
        "model_profiles": options,
        "default_model_profile": default_profile(options),
    }


def preference_data(pref):
    return {"theme": pref.theme, "notes": pref.notes, "model_profile": pref.model_profile}


def session_data(request):
    user = request.user
    pref = preference_for(user) if user and user.is_authenticated else None
    return {
        "user": {"id": user.id, "username": user.username, "is_staff": user.is_staff} if pref else None,
        "csrfToken": get_token(request),
        "preferences": preference_data(pref)
        if pref
        else {"theme": "light", "notes": [], "model_profile": ""},
        "capabilities": capabilities(request),
        "budget": budget_snapshot() if pref else None,
    }


@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def session_view(request):
    return Response(session_data(request))


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def login_view(request):
    user = authenticate(request, username=request.data.get("username"), password=request.data.get("password"))
    if user is None:
        raise DomainError("invalid_credentials", "Неверное имя пользователя или пароль.", 400)
    login(request, user)
    return Response(session_data(request))


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response({"ok": True, **session_data(request)})


@api_view(["GET", "POST"])
def chats_view(request):
    if request.method == "GET":
        return Response(
            {
                "results": [
                    chat_data(c)
                    for c in Chat.objects.filter(owner=request.user, deleted_at__isnull=True)
                    .select_related("current_revision")
                    .order_by("-updated_at")
                ]
            }
        )
    title = request.data.get("title", "")
    audience = request.data.get("audience", "everyone")
    normalized_title = validate_chat_title(title, allow_empty=True)
    if audience not in ("everyone", "gamers", "children", "seniors"):
        raise DomainError("invalid_chat", "Проверьте название и аудиторию.")
    chat = Chat.objects.create(
        owner=request.user, title=normalized_title, title_is_custom=bool(title.strip()), audience=audience
    )
    return Response(chat_data(chat, True), status=201)


@api_view(["GET", "PATCH", "DELETE"])
def chat_view(request, ident):
    chat = owned_chat(request, ident)
    if request.method == "GET":
        return Response(chat_data(chat, True))
    if request.method == "PATCH":
        chat = rename_chat(chat, request.data.get("title"))
        return Response(chat_data(chat, True))
    with transaction.atomic():
        chat = Chat.objects.select_for_update().get(pk=chat.pk)
        for run in chat.runs.filter(status__in=Run.ACTIVE):
            cancel_run(run)
        chat.deleted_at = timezone.now()
        chat.save(update_fields=["deleted_at"])
    return Response(status=204)


def enforce_provider_boundary(request, provider):
    if provider in {"codex", "codex_api"}:
        if not settings.GAMEFORGE_PRO_ENABLED or not can_use_pro(request):
            raise DomainError(
                "codex_access_denied", "Для вашего аккаунта Pro не разрешён на этом сервере.", 403
            )


@api_view(["POST"])
def runs_view(request, ident):
    run = create_run(owned_chat(request, ident), request.data,
                     authorize=lambda provider: enforce_provider_boundary(request, provider))
    return Response(run_data(run), status=202)


@api_view(["GET"])
def run_view(request, ident):
    return Response(run_data(owned_run(request, ident)))


@api_view(["POST"])
def cancel_view(request, ident):
    return Response(run_data(cancel_run(owned_run(request, ident))))


@api_view(["POST"])
def continue_view(request, ident):
    run = owned_run(request, ident)
    data = dict(request.data)
    data.setdefault("idempotency_key", str(uuid.uuid4()))
    return Response(run_data(create_run(
        run.chat, data, continued_from=run,
        authorize=lambda provider: enforce_provider_boundary(request, provider),
    )), status=202)


@api_view(["POST"])
def recheck_view(request, ident):
    original = owned_run(request, ident)
    # Owner-only local validation needs no access to the model provider.
    data = {"idempotency_key": request.data.get("idempotency_key") or str(uuid.uuid4())}
    return Response(run_data(create_run(original.chat, data, continued_from=original, check_only=True)), status=202)


@api_view(["POST"])
def confirm_view(request, ident):
    if request.data.get("confirmed") is not True:
        raise DomainError(
            "confirmation_required", "Подтвердите, что лично проверили отмеченные игровые условия."
        )
    with transaction.atomic():
        original = owned_run(request, ident)
        chat = Chat.objects.select_for_update().get(pk=original.chat_id)
        run = Run.objects.select_for_update().get(pk=original.pk)
        from .acceptance import confirmation_report
        from .tasks import check_identity

        report = confirmation_report(run)
        if report is None:
            raise DomainError("cannot_confirm", "Это задание не ожидает ручной проверки.", 409)
        if (
            request.data.get("artifact_hash") != run.candidate_revision.artifact_hash
            or request.data.get("report_id") != report.id
        ):
            raise DomainError("confirmation_changed", "Результат проверки изменился. Откройте его заново.", 409)
        if report.identity != check_identity(run.candidate_revision):
            raise DomainError("stale_verification", "Правила проверки изменились. Повторите проверку игры.", 409)
        if (
            chat.current_revision_id != run.base_revision_id
            or chat.runs.filter(status__in=Run.ACTIVE).exists()
        ):
            raise DomainError("base_changed", "Игра уже меняется или рабочая версия обновлена.", 409)
        revision = run.candidate_revision
        revision.accepted = True
        revision.verification = "manual"
        revision.checks_review_required = False
        revision.save(update_fields=["accepted", "verification", "checks_review_required"])
        chat.current_revision = revision
        if not chat.title_is_custom:
            from .titles import short_game_title

            chat.title = short_game_title(revision.title)
        chat.save(update_fields=["current_revision", "title", "updated_at"])
        run.status = "succeeded"
        run.stage = "succeeded"
        run.result_revision = revision
        run.error = None
        run.message = "Игра принята после вашей ручной проверки."
        run.finished_at = timezone.now()
        run.save()
        event(run, "manual_confirmation", run.message)
        Message.objects.create(chat=chat, run=run, role="assistant", content=run.message)
    return Response(run_data(run))


@api_view(["POST"])
def restore_view(request, ident):
    with transaction.atomic():
        chat = Chat.objects.select_for_update().get(pk=owned_chat(request, ident).pk)
        if chat.runs.filter(status__in=Run.ACTIVE).exists():
            raise DomainError("chat_busy", "Дождитесь завершения задания или отмените его.", 409)
        revision = get_object_or_404(Revision, pk=request.data.get("revision_id"), chat=chat, accepted=True)
        chat.current_revision = revision
        chat.save(update_fields=["current_revision", "updated_at"])
    return Response(chat_data(chat, True))


@api_view(["GET"])
def events_view(request, ident):
    run = owned_run(request, ident)
    try:
        after = max(0, int(request.query_params.get("after", request.headers.get("Last-Event-ID", "0"))))
    except ValueError:
        raise DomainError("invalid_cursor", "Некорректный номер события.")
    events = list(run.events.filter(id__gt=after).order_by("id")[:300])

    def stream():
        for e in events:
            payload = {
                "id": e.id,
                "kind": e.kind,
                "message": e.message,
                "details": e.details,
                "created_at": e.created_at.isoformat(),
            }
            yield f"id: {e.id}\nevent: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "retry: 1500\n: reconnect\n\n"

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@api_view(["GET"])
def diagnostics_view(request, ident):
    run = owned_run(request, ident)
    return Response(
        {
            "run": run_data(run),
            "private_diagnostics": run.private_diagnostics,
            "invocations": [
                {
                    "id": str(i.id),
                    "attempt": i.attempt,
                    "state": i.state,
                    "request": i.request,
                    "response": i.response,
                    "error": i.error,
                    "usage": i.usage,
                    "reservation_usd": str(i.reservation_usd),
                    "cost_usd": str(i.cost_usd) if i.cost_usd is not None else None,
                    "price": i.price,
                    "provider_invocation_id": i.provider_invocation_id,
                    "provider_metadata": i.provider_metadata,
                    "elapsed_seconds": i.elapsed_seconds,
                    "created_at": i.created_at.isoformat(),
                    "sent_at": i.sent_at.isoformat() if i.sent_at else None,
                    "finished_at": i.finished_at.isoformat() if i.finished_at else None,
                }
                for i in run.invocations.order_by("attempt")
            ],
            "revisions": [revision_data(v) for v in run.revisions.all()],
            "completion_policy": run.completion_policy,
            "events": [{"id": e.id, "kind": e.kind, "created_at": e.created_at.isoformat(),
                        "details": e.details} for e in run.events.order_by("id")[:200]],
            "events_truncated": run.events.count() > 200,
        }
    )


@api_view(["GET"])
def revision_view(request, ident):
    return Response(revision_data(owned_revision(request, ident)))


@api_view(["GET"])
def source_view(request, ident):
    revision = owned_revision(request, ident)
    return Response(
        {
            "id": str(revision.id),
            "files": revision.files,
            "file_hashes": revision.file_hashes,
            "diff": revision.diff,
            "generation_profile": revision.generation_profile,
            "compact_manifest": revision.compact_manifest,
            "runtime_version": revision.runtime_version,
            "pipeline_version": revision.pipeline_version,
        }
    )


@api_view(["GET"])
def export_view(request, ident):
    revision = owned_revision(request, ident)
    response = HttpResponse(revision.html, content_type="text/html; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="game.html"'
    response["Cache-Control"] = "private, no-store"
    return response


@api_view(["GET"])
def preview_link_view(request, ident):
    return Response({"url": preview_url(owned_revision(request, ident))})


def preview_view(request, token):
    if request.get_host() != urlparse(settings.GAMEFORGE_PREVIEW_ORIGIN).netloc:
        return HttpResponse("Preview is available only on its isolated origin.", status=403)
    try:
        payload = signing.loads(token, salt="game-preview", max_age=86400)
    except signing.BadSignature:
        return HttpResponse("Ссылка устарела. Откройте игру заново.", status=403)
    revision = get_object_or_404(Revision, pk=payload.get("revision"), artifact_hash=payload.get("hash"))
    html = revision.html
    if request.GET.get("audio_control") == "1":
        from generation.preview import with_audio_control

        html = with_audio_control(html, artifact_hash=revision.artifact_hash,
                                  app_origin=settings.GAMEFORGE_APP_ORIGIN)
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; worker-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'; sandbox allow-scripts; frame-ancestors "
        + settings.GAMEFORGE_APP_ORIGIN
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    response.xframe_options_exempt = True
    return response


@api_view(["GET", "POST"])
def publications_view(request):
    if request.method == "GET":
        qs = Publication.objects.select_related("owner", "revision", "source_chat").annotate(
            like_count=Count("likes")
        )
        if request.query_params.get("mine") == "1":
            qs = qs.filter(owner=request.user)
        qs = (
            qs.order_by("-like_count", "-created_at")
            if request.query_params.get("sort") == "popular"
            else qs.order_by("-created_at")
        )
        return Response({"results": [publication_data(p, request.user) for p in qs[:100]]})
    chat = owned_chat(request, request.data.get("chat_id"))
    revision = get_object_or_404(
        Revision, pk=request.data.get("revision_id") or chat.current_revision_id, chat=chat, accepted=True
    )
    title = request.data.get("title") or revision.title
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        raise DomainError("invalid_title", "Укажите название до 160 символов.")
    publication = Publication.objects.create(
        owner=request.user, source_chat=chat, revision=revision, title=title.strip()
    )
    return Response(publication_data(publication, request.user), status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AllowAny])
def publication_view(request, ident):
    publication = get_object_or_404(Publication, pk=ident)
    if request.method == "GET":
        return Response(publication_data(publication, request.user))
    if not request.user or not request.user.is_authenticated or publication.owner_id != request.user.id:
        raise DomainError("permission_denied", "Публикация принадлежит другому пользователю.", 403)
    if request.method == "DELETE":
        publication.delete()
        return Response(status=204)
    if "title" in request.data:
        title = request.data["title"]
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
            raise DomainError("invalid_title", "Укажите название до 160 символов.")
        publication.title = title.strip()
    if "revision_id" in request.data:
        revision = get_object_or_404(
            Revision,
            pk=request.data["revision_id"],
            chat__owner=request.user,
            chat__deleted_at__isnull=True,
            accepted=True,
        )
        if revision.chat_id != publication.source_chat_id:
            raise DomainError("wrong_chat", "Обновление должно относиться к исходной игре.")
        publication.revision = revision
    publication.save()
    return Response(publication_data(publication, request.user))


@api_view(["POST", "PUT"])
def like_view(request, ident):
    publication = get_object_or_404(Publication, pk=ident)
    liked = request.data.get("liked", True)
    if not isinstance(liked, bool):
        raise DomainError("invalid_like", "Укажите true или false.")
    if liked:
        Like.objects.get_or_create(publication=publication, user=request.user)
    else:
        Like.objects.filter(publication=publication, user=request.user).delete()
    return Response({"liked": liked, "likes": publication.likes.count()})


@api_view(["POST"])
def remix_view(request, ident):
    publication = get_object_or_404(Publication, pk=ident)
    with transaction.atomic():
        source = publication.revision
        chat = Chat.objects.create(
            owner=request.user, title=publication.title, title_is_custom=True, source_publication=publication
        )
        revision = Revision.objects.create(
            chat=chat,
            parent=source,
            number=1,
            title=source.title,
            files=source.files,
            html=source.html,
            artifact_hash=source.artifact_hash,
            file_hashes=source.file_hashes,
            generation_profile=source.generation_profile,
            compact_manifest=source.compact_manifest,
            runtime_version=source.runtime_version,
            pipeline_version=source.pipeline_version,
            design=source.design,
            checks=source.checks,
            diff=[],
            accepted=True,
            verification=source.verification,
        )
        # Published evidence concerns exactly these bytes; copy it without a new model/browser call.
        report = source.reports.order_by("-id").first()
        if report:
            report.pk = None
            report.revision = revision
            report.save()
        chat.current_revision = revision
        chat.save(update_fields=["current_revision"])
    return Response(chat_data(chat, True), status=201)


@api_view(["GET", "PATCH"])
def preferences_view(request):
    pref = preference_for(request.user)
    if request.method == "PATCH":
        if "model_profile" in request.data:
            profile_id = request.data["model_profile"]
            if not isinstance(profile_id, str) or profile_id not in configured_profiles():
                raise DomainError("invalid_model_profile", "Выберите Pro или Lite.")
            reason = unavailable_reason(configured_profiles()[profile_id], request)
            if reason:
                raise DomainError("model_unavailable", reason, 409)
            pref.model_profile = profile_id
        if "theme" in request.data:
            if request.data["theme"] not in ("light", "dark"):
                raise DomainError("invalid_theme", "Выберите светлую или тёмную тему.")
            pref.theme = request.data["theme"]
        if "notes" in request.data:
            notes = request.data["notes"]
            if (
                not isinstance(notes, list)
                or len(notes) > 10
                or not all(isinstance(s, str) and len(s) <= 300 for s in notes)
            ):
                raise DomainError("invalid_preferences", "Можно сохранить до 10 коротких пожеланий.")
            pref.notes = list(dict.fromkeys(s.strip() for s in notes if s.strip()))
        pref.save(update_fields=[key for key in ("theme", "notes", "model_profile") if key in request.data])
    return Response(preference_data(pref))


@api_view(["POST"])
def feedback_view(request, ident):
    chat = owned_chat(request, ident)
    rating = request.data.get("rating")
    reasons = request.data.get("reasons", [])
    if type(rating) is not int or not 1 <= rating <= 5:
        raise DomainError("invalid_rating", "Оценка должна быть от 1 до 5.")
    if (
        not isinstance(reasons, list)
        or len(reasons) > 5
        or not all(isinstance(s, str) and len(s) <= 300 for s in reasons)
    ):
        raise DomainError("invalid_reasons", "Добавьте до пяти коротких пожеланий.")
    with transaction.atomic():
        feedback = Feedback.objects.create(
            chat=chat, user=request.user, revision=chat.current_revision, rating=rating, reasons=reasons
        )
        pref = preference_for(request.user)
        pref.notes = list(dict.fromkeys(pref.notes + [s.strip() for s in reasons if s.strip()]))[-10:]
        pref.save(update_fields=["notes"])
    return Response(
        {
            "id": feedback.id,
            "rating": rating,
            "reasons": reasons,
            "preferences": preference_data(pref),
        },
        status=201,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(request):
    return Response({"status": "ok"})


def index_view(request, path=""):
    index = settings.BASE_DIR / "web" / "dist" / "index.html"
    if index.exists():
        return HttpResponse(index.read_text(), content_type="text/html")
    return HttpResponse("Frontend is not built yet. Start the Vite development server.", status=503)


@api_view(["GET"])
@permission_classes([AllowAny])
def publication_thumbnail_view(request, ident):
    import base64

    publication = get_object_or_404(Publication, pk=ident)
    report = publication.revision.reports.exclude(screenshot_base64="").order_by("-id").first()
    if not report:
        return HttpResponse(status=404)
    response = HttpResponse(
        base64.b64decode(report.screenshot_base64),
        content_type=report.screenshot_mime
        if report.screenshot_mime in ("image/png", "image/jpeg", "image/webp")
        else "image/png",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "public, max-age=60"
    return response
