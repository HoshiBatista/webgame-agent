"""Deterministic, task-specific scoring for Prompt2Play golden evaluations."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from prompt2play.contracts import GameSpec
from prompt2play.validation.static import validate_html


class GoldenCase(BaseModel):
    """One representative or adversarial game-generation request."""

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    prompt: str = Field(min_length=8, max_length=4000)
    expected_genres: list[str] = Field(min_length=1)
    audience_terms: list[str] = Field(min_length=1)


class CandidateScore(BaseModel):
    """Machine-readable criteria for one specification and game candidate."""

    case_id: str
    passed: bool
    score: float = Field(ge=0, le=1)
    criteria: dict[str, bool]
    finding_codes: list[str]


def load_golden_cases(path: Path) -> list[GoldenCase]:
    """Load and validate a version-controlled evaluation dataset."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Golden evaluation dataset must be a JSON list")
    cases = [GoldenCase.model_validate(item) for item in raw]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Golden evaluation case IDs must be unique")
    return cases


def score_candidate(case: GoldenCase, spec: GameSpec, html: str) -> CandidateScore:
    """Score observable product requirements without another model judge."""

    findings, _ = validate_html(html)
    audience = f"{spec.audience} {' '.join(spec.accessibility)}".lower()
    controls = " ".join(spec.controls).lower()
    normalized_html = html.lower()
    criteria = {
        "genre_alignment": spec.genre in case.expected_genres,
        "audience_alignment": any(term.lower() in audience for term in case.audience_terms),
        "touch_controls": "touch" in controls or "pointer" in controls,
        "observable_rubrics": len(spec.rubrics) >= 3,
        "complete_game_states": bool(spec.win_condition.strip() and spec.lose_condition.strip()),
        "static_release_gate": not findings,
        "host_analytics": "prompt2play-game" in normalized_html and "game_event" in normalized_html,
        "self_contained_size": 1000 <= len(html.encode("utf-8")) <= 512_000,
    }
    score = sum(criteria.values()) / len(criteria)
    return CandidateScore(
        case_id=case.id,
        passed=score >= 0.875 and not findings,
        score=score,
        criteria=criteria,
        finding_codes=[finding.code for finding in findings],
    )
