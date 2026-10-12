"""PostgreSQL persistence models for the durable workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return an aware timestamp suitable for persisted events."""

    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative model base."""


class Project(Base):
    """A user-visible game project with immutable child revisions."""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(100), default="Новая игра")
    prompt: Mapped[str] = mapped_column(Text)
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    runs: Mapped[list[GenerationRun]] = relationship(back_populates="project")
    revisions: Mapped[list[Revision]] = relationship(
        back_populates="project", foreign_keys="Revision.project_id"
    )


class GenerationRun(Base):
    """Canonical state of one initial generation or revision request."""

    __tablename__ = "generation_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("revisions.id", ondelete="SET NULL"), nullable=True
    )
    prompt: Mapped[str] = mapped_column(Text)
    revision_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="accepted", index=True)
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    max_repairs: Mapped[int] = mapped_column(Integer, default=2)
    execution_fence: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    project: Mapped[Project] = relationship(back_populates="runs")
    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run", order_by="RunEvent.sequence", cascade="all, delete-orphan"
    )


class Revision(Base):
    """Immutable generated artifact metadata and lineage."""

    __tablename__ = "revisions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("revisions.id", ondelete="SET NULL"), nullable=True
    )
    artifact_digest: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    genre: Mapped[str] = mapped_column(String(32))
    audience: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), default="candidate")
    model_name: Mapped[str] = mapped_column(String(100))
    validation_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    public_slug: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped[Project] = relationship(back_populates="revisions", foreign_keys=[project_id])


class RunEvent(Base):
    """Durable, ordered progress event for resumable SSE."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[GenerationRun] = relationship(back_populates="events")


class OutboxEvent(Base):
    """Transactional handoff from PostgreSQL state to Celery delivery."""

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelInvocation(Base):
    """Provider usage and latency without storing sensitive prompt bodies."""

    __tablename__ = "model_invocations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str] = mapped_column(String(100))
    provider_response_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalyticsEvent(Base):
    """Coarse gameplay outcome used to rank successful mechanics."""

    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("revisions.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
