"""Versioned API and model contracts for Prompt2Play."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=4000)]
DisplayTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


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


class FeedbackReason(StrEnum):
    """Stable improvement dimensions understood by the learning-context builder."""

    MUSIC = "music"
    VISUALS = "visuals"
    CONTROLS = "controls"
    DIFFICULTY = "difficulty"
    GAMEPLAY = "gameplay"
    PERFORMANCE = "performance"
    BUGS = "bugs"
    OTHER = "other"


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
    validator_version: str = "2"


class CreateProjectRequest(BaseModel):
    """Create a project and its initial generation run."""

    prompt: Prompt


class LoginRequest(BaseModel):
    """Credentials for an administrator-provisioned creator account."""

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=512)


class UserSummary(BaseModel):
    """Safe identity data returned to the creator UI."""

    id: UUID
    username: str
    is_admin: bool


class PublicGameUpdateRequest(BaseModel):
    """Editable presentation metadata; the published artifact remains immutable."""

    title: DisplayTitle


class RemixRequest(BaseModel):
    """Optional name for a private project forked from a public game."""

    title: DisplayTitle | None = None


class SubmitFeedbackRequest(BaseModel):
    """Creator evaluation that becomes bounded context for later generations."""

    rating: int = Field(ge=1, le=5)
    reasons: list[FeedbackReason] = Field(default_factory=list, max_length=8)
    comment: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None

    @model_validator(mode="after")
    def explain_non_perfect_rating(self) -> SubmitFeedbackRequest:
        """Require an actionable signal when the game is not rated perfectly."""

        if self.rating < 5 and not self.reasons and not self.comment:
            raise ValueError("A rating below 5 requires a reason or comment")
        return self


class FeedbackSummary(BaseModel):
    """Persisted evaluation returned to the creator UI."""

    id: UUID
    revision_id: UUID
    rating: int
    reasons: list[FeedbackReason]
    comment: str | None
    created_at: datetime
    updated_at: datetime


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
    public_game_id: UUID | None = None
    public_title: str | None = None
    validation: ValidationReport | None = None


class ChatMessage(BaseModel):
    """Persisted creator request and its generation outcome."""

    id: UUID
    text: str
    state: RunState
    created_at: datetime
    revision_id: UUID | None
    error: str | None


class ProjectSummary(BaseModel):
    """Project card used by the gallery and editor."""

    id: UUID
    title: str
    prompt: str
    current_revision_id: UUID | None
    forked_from_revision_id: UUID | None = None
    created_at: datetime
    revisions: list[RevisionSummary] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list)


class PublicGameSummary(BaseModel):
    """Safe social-feed projection of one explicitly published revision."""

    id: UUID
    revision_id: UUID
    title: str
    author_username: str
    genre: str
    audience: str
    like_count: int
    liked_by_me: bool
    is_mine: bool
    share_url: str
    published_at: datetime
    updated_at: datetime


class PublishResponse(BaseModel):
    """Publication identity returned after publishing or updating a project."""

    public_game_id: UUID
    share_url: str


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
