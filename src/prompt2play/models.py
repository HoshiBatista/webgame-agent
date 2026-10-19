"""PostgreSQL persistence models for the durable workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return an aware timestamp suitable for persisted events."""

    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative model base."""


class User(Base):
    """Creator account provisioned by an administrator."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(80))
    username_normalized: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    projects: Mapped[list[Project]] = relationship(back_populates="owner")
    auth_sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    public_games: Mapped[list[PublicGame]] = relationship(back_populates="author")
    public_game_likes: Mapped[list[PublicGameLike]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    """Server-side opaque login session; raw tokens are never persisted."""

    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="auth_sessions")


class Project(Base):
    """A user-visible game project with immutable child revisions."""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(100), default="Новая игра")
    prompt: Mapped[str] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    selection_version: Mapped[int] = mapped_column(Integer, default=0)
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    forked_from_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "revisions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_projects_forked_from_revision_id_revisions",
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    runs: Mapped[list[GenerationRun]] = relationship(back_populates="project")
    revisions: Mapped[list[Revision]] = relationship(
        back_populates="project", foreign_keys="Revision.project_id"
    )
    owner: Mapped[User | None] = relationship(back_populates="projects")


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
    feedback_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    repair_count: Mapped[int] = mapped_column(Integer, default=0)
    max_repairs: Mapped[int] = mapped_column(Integer, default=2)
    execution_fence: Mapped[int] = mapped_column(Integer, default=0)
    project_version: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    artifact_digest: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    genre: Mapped[str] = mapped_column(String(32))
    audience: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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


class IdempotencyRecord(Base):
    """A request reservation that makes accepted API commands safely repeatable."""

    __tablename__ = "idempotency_records"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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


class PublicGame(Base):
    """One explicitly published, stable revision per creator project."""

    __tablename__ = "public_games"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), unique=True, index=True
    )
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    author: Mapped[User] = relationship(back_populates="public_games")
    likes: Mapped[list[PublicGameLike]] = relationship(
        back_populates="public_game", cascade="all, delete-orphan"
    )


class PublicGameLike(Base):
    """A creator's idempotent like of a published game."""

    __tablename__ = "public_game_likes"

    public_game_id: Mapped[UUID] = mapped_column(
        ForeignKey("public_games.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    public_game: Mapped[PublicGame] = relationship(back_populates="likes")
    user: Mapped[User] = relationship(back_populates="public_game_likes")


class GameFeedback(Base):
    """A creator rating used as bounded memory for later generations."""

    __tablename__ = "game_feedback"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_game_feedback_rating"),
        UniqueConstraint("user_id", "revision_id", name="uq_game_feedback_user_revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
