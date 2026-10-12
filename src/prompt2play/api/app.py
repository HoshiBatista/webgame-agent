"""FastAPI transport for projects, durable runs, previews and analytics."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from prompt2play.adapters.artifacts import ArtifactStore
from prompt2play.application.workflow import enqueue_stage, record_event
from prompt2play.config import Settings, get_settings
from prompt2play.contracts import (
    AnalyticsEventRequest,
    CreateProjectRequest,
    ProjectSummary,
    ReviseRequest,
    RevisionStatus,
    RevisionSummary,
    RunEventMessage,
    RunState,
    RunSummary,
    ValidationReport,
)
from prompt2play.db import SessionLocal, get_session
from prompt2play.models import AnalyticsEvent, GenerationRun, Project, Revision, RunEvent

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


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


def _revision_summary(revision: Revision, settings: Settings) -> RevisionSummary:
    validation = (
        ValidationReport.model_validate(revision.validation_report)
        if revision.validation_report
        else None
    )
    preview = None
    if revision.status == RevisionStatus.VALIDATED.value:
        preview = f"{settings.public_base_url}/v1/revisions/{revision.id}/preview"
    share = (
        f"{settings.public_base_url}/play/{revision.public_slug}" if revision.public_slug else None
    )
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
        validation=validation,
    )


def _project_summary(project: Project, session: Session, settings: Settings) -> ProjectSummary:
    revisions = session.scalars(
        select(Revision)
        .where(Revision.project_id == project.id)
        .order_by(Revision.created_at.desc())
    ).all()
    return ProjectSummary(
        id=project.id,
        title=project.title,
        prompt=project.prompt,
        current_revision_id=project.current_revision_id,
        created_at=project.created_at,
        revisions=[_revision_summary(item, settings) for item in revisions],
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
        "object-src 'none'; base-uri 'none'; form-action 'none'"
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
        description="Prompt → Luna → validated self-contained HTML5 game",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )

    @app.get("/healthz", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"])
    def ready(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.post("/v1/projects", status_code=status.HTTP_202_ACCEPTED, tags=["projects"])
    def create_project(
        body: CreateProjectRequest,
        session: SessionDep,
        _: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, str]:
        project = Project(prompt=body.prompt)
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
        record_event(session, run, "accepted", "Запрос принят в генерацию")
        enqueue_stage(session, "specify", run.id)
        session.commit()
        _try_dispatch()
        return {"project_id": str(project.id), "run_id": str(run.id)}

    @app.get("/v1/projects", response_model=list[ProjectSummary], tags=["projects"])
    def list_projects(session: SessionDep, settings_dep: SettingsDep) -> list[ProjectSummary]:
        projects = session.scalars(select(Project).order_by(Project.created_at.desc())).all()
        return [_project_summary(item, session, settings_dep) for item in projects]

    @app.get("/v1/projects/{project_id}", response_model=ProjectSummary, tags=["projects"])
    def get_project(
        project_id: UUID, session: SessionDep, settings_dep: SettingsDep
    ) -> ProjectSummary:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return _project_summary(project, session, settings_dep)

    @app.get("/v1/runs/{run_id}", response_model=RunSummary, tags=["runs"])
    def get_run(run_id: UUID, session: SessionDep) -> RunSummary:
        run = session.get(GenerationRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_summary(run)

    @app.post("/v1/runs/{run_id}/cancel", response_model=RunSummary, tags=["runs"])
    def cancel_run(run_id: UUID, session: SessionDep) -> RunSummary:
        run = session.get(GenerationRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.state not in {RunState.SUCCEEDED.value, RunState.FAILED.value}:
            run.cancel_requested = True
            record_event(session, run, "cancel_requested", "Запрошена остановка генерации")
            session.commit()
        return _run_summary(run)

    @app.get("/v1/runs/{run_id}/events", tags=["runs"])
    async def run_events(
        run_id: UUID,
        request: Request,
        last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
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
        _: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, str]:
        revision = session.get(Revision, revision_id)
        if revision is None or revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        project = session.get(Project, revision.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        run = GenerationRun(
            project_id=project.id,
            parent_revision_id=revision.id,
            prompt=project.prompt,
            revision_instruction=body.instruction,
            state=RunState.ACCEPTED.value,
            max_repairs=settings.max_repair_attempts,
        )
        session.add(run)
        session.flush()
        record_event(session, run, "accepted", "Запрос на новую ревизию принят")
        enqueue_stage(session, "specify", run.id)
        session.commit()
        _try_dispatch()
        return {"project_id": str(project.id), "run_id": str(run.id)}

    @app.get("/v1/revisions/{revision_id}", response_model=RevisionSummary, tags=["revisions"])
    def get_revision(
        revision_id: UUID, session: SessionDep, settings_dep: SettingsDep
    ) -> RevisionSummary:
        revision = session.get(Revision, revision_id)
        if revision is None:
            raise HTTPException(status_code=404, detail="Revision not found")
        return _revision_summary(revision, settings_dep)

    @app.get("/v1/revisions/{revision_id}/preview", tags=["previews"])
    def preview(revision_id: UUID, session: SessionDep, settings_dep: SettingsDep) -> Response:
        revision = session.get(Revision, revision_id)
        if revision is None or revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        html = ArtifactStore(settings_dep.artifact_root).read_html(revision.artifact_digest)
        return _preview_response(html)

    @app.post("/v1/revisions/{revision_id}/publish", tags=["revisions"])
    def publish(
        revision_id: UUID, session: SessionDep, settings_dep: SettingsDep
    ) -> dict[str, str]:
        revision = session.get(Revision, revision_id)
        if revision is None or revision.status != RevisionStatus.VALIDATED.value:
            raise HTTPException(status_code=404, detail="Validated revision not found")
        if revision.public_slug is None:
            revision.public_slug = secrets.token_urlsafe(12)
            session.commit()
        return {"share_url": f"{settings_dep.public_base_url}/play/{revision.public_slug}"}

    @app.get("/play/{slug}", tags=["previews"])
    def shared_game(slug: str, session: SessionDep, settings_dep: SettingsDep) -> Response:
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
        revision_id: UUID, body: AnalyticsEventRequest, session: SessionDep
    ) -> Response:
        revision = session.get(Revision, revision_id)
        if revision is None or revision.status != RevisionStatus.VALIDATED.value:
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
    def analytics_summary(session: SessionDep) -> list[dict[str, object]]:
        rows = session.execute(
            select(Revision.genre, AnalyticsEvent.event_type, func.count(AnalyticsEvent.id))
            .join(Revision, Revision.id == AnalyticsEvent.revision_id)
            .group_by(Revision.genre, AnalyticsEvent.event_type)
            .order_by(func.count(AnalyticsEvent.id).desc())
        ).all()
        return [{"genre": genre, "event": event, "count": count} for genre, event, count in rows]

    return app


app = create_app()
