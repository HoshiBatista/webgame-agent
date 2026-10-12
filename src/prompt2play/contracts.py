"""Versioned API and model contracts for Prompt2Play."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=4000)]


class RunState(StrEnum):
    """Persisted generation workflow states."""

    ACCEPTED = "accepted"
    SPECIFYING = "specifying"
    GENERATING = "generating"
    STATIC_VALIDATION = "static_validation"
    BROWSER_VALIDATION = "browser_validation"
    REPAIRING = "repairing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RevisionStatus(StrEnum):
    """Release status of an immutable game revision."""

    CANDIDATE = "candidate"
    VALIDATED = "validated"
    REJECTED = "rejected"


class Rubric(BaseModel):
    """Observable acceptance criterion produced before game code."""

    id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=4, max_length=500)
    verification: str = Field(min_length=4, max_length=500)


class GameSpec(BaseModel):
    """Schema-constrained interpretation of the user's game request."""

    title: str = Field(min_length=1, max_length=100)
    genre: Literal["arcade", "puzzle", "clicker", "platformer", "runner", "other"]
    audience: str = Field(min_length=1, max_length=200)
    player_goal: str = Field(min_length=4, max_length=500)
    core_loop: str = Field(min_length=4, max_length=800)
    controls: list[str] = Field(min_length=1, max_length=8)
    visual_direction: str = Field(min_length=4, max_length=500)
    accessibility: list[str] = Field(min_length=1, max_length=8)
    win_condition: str = Field(min_length=2, max_length=400)
    lose_condition: str = Field(min_length=2, max_length=400)
    rubrics: list[Rubric] = Field(min_length=3, max_length=10)


class GeneratedGame(BaseModel):
    """Structured output returned by the generation model."""

    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=4, max_length=500)
    html: str = Field(min_length=1000, max_length=450_000)


class Finding(BaseModel):
    """Normalized validation defect."""

    code: str
    severity: Literal["error", "warning"]
    message: str
    repair_hint: str


class ValidationReport(BaseModel):
    """Static and browser validation evidence."""

    passed: bool
    static_passed: bool
    browser_passed: bool | None = None
    browser_status: Literal["passed", "failed", "unverified"] = "unverified"
    findings: list[Finding] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    validator_version: str = "1"


class CreateProjectRequest(BaseModel):
    """Create a project and its initial generation run."""

    prompt: Prompt


class ReviseRequest(BaseModel):
    """Request an iterative child revision."""

    instruction: Prompt


class AnalyticsEventRequest(BaseModel):
    """Privacy-minimal gameplay analytics submitted by the host UI."""

    session_id: str = Field(min_length=8, max_length=100)
    event_type: Literal["preview_open", "game_start", "win", "lose", "restart", "share"]
    payload: dict[str, Any] = Field(default_factory=dict)


class RevisionSummary(BaseModel):
    """Public revision metadata; host filesystem paths are never exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID | None
    title: str
    genre: str
    audience: str
    status: RevisionStatus
    model_name: str
    created_at: datetime
    preview_url: str | None = None
    share_url: str | None = None
    validation: ValidationReport | None = None


class ProjectSummary(BaseModel):
    """Project card used by the gallery and editor."""

    id: UUID
    title: str
    prompt: str
    current_revision_id: UUID | None
    created_at: datetime
    revisions: list[RevisionSummary] = Field(default_factory=list)


class RunSummary(BaseModel):
    """Observable workflow state returned to the creator UI."""

    id: UUID
    project_id: UUID
    state: RunState
    error: str | None
    revision_id: UUID | None
    repair_count: int
    created_at: datetime
    updated_at: datetime


class RunEventMessage(BaseModel):
    """One resumable Server-Sent Event payload."""

    id: int
    event: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
