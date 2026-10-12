"""Validated resumable draft data; never executable code or a release artifact."""

from __future__ import annotations

from typing import Any

import jsonschema

from prompt2play.contracts import BuildPlan, GameSpec
from prompt2play.contracts.models import digest, obj, stable

from .visual_quality import validate_source_review
from .workspace import WorkspaceLimits, normalized_path

DRAFT_SCHEMA = obj(
    {
        "version": {"const": "authoring-draft-v1"},
        "request_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "spec": {"type": "object"},
        "plan": {"type": "object"},
        "runtime": {"type": "object"},
        "files": {"type": "object", "additionalProperties": {"type": "string"}},
        "history": {"type": "array", "items": {"type": "object"}},
        "operations": {"type": "integer", "minimum": 0},
        "quick_checks": {"type": "integer", "minimum": 0},
        "turn": {"type": "integer", "minimum": 0},
        "feedback": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "string"},
        "visual_reviews": {"type": "array", "items": {"type": "object"}},
        "phase": {"enum": ["author", "review", "rendered_review", "ready"]},
        "review_attempt": {"type": "integer", "minimum": 0},
        "review_feedback": {"type": "array", "items": {"type": "object"}},
    }
)
# Optional additions preserve immutable v1 checkpoints from earlier workers.
DRAFT_SCHEMA["properties"].update(
    test_scenario={"type": "object"},
    browser_result={"type": "object"},
    mechanics={"type": "array"},
    pending_submit={"type": "boolean"},
    adaptive={"type": "object"},
    rendered_reviews={"type": "array", "items": {"type": "object"}},
    packager={"type": "object"},
    requirement_reviews={"type": "array", "items": {"type": "object"}},
    migration={"type": "object"},
    request_identity_version={"const": 2},
)


def validate_draft_state(state: dict[str, Any]) -> None:
    # Plans have a separate 100 KB contract bound. A draft includes source,
    # feedback and history and uses the same 12 MiB envelope as its endpoint.
    envelope = 32 if "adaptive" in state else 12
    if len(stable(state).encode()) > envelope * 1024 * 1024:
        raise ValueError("Authoring checkpoint exceeds its byte envelope")
    try:
        jsonschema.validate(state, DRAFT_SCHEMA)
    except jsonschema.ValidationError:
        raise ValueError("Invalid authoring checkpoint structure") from None
    GameSpec(state["spec"])
    BuildPlan(state["plan"])
    if "adaptive" in state:
        from prompt2play.contracts.adaptive import validate_adaptive

        validate_adaptive(state["adaptive"], state["spec"], state["plan"])
    if state.get("test_scenario"):
        from prompt2play.validation.runner import validate_acceptance

        validate_acceptance(state["test_scenario"])
    modular = state["plan"]["format"] == "runtime-modules-v2"
    limits = (
        WorkspaceLimits(max_files=32, max_file_bytes=2_000_000, max_total_bytes=4_000_000)
        if modular
        else WorkspaceLimits()
    )
    files = state["files"]
    if (
        len(files) > limits.max_files
        or sum(len(s.encode()) for s in files.values()) > limits.max_total_bytes
    ):
        raise ValueError("Draft exceeds source byte quota")
    for path, source in files.items():
        if (
            normalized_path(path, allow_assets=modular) != path
            or not source.strip()
            or len(source.encode()) > limits.max_file_bytes
        ):
            raise ValueError("Invalid draft source path or size")
    # Runtime bytes are still independently bound by assemble_runtime on submission.
    if not isinstance(state["runtime"].get("sha256"), str):
        raise ValueError("Draft runtime identity is missing")

    if state["phase"] == "ready":
        if "adaptive" in state:
            from .coverage import validate_coverage

            coverage = state.get("requirement_reviews", [])
            if (
                not coverage
                or coverage[-1].get("source_sha256") != digest(files)
                or coverage[-1].get("build_plan_sha256") != digest(state["plan"])
                or validate_coverage(
                    coverage[-1]["review"], state["adaptive"]["requirements"], files
                )
                not in ("covered", "human_required")
            ):
                raise ValueError("Ready adaptive draft lacks matching requirement coverage")
            rendered = state.get("rendered_reviews", [])
            if (
                not rendered
                or rendered[-1].get("source_sha256") != digest(files)
                or rendered[-1].get("build_plan_sha256") != digest(state["plan"])
                or rendered[-1].get("status") not in ("rendered_ready", "human_required")
            ):
                raise ValueError(
                    "Ready adaptive draft lacks a matching rendered review or human gate"
                )
        reviews = state["visual_reviews"]
        if (
            not reviews
            or reviews[-1].get("source_sha256") != digest(files)
            or reviews[-1].get("build_plan_sha256") != digest(state["plan"])
            or reviews[-1].get("status") != "source_ready"
            or not validate_source_review({"criteria": reviews[-1].get("criteria")}, files)
        ):
            raise ValueError("Ready draft lacks a matching successful source review")
