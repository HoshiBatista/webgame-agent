"""FastAPI transport for projects, durable runs, previews and analytics."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import secrets
import zipfile
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from prompt2play.adapters.artifacts import ArtifactIntegrityError, ArtifactStore
from prompt2play.application.workflow import enqueue_stage, record_event
from prompt2play.auth import (
    create_auth_session,
    normalize_username,
    resolve_user,
    token_digest,
    verify_password,
)
from prompt2play.config import Settings, get_settings
from prompt2play.contracts import (
    AnalyticsEventRequest,
    ChatMessage,
    CreateProjectRequest,
    FeedbackReason,
    FeedbackSummary,
    LoginRequest,
    ProjectSummary,
    PublicGameSummary,
    PublicGameUpdateRequest,
    PublishResponse,
    RemixRequest,
    ReviseRequest,
    RevisionStatus,
    RevisionSummary,
    RunEventMessage,
    RunState,
    RunSummary,
    SubmitFeedbackRequest,
    UserSummary,
    ValidationReport,
)
from prompt2play.db import SessionLocal, get_session
from prompt2play.models import (
    AnalyticsEvent,
    AuthSession,
    GameFeedback,
    GenerationRun,
    IdempotencyRecord,
    Project,
    PublicGame,
    PublicGameLike,
    Revision,
    RunEvent,
    User,
)

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
IdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=8, max_length=200),
]


def get_current_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> User:
    """Require a valid creator session without exposing why authentication failed."""

    user = resolve_user(session, request.cookies.get(settings.session_cookie_name))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return user


UserDep = Annotated[User, Depends(get_current_user)]


def _owned_project(session: Session, project_id: UUID, user: User) -> Project:
    project = session.scalar(
        select(Project).where(
            Project.id == project_id, Project.owner_id == user.id, Project.archived.is_(False)
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _owned_run(session: Session, run_id: UUID, user: User) -> GenerationRun:
    run = session.scalar(
        select(GenerationRun)
        .join(Project, Project.id == GenerationRun.project_id)
        .where(GenerationRun.id == run_id, Project.owner_id == user.id, Project.archived.is_(False))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _owned_revision(session: Session, revision_id: UUID, user: User) -> Revision:
    revision = session.scalar(
        select(Revision)
        .join(Project, Project.id == Revision.project_id)
        .where(Revision.id == revision_id, Project.owner_id == user.id, Project.archived.is_(False))
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    return revision


def _request_hash(operation: str, *parts: object) -> str:
    """Return a stable fingerprint without persisting another copy of prompt text."""

    payload = json.dumps([operation, *parts], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _scoped_idempotency_key(user_id: UUID, key: str | None) -> str | None:
    """Prevent one creator's idempotency key from colliding with another's."""

    if key is None:
        return None
    return hashlib.sha256(f"{user_id}:{key}".encode()).hexdigest()


def _reserve_idempotency(
    session: Session,
    key: str | None,
    operation: str,
    request_hash: str,
) -> tuple[IdempotencyRecord | None, GenerationRun | None]:
    """Reserve a key or return the run committed by an equivalent request."""

    if key is None:
        return None, None
    record = session.get(IdempotencyRecord, key)
    if record is None:
        candidate = IdempotencyRecord(
            key=key,
            operation=operation,
            request_hash=request_hash,
        )
        try:
            with session.begin_nested():
                session.add(candidate)
                session.flush()
            return candidate, None
        except IntegrityError:
            record = session.get(IdempotencyRecord, key)
            if record is None:
                raise
    if record.operation != operation or record.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used for a different request",
        )
    if record.run_id is None or record.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotent request is still being committed",
        )
    run = session.get(GenerationRun, record.run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotent request no longer references an available run",
        )
    return record, run


def _run_summary(run: GenerationRun) -> RunSummary:
    return RunSummary(
        id=run.id,
        project_id=run.project_id,
        state=RunState(run.state),
        error=run.error,
        revision_id=run.revision_id,
        repair_count=run.repair_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _revision_summary(
    revision: Revision, settings: Settings, publication: PublicGame | None = None
) -> RevisionSummary:
    validation = (
        ValidationReport.model_validate(revision.validation_report)
        if revision.validation_report
        else None
    )
    preview = None
    if revision.status == RevisionStatus.VALIDATED.value:
        preview = f"{settings.public_base_url}/v1/revisions/{revision.id}/preview"
    share = f"{settings.public_base_url}/play/{publication.slug}" if publication else None
    return RevisionSummary(
        id=revision.id,
        parent_id=revision.parent_id,
        title=revision.title,
        genre=revision.genre,
        audience=revision.audience,
        status=RevisionStatus(revision.status),
        model_name=revision.model_name,
        created_at=revision.created_at,
        preview_url=preview,
        share_url=share,
        public_game_id=publication.id if publication else None,
        public_title=publication.title if publication else None,
        validation=validation,
    )


def _project_summary(project: Project, session: Session, settings: Settings) -> ProjectSummary:
    revisions = session.scalars(
        select(Revision)
        .where(Revision.project_id == project.id)
        .order_by(Revision.created_at.desc(), Revision.id.desc())
    ).all()
    publication = session.scalar(select(PublicGame).where(PublicGame.project_id == project.id))
    return ProjectSummary(
        id=project.id,
        title=project.title,
        prompt=project.prompt,
        current_revision_id=project.current_revision_id,
        forked_from_revision_id=project.forked_from_revision_id,
        created_at=project.created_at,
        revisions=[
            _revision_summary(
                item,
                settings,
                publication if publication and publication.revision_id == item.id else None,
            )
            for item in revisions
        ],
        messages=[
            ChatMessage(
                id=run.id,
                text=run.revision_instruction or run.prompt,
                state=RunState(run.state),
                created_at=run.created_at,
                revision_id=run.revision_id,
                error=run.error,
            )
            for run in session.scalars(
                select(GenerationRun)
                .where(GenerationRun.project_id == project.id)
                .order_by(GenerationRun.created_at, GenerationRun.id)
            ).all()
        ],
    )


def _public_game_summary(
    public_game: PublicGame, session: Session, settings: Settings, user: User
) -> PublicGameSummary:
    revision = session.get(Revision, public_game.revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="Published game not found")
    like_count = session.scalar(
        select(func.count())
        .select_from(PublicGameLike)
        .where(PublicGameLike.public_game_id == public_game.id)
    )
    liked = session.get(PublicGameLike, (public_game.id, user.id)) is not None
    return PublicGameSummary(
        id=public_game.id,
        revision_id=revision.id,
        title=public_game.title,
        author_username=public_game.author.username,
        genre=revision.genre,
        audience=revision.audience,
        like_count=like_count or 0,
        liked_by_me=liked,
        is_mine=public_game.author_id == user.id,
        share_url=f"{settings.public_base_url}/play/{public_game.slug}",
        published_at=public_game.created_at,
        updated_at=public_game.updated_at,
    )


def _feedback_summary(feedback: GameFeedback) -> FeedbackSummary:
    return FeedbackSummary(
        id=feedback.id,
        revision_id=feedback.revision_id,
        rating=feedback.rating,
        reasons=[FeedbackReason(item) for item in feedback.reasons],
        comment=feedback.comment,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


def _try_dispatch() -> None:
    """Wake the dispatcher; the PostgreSQL outbox remains durable if Redis is down."""

    try:
        from prompt2play.tasks import dispatch_outbox

        dispatch_outbox.delay()
    except Exception:
        return


def _preview_response(html: str) -> HTMLResponse:
    response = HTMLResponse(html)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; sandbox allow-scripts"
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), fullscreen=(self)"
    )
    return response


def create_app() -> FastAPI:
    """Build the HTTP adapter without creating infrastructure implicitly."""

    settings = get_settings()
    app = FastAPI(
        title="Prompt2Play API",
        version="0.1.0",
        description="Prompt → model → validated self-contained HTML5 game",
    )

    @app.exception_handler(ArtifactIntegrityError)
    async def artifact_integrity_error(
        _request: Request, _error: ArtifactIntegrityError
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Artifact integrity check failed"})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )

    @app.get("/healthz", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"])
    def ready(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.post("/v1/auth/login", response_model=UserSummary, tags=["auth"])
    def login(
        body: LoginRequest,
        response: Response,
        session: SessionDep,
        settings_dep: SettingsDep,
    ) -> UserSummary:
        user = session.scalar(
            select(User).where(User.username_normalized == normalize_username(body.username))
        )
        if (
            user is None
            or not user.is_active
            or not verify_password(body.password, user.password_hash)
        ):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        _, token = create_auth_session(session, user, settings_dep.session_ttl_hours)
        session.commit()
        response.set_cookie(
            settings_dep.session_cookie_name,
            token,
            max_age=settings_dep.session_ttl_hours * 3600,
            httponly=True,
            secure=settings_dep.public_base_url.startswith("https://"),
            samesite="strict",
            path="/",
        )
        return UserSummary(id=user.id, username=user.username, is_admin=user.is_admin)

    @app.get("/v1/auth/me", response_model=UserSummary, tags=["auth"])
    def auth_me(user: UserDep) -> UserSummary:
        return UserSummary(id=user.id, username=user.username, is_admin=user.is_admin)

    @app.post("/v1/auth/logout", status_code=204, tags=["auth"])
    def logout(
        request: Request,
        response: Response,
        session: SessionDep,
        settings_dep: SettingsDep,
    ) -> Response:
        token = request.cookies.get(settings_dep.session_cookie_name)
        if token:
            session.execute(
                delete(AuthSession).where(AuthSession.token_digest == token_digest(token))
            )
            session.commit()
        response.delete_cookie(settings_dep.session_cookie_name, path="/")
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    @app.post("/v1/projects", status_code=status.HTTP_202_ACCEPTED, tags=["projects"])
    def create_project(
        body: CreateProjectRequest,
        session: SessionDep,
        user: UserDep,
        idempotency_key: IdempotencyKey = None,
    ) -> dict[str, str]:
        operation = f"create_project:{user.id}"
        record, existing_run = _reserve_idempotency(
            session,
            _scoped_idempotency_key(user.id, idempotency_key),
            operation,
            _request_hash(operation, body.prompt),
        )
        if existing_run is not None:
            return {
                "project_id": str(existing_run.project_id),
                "run_id": str(existing_run.id),
            }
        project = Project(prompt=body.prompt, owner_id=user.id)
        session.add(project)
        session.flush()
        run = GenerationRun(
            project_id=project.id,
            prompt=body.prompt,
            state=RunState.ACCEPTED.value,
            max_repairs=settings.max_repair_attempts,
        )
        session.add(run)
        session.flush()
        if record is not None:
            record.project_id = project.id
            record.run_id = run.id
        record_event(session, run, "accepted", "Запрос принят в генерацию")
        enqueue_stage(session, "specify", run.id)
        session.commit()
        _try_dispatch()
        return {"project_id": str(project.id), "run_id": str(run.id)}

    @app.get("/v1/projects", response_model=list[ProjectSummary], tags=["projects"])
    def list_projects(
        session: SessionDep, settings_dep: SettingsDep, user: UserDep
    ) -> list[ProjectSummary]:
        projects = session.scalars(
            select(Project)
            .where(Project.owner_id == user.id, Project.archived.is_(False))
            .order_by(Project.created_at.desc())
        ).all()
        return [_project_summary(item, session, settings_dep) for item in projects]

    @app.get("/v1/projects/{project_id}", response_model=ProjectSummary, tags=["projects"])
    def get_project(
        project_id: UUID, session: SessionDep, settings_dep: SettingsDep, user: UserDep
    ) -> ProjectSummary:
        project = _owned_project(session, project_id, user)
        return _project_summary(project, session, settings_dep)

    @app.delete("/v1/projects/{project_id}", status_code=204, tags=["projects"])
    def archive_project(project_id: UUID, session: SessionDep, user: UserDep) -> Response:
        project = _owned_project(session, project_id, user)
        # Archive rather than cascade-delete: publications and their remixes keep working.
        session.refresh(project, with_for_update=True)
        runs = session.scalars(
            select(GenerationRun).where(GenerationRun.project_id == project.id).with_for_update()
        ).all()
        for run in runs:
            if run.state not in {"succeeded", "failed", "cancelled"}:
                run.cancel_requested = True
                run.state = RunState.CANCELLED.value
                record_event(session, run, "cancelled", "Чат удалён пользователем")
        project.archived = True
        session.commit()
        return Response(status_code=204)

    @app.get("/v1/runs/{run_id}", response_model=RunSummary, tags=["runs"])
    def get_run(run_id: UUID, session: SessionDep, user: UserDep) -> RunSummary:
        run = _owned_run(session, run_id, user)
        return _run_summary(run)

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunSummary, tags=["runs"])
    def cancel_run(run_id: UUID, session: SessionDep, user: UserDep) -> RunSummary:
        run = _owned_run(session, run_id, user)
        session.refresh(run, with_for_update=True)
        if run.state not in {
            RunState.SUCCEEDED.value,
            RunState.FAILED.value,
            RunState.CANCELLED.value,
        }:
            run.cancel_requested = True
            run.state = RunState.CANCELLED.value
            record_event(session, run, "cancelled", "Генерация отменена пользователем")
            session.commit()
        return _run_summary(run)

    @app.get("/v1/runs/{run_id}/events", tags=["runs"])
    async def run_events(
        run_id: UUID,
        request: Request,
        session: SessionDep,
        user: UserDep,
        last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        _owned_run(session, run_id, user)
        # StreamingResponse keeps yield-based dependencies alive until disconnect.
        # The stream opens short-lived sessions below, so release this one now.
        session.close()

        async def stream() -> AsyncIterator[str]:
            cursor = last_event_id or 0
            terminal_seen = False
            while not await request.is_disconnected():
                with SessionLocal() as event_session:
                    exists = event_session.get(GenerationRun, run_id)
                    if exists is None:
                        yield 'event: error\ndata: {"detail":"Run not found"}\n\n'
                        return
                    events = event_session.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == run_id, RunEvent.sequence > cursor)
                        .order_by(RunEvent.sequence)
                    ).all()
                    for item in events:
                        payload = RunEventMessage(
                            id=item.sequence,
                            event=item.event_type,
                            message=item.message,
                            payload=item.payload,
                            created_at=item.created_at,
                        )
                        cursor = item.sequence
                        yield (
                            f"id: {item.sequence}\nevent: {item.event_type}\n"
                            f"data: {payload.model_dump_json()}\n\n"
                        )
                    terminal_seen = exists.state in {
                        RunState.SUCCEEDED.value,
                        RunState.FAILED.value,
                        RunState.CANCELLED.value,
                    }
                if terminal_seen:
                    return
                yield ": keep-alive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post(
        "/v1/revisions/{revision_id}/revise",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["revisions"],
    )
    def revise(
        revision_id: UUID,
        body: ReviseRequest,
        session: SessionDep,
        user: UserDep,
        idempotency_key: IdempotencyKey = None,
    ) -> dict[str, str]:
        revision = _owned_revision(session, revision_id, user)
        if revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        operation = f"revise:{user.id}"
        record, existing_run = _reserve_idempotency(
            session,
            _scoped_idempotency_key(user.id, idempotency_key),
            operation,
            _request_hash(operation, revision_id, body.instruction),
        )
        if existing_run is not None:
            return {
                "project_id": str(existing_run.project_id),
                "run_id": str(existing_run.id),
            }
        project = _owned_project(session, revision.project_id, user)
        session.refresh(project, with_for_update=True)
        if project.archived:
            raise HTTPException(status_code=404, detail="Project not found")
        project.selection_version += 1
        run = GenerationRun(
            project_id=project.id,
            parent_revision_id=revision.id,
            prompt=project.prompt,
            revision_instruction=body.instruction,
            state=RunState.ACCEPTED.value,
            max_repairs=settings.max_repair_attempts,
            project_version=project.selection_version,
        )
        session.add(run)
        session.flush()
        if record is not None:
            record.project_id = project.id
            record.run_id = run.id
        record_event(session, run, "accepted", "Запрос на новую ревизию принят")
        enqueue_stage(session, "specify", run.id)
        session.commit()
        _try_dispatch()
        return {"project_id": str(project.id), "run_id": str(run.id)}

    @app.get("/v1/revisions/{revision_id}", response_model=RevisionSummary, tags=["revisions"])
    def get_revision(
        revision_id: UUID, session: SessionDep, settings_dep: SettingsDep, user: UserDep
    ) -> RevisionSummary:
        revision = _owned_revision(session, revision_id, user)
        publication = session.scalar(
            select(PublicGame).where(PublicGame.revision_id == revision.id)
        )
        return _revision_summary(revision, settings_dep, publication)

    @app.post(
        "/v1/revisions/{revision_id}/restore", response_model=ProjectSummary, tags=["revisions"]
    )
    def restore_revision(
        revision_id: UUID, session: SessionDep, settings_dep: SettingsDep, user: UserDep
    ) -> ProjectSummary:
        revision = _owned_revision(session, revision_id, user)
        if revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=409, detail="Only validated revisions can be restored")
        project = _owned_project(session, revision.project_id, user)
        session.refresh(project, with_for_update=True)
        if project.archived:
            raise HTTPException(status_code=404, detail="Project not found")
        project.selection_version += 1
        project.current_revision_id = revision.id
        project.title = revision.title
        session.commit()
        return _project_summary(project, session, settings_dep)

    @app.get("/v1/revisions/{revision_id}/export", tags=["revisions"])
    def export_revision(
        revision_id: UUID,
        session: SessionDep,
        settings_dep: SettingsDep,
        user: UserDep,
        format: Literal["html", "zip"] = "zip",
    ) -> Response:
        revision = _owned_revision(session, revision_id, user)
        if revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        html = ArtifactStore(settings_dep.artifact_root).read_html(revision.artifact_digest)
        if format == "html":
            content = html.encode()
            media_type = "text/html"
        else:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("index.html", html)
                bundle.writestr(
                    "metadata.json",
                    json.dumps(
                        {
                            "revision_id": str(revision.id),
                            "sha256": revision.artifact_digest,
                            "model": revision.model_name,
                            "spec": revision.spec,
                            "validation": revision.validation_report,
                        },
                        ensure_ascii=False,
                    ),
                )
            content = buffer.getvalue()
            media_type = "application/zip"
        return Response(
            content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="game-{revision.id}.{format}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post(
        "/v1/revisions/{revision_id}/feedback",
        response_model=FeedbackSummary,
        tags=["feedback"],
    )
    def submit_feedback(
        revision_id: UUID,
        body: SubmitFeedbackRequest,
        session: SessionDep,
        user: UserDep,
    ) -> FeedbackSummary:
        revision = _owned_revision(session, revision_id, user)
        if revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        feedback_id = session.scalar(
            pg_insert(GameFeedback)
            .values(
                user_id=user.id,
                project_id=revision.project_id,
                revision_id=revision.id,
                rating=body.rating,
                reasons=[item.value for item in body.reasons],
                comment=body.comment,
            )
            .on_conflict_do_update(
                constraint="uq_game_feedback_user_revision",
                set_={
                    "rating": body.rating,
                    "reasons": [item.value for item in body.reasons],
                    "comment": body.comment,
                    "updated_at": func.now(),
                },
            )
            .returning(GameFeedback.id)
        )
        session.commit()
        feedback = session.get(GameFeedback, feedback_id)
        if feedback is None:
            raise HTTPException(status_code=500, detail="Feedback could not be saved")
        return _feedback_summary(feedback)

    @app.get(
        "/v1/projects/{project_id}/feedback",
        response_model=list[FeedbackSummary],
        tags=["feedback"],
    )
    def project_feedback(
        project_id: UUID, session: SessionDep, user: UserDep
    ) -> list[FeedbackSummary]:
        _owned_project(session, project_id, user)
        items = session.scalars(
            select(GameFeedback)
            .where(GameFeedback.project_id == project_id, GameFeedback.user_id == user.id)
            .order_by(GameFeedback.updated_at.desc())
        ).all()
        return [_feedback_summary(item) for item in items]

    @app.get("/v1/revisions/{revision_id}/preview", tags=["previews"])
    def preview(
        revision_id: UUID,
        session: SessionDep,
        settings_dep: SettingsDep,
        user: UserDep,
    ) -> Response:
        revision = _owned_revision(session, revision_id, user)
        if revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        html = ArtifactStore(settings_dep.artifact_root).read_html(revision.artifact_digest)
        return _preview_response(html)

    @app.post(
        "/v1/revisions/{revision_id}/publish",
        response_model=PublishResponse,
        tags=["revisions"],
    )
    def publish(
        revision_id: UUID,
        session: SessionDep,
        settings_dep: SettingsDep,
        user: UserDep,
    ) -> PublishResponse:
        revision = _owned_revision(session, revision_id, user)
        if revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        project = _owned_project(session, revision.project_id, user)
        session.refresh(project, with_for_update=True)
        publication = session.scalar(
            select(PublicGame).where(PublicGame.project_id == revision.project_id)
        )
        if publication is None:
            publication = PublicGame(
                project_id=revision.project_id,
                revision_id=revision.id,
                author_id=user.id,
                title=revision.title,
                slug=secrets.token_urlsafe(12),
            )
            session.add(publication)
        elif publication.revision_id != revision.id:
            publication.revision_id = revision.id
        session.commit()
        return PublishResponse(
            public_game_id=publication.id,
            share_url=f"{settings_dep.public_base_url}/play/{publication.slug}",
        )

    @app.get("/v1/public-games", response_model=list[PublicGameSummary], tags=["community"])
    def public_feed(
        session: SessionDep,
        settings_dep: SettingsDep,
        user: UserDep,
        sort: Literal["newest", "popular"] = "newest",
        mine: bool = False,
    ) -> list[PublicGameSummary]:
        likes = (
            select(func.count())
            .where(PublicGameLike.public_game_id == PublicGame.id)
            .correlate(PublicGame)
            .scalar_subquery()
        )
        statement = select(PublicGame)
        if mine:
            statement = statement.where(PublicGame.author_id == user.id)
        if sort == "popular":
            statement = statement.order_by(likes.desc())
        games = session.scalars(
            statement.order_by(PublicGame.created_at.desc(), PublicGame.id.desc())
        ).all()
        return [_public_game_summary(game, session, settings_dep, user) for game in games]

    @app.delete("/v1/public-games/{public_game_id}", status_code=204, tags=["community"])
    def delete_public_game(public_game_id: UUID, session: SessionDep, user: UserDep) -> Response:
        game = session.scalar(
            select(PublicGame).where(
                PublicGame.id == public_game_id, PublicGame.author_id == user.id
            )
        )
        if game is None:
            raise HTTPException(status_code=404, detail="Published game not found")
        # Legacy slugs must not resurrect an explicitly removed publication.
        for revision in session.scalars(
            select(Revision).where(Revision.project_id == game.project_id)
        ).all():
            revision.public_slug = None
        session.delete(game)
        session.commit()
        return Response(status_code=204)

    @app.put(
        "/v1/public-games/{public_game_id}",
        response_model=PublicGameSummary,
        tags=["community"],
    )
    def update_public_game(
        public_game_id: UUID,
        body: PublicGameUpdateRequest,
        session: SessionDep,
        settings_dep: SettingsDep,
        user: UserDep,
    ) -> PublicGameSummary:
        public_game = session.scalar(
            select(PublicGame).where(
                PublicGame.id == public_game_id, PublicGame.author_id == user.id
            )
        )
        if public_game is None:
            raise HTTPException(status_code=404, detail="Published game not found")
        public_game.title = body.title
        session.commit()
        return _public_game_summary(public_game, session, settings_dep, user)

    @app.put(
        "/v1/public-games/{public_game_id}/like",
        response_model=PublicGameSummary,
        tags=["community"],
    )
    def like_public_game(
        public_game_id: UUID,
        session: SessionDep,
        settings_dep: SettingsDep,
        user: UserDep,
    ) -> PublicGameSummary:
        public_game = session.get(PublicGame, public_game_id)
        if public_game is None:
            raise HTTPException(status_code=404, detail="Published game not found")
        session.execute(
            pg_insert(PublicGameLike)
            .values(public_game_id=public_game.id, user_id=user.id)
            .on_conflict_do_nothing()
        )
        session.commit()
        return _public_game_summary(public_game, session, settings_dep, user)

    @app.delete(
        "/v1/public-games/{public_game_id}/like",
        response_model=PublicGameSummary,
        tags=["community"],
    )
    def unlike_public_game(
        public_game_id: UUID,
        session: SessionDep,
        settings_dep: SettingsDep,
        user: UserDep,
    ) -> PublicGameSummary:
        public_game = session.get(PublicGame, public_game_id)
        if public_game is None:
            raise HTTPException(status_code=404, detail="Published game not found")
        session.execute(
            delete(PublicGameLike).where(
                PublicGameLike.public_game_id == public_game.id,
                PublicGameLike.user_id == user.id,
            )
        )
        session.commit()
        return _public_game_summary(public_game, session, settings_dep, user)

    @app.post(
        "/v1/public-games/{public_game_id}/remix",
        response_model=ProjectSummary,
        status_code=status.HTTP_201_CREATED,
        tags=["community"],
    )
    def remix_public_game(
        public_game_id: UUID,
        body: RemixRequest,
        session: SessionDep,
        settings_dep: SettingsDep,
        user: UserDep,
    ) -> ProjectSummary:
        public_game = session.get(PublicGame, public_game_id)
        if public_game is None:
            raise HTTPException(status_code=404, detail="Published game not found")
        source_revision = session.get(Revision, public_game.revision_id)
        source_project = session.get(Project, public_game.project_id)
        if source_revision is None or source_project is None:
            raise HTTPException(status_code=404, detail="Published game not found")
        project = Project(
            owner_id=user.id,
            title=body.title or f"Ремикс: {public_game.title}",
            prompt=(
                f"Доработай игру «{public_game.title}», сохраняя её текущую "
                "спецификацию и механику вне явно запрошенных изменений."
            ),
            forked_from_revision_id=source_revision.id,
        )
        session.add(project)
        session.flush()
        revision = Revision(
            project_id=project.id,
            parent_id=source_revision.id,
            artifact_digest=source_revision.artifact_digest,
            title=source_revision.title,
            summary=source_revision.summary,
            genre=source_revision.genre,
            audience=source_revision.audience,
            spec=source_revision.spec,
            status=source_revision.status,
            model_name=source_revision.model_name,
            validation_report=source_revision.validation_report,
        )
        session.add(revision)
        session.flush()
        project.current_revision_id = revision.id
        session.commit()
        return _project_summary(project, session, settings_dep)

    @app.get("/play/{slug}", tags=["previews"])
    def shared_game(slug: str, session: SessionDep, settings_dep: SettingsDep) -> Response:
        revision = session.scalar(
            select(Revision)
            .join(PublicGame, PublicGame.revision_id == Revision.id)
            .where(PublicGame.slug == slug, Revision.status == RevisionStatus.VALIDATED.value)
        )
        if revision is None:
            revision = session.scalar(
                select(Revision).where(
                    Revision.public_slug == slug,
                    Revision.status == RevisionStatus.VALIDATED.value,
                )
            )
        if revision is None:
            raise HTTPException(status_code=404, detail="Shared game not found")
        html = ArtifactStore(settings_dep.artifact_root).read_html(revision.artifact_digest)
        return _preview_response(html)

    @app.post("/v1/revisions/{revision_id}/analytics", status_code=204, tags=["analytics"])
    def record_analytics(
        revision_id: UUID, body: AnalyticsEventRequest, session: SessionDep, user: UserDep
    ) -> Response:
        revision = _owned_revision(session, revision_id, user)
        if revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        if len(json.dumps(body.payload)) > 2000:
            raise HTTPException(status_code=413, detail="Analytics payload is too large")
        session.add(
            AnalyticsEvent(
                revision_id=revision.id,
                session_id=body.session_id,
                event_type=body.event_type,
                payload=body.payload,
            )
        )
        session.commit()
        return Response(status_code=204)

    @app.get("/v1/analytics/summary", tags=["analytics"])
    def analytics_summary(session: SessionDep, user: UserDep) -> list[dict[str, object]]:
        rows = session.execute(
            select(Revision.genre, AnalyticsEvent.event_type, func.count(AnalyticsEvent.id))
            .join(Revision, Revision.id == AnalyticsEvent.revision_id)
            .join(Project, Project.id == Revision.project_id)
            .where(Project.owner_id == user.id)
            .group_by(Revision.genre, AnalyticsEvent.event_type)
            .order_by(func.count(AnalyticsEvent.id).desc())
        ).all()
        return [{"genre": genre, "event": event, "count": count} for genre, event, count in rows]

    return app


app = create_app()
