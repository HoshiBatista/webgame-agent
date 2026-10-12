"""Persisted generation workflow use cases called by Celery tasks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prompt2play.adapters.artifacts import ArtifactStore
from prompt2play.application.ports import ModelGateway, ModelResult
from prompt2play.config import Settings
from prompt2play.contracts import (
    Finding,
    GameSpec,
    GeneratedGame,
    RevisionStatus,
    RunState,
    ValidationReport,
)
from prompt2play.models import (
    AnalyticsEvent,
    GenerationRun,
    ModelInvocation,
    OutboxEvent,
    Project,
    Revision,
    RunEvent,
)
from prompt2play.validation.browser import validate_in_browser
from prompt2play.validation.static import validate_html

GatewayFactory = Callable[[], ModelGateway]


def _locked_run(session: Session, run_id: UUID) -> GenerationRun | None:
    statement = select(GenerationRun).where(GenerationRun.id == run_id).with_for_update()
    return session.scalar(statement)


def record_event(
    session: Session,
    run: GenerationRun,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append one ordered workflow event in the current transaction."""

    sequence = session.scalar(
        select(func.coalesce(func.max(RunEvent.sequence), 0)).where(RunEvent.run_id == run.id)
    )
    session.add(
        RunEvent(
            run_id=run.id,
            sequence=int(sequence or 0) + 1,
            event_type=event_type,
            message=message,
            payload=payload or {},
        )
    )


def enqueue_stage(session: Session, stage: str, run_id: UUID) -> None:
    """Persist a small Celery command in the transactional outbox."""

    session.add(OutboxEvent(event_type=stage, payload={"run_id": str(run_id)}))


def _claim(
    session: Session,
    run_id: UUID,
    expected: RunState | tuple[RunState, ...],
    active: RunState,
    message: str,
) -> tuple[int, GenerationRun] | None:
    run = _locked_run(session, run_id)
    expected_states = expected if isinstance(expected, tuple) else (expected,)
    if run is None or run.state not in {state.value for state in expected_states}:
        return None
    if run.cancel_requested:
        run.state = RunState.CANCELLED.value
        record_event(session, run, "cancelled", "Генерация отменена пользователем")
        return None
    run.execution_fence += 1
    run.state = active.value
    record_event(session, run, active.value, message)
    session.flush()
    return run.execution_fence, run


def _record_invocation(
    session: Session,
    run_id: UUID,
    purpose: str,
    model_name: str,
    result: ModelResult[GameSpec] | ModelResult[GeneratedGame],
) -> None:
    session.add(
        ModelInvocation(
            run_id=run_id,
            purpose=purpose,
            model_name=model_name,
            provider_response_id=result.response_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            status="completed",
        )
    )


def _analytics_context(session: Session) -> str:
    rows = session.execute(
        select(Revision.genre, AnalyticsEvent.event_type, func.count(AnalyticsEvent.id))
        .join(Revision, Revision.id == AnalyticsEvent.revision_id)
        .where(Revision.status == RevisionStatus.VALIDATED.value)
        .group_by(Revision.genre, AnalyticsEvent.event_type)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .limit(20)
    ).all()
    if not rows:
        return "Недостаточно агрегированных данных; не делай выводов о прошлых играх."
    return "\n".join(f"genre={genre}; event={event}; count={count}" for genre, event, count in rows)


def fail_run(session_factory: Callable[[], Session], run_id: UUID, fence: int, error: str) -> None:
    """Finish the current fenced execution with a user-visible error."""

    with session_factory() as session, session.begin():
        run = _locked_run(session, run_id)
        if run is None or run.execution_fence != fence:
            return
        run.state = RunState.FAILED.value
        run.error = error[:2000]
        record_event(session, run, "failed", "Генерация завершилась с ошибкой")


def specify_run(
    session_factory: Callable[[], Session], gateway_factory: GatewayFactory, run_id: UUID
) -> bool:
    """Claim, specify and enqueue generation for one run."""

    with session_factory() as session, session.begin():
        claimed = _claim(
            session,
            run_id,
            (RunState.ACCEPTED, RunState.SPECIFYING),
            RunState.SPECIFYING,
            "Luna формирует механику и критерии игры",
        )
        if claimed is None:
            return False
        fence, run = claimed
        prompt = run.prompt
        if run.revision_instruction:
            prompt = f"{prompt}\nИзменение пользователя: {run.revision_instruction}"
        context = _analytics_context(session)

    gateway = gateway_factory()
    try:
        result = gateway.specify(prompt, context)
    except Exception as exc:
        fail_run(session_factory, run_id, fence, f"OpenAI specification failed: {exc}")
        return False

    with session_factory() as session, session.begin():
        current_run = _locked_run(session, run_id)
        if (
            current_run is None
            or current_run.execution_fence != fence
            or current_run.cancel_requested
        ):
            return False
        current_run.spec = result.value.model_dump(mode="json")
        current_run.state = RunState.GENERATING.value
        project = session.get(Project, current_run.project_id)
        if project is not None and project.title == "Новая игра":
            project.title = result.value.title
        _record_invocation(session, run_id, "specification", gateway.model_name, result)
        record_event(
            session,
            current_run,
            "specified",
            "Спецификация готова",
            {"title": result.value.title},
        )
        enqueue_stage(session, "generate", run_id)
    return True


def generate_run(
    session_factory: Callable[[], Session],
    gateway_factory: GatewayFactory,
    artifact_store: ArtifactStore,
    run_id: UUID,
    *,
    repair: bool = False,
) -> bool:
    """Generate one complete candidate and enqueue independent validation."""

    expected = RunState.REPAIRING if repair else RunState.GENERATING
    with session_factory() as session, session.begin():
        claimed = _claim(
            session,
            run_id,
            expected,
            expected,
            "Luna исправляет найденные дефекты" if repair else "Luna пишет игру",
        )
        if claimed is None:
            return False
        fence, run = claimed
        if repair:
            run.repair_count += 1
        spec_data = run.spec
        if spec_data is None:
            raise RuntimeError("Generation run has no specification")
        spec = GameSpec.model_validate(spec_data)
        parent_id = run.revision_id or run.parent_revision_id
        parent = session.get(Revision, parent_id) if parent_id else None
        parent_html = artifact_store.read_html(parent.artifact_digest) if parent else None
        findings = None
        if repair and parent and parent.validation_report:
            report = ValidationReport.model_validate(parent.validation_report)
            findings = "\n".join(
                f"{item.code}: {item.message}; fix: {item.repair_hint}" for item in report.findings
            )
        prompt = run.prompt
        instruction = run.revision_instruction

    gateway = gateway_factory()
    try:
        result = gateway.generate(
            prompt,
            spec,
            parent_html=parent_html,
            revision_instruction=instruction,
            findings=findings,
        )
        stored = artifact_store.commit(result.value.html, spec, run_id)
    except Exception as exc:
        fail_run(session_factory, run_id, fence, f"OpenAI generation failed: {exc}")
        return False

    with session_factory() as session, session.begin():
        current_run = _locked_run(session, run_id)
        if (
            current_run is None
            or current_run.execution_fence != fence
            or current_run.cancel_requested
        ):
            return False
        revision = Revision(
            project_id=current_run.project_id,
            parent_id=parent_id,
            artifact_digest=stored.digest,
            title=result.value.title,
            summary=result.value.summary,
            genre=spec.genre,
            audience=spec.audience,
            status=RevisionStatus.CANDIDATE.value,
            model_name=gateway.model_name,
        )
        session.add(revision)
        session.flush()
        current_run.revision_id = revision.id
        current_run.state = RunState.STATIC_VALIDATION.value
        _record_invocation(
            session, run_id, "repair" if repair else "generation", gateway.model_name, result
        )
        record_event(
            session,
            current_run,
            "candidate_committed",
            "Кандидат сохранён неизменяемой ревизией",
            {"revision_id": str(revision.id), "bytes": stored.size_bytes},
        )
        enqueue_stage(session, "validate", run_id)
    return True


def validate_run(
    session_factory: Callable[[], Session],
    artifact_store: ArtifactStore,
    settings: Settings,
    run_id: UUID,
) -> bool:
    """Run authoritative static and browser gates and choose repair or promotion."""

    with session_factory() as session, session.begin():
        claimed = _claim(
            session,
            run_id,
            (RunState.STATIC_VALIDATION, RunState.BROWSER_VALIDATION),
            RunState.BROWSER_VALIDATION,
            "Проверяем безопасность, mobile WebView и игровой ввод",
        )
        if claimed is None:
            return False
        fence, run = claimed
        revision_id = run.revision_id
        if revision_id is None:
            raise RuntimeError("Validation run has no revision")
        revision = session.get(Revision, revision_id)
        if revision is None:
            raise RuntimeError("Revision does not exist")
        digest = revision.artifact_digest

    html = artifact_store.read_html(digest)
    static_findings, checks = validate_html(html)
    browser_passed: bool | None = None
    browser_findings: list[Finding] = []
    browser_checks: list[str] = []
    if not static_findings and settings.browser_validation:
        html_path = artifact_store.entrypoint_path(digest)
        browser_passed, browser_findings, browser_checks = validate_in_browser(
            html_path, settings.browser_timeout_ms
        )
    elif not settings.browser_validation:
        browser_checks.append("browser_unverified: disabled by configuration")

    findings = static_findings + browser_findings
    browser_status: Literal["passed", "failed", "unverified"] = (
        "passed"
        if browser_passed is True
        else "failed"
        if browser_passed is False
        else "unverified"
    )
    passed = not findings and browser_passed is True
    report = ValidationReport(
        passed=passed,
        static_passed=not static_findings,
        browser_passed=browser_passed,
        browser_status=browser_status,
        findings=findings,
        checks=checks + browser_checks,
    )

    with session_factory() as session, session.begin():
        current_run = _locked_run(session, run_id)
        if current_run is None or current_run.execution_fence != fence:
            return False
        revision = session.get(Revision, revision_id)
        project = session.get(Project, current_run.project_id)
        if revision is None or project is None:
            return False
        revision.validation_report = report.model_dump(mode="json")
        artifact_store.write_validation(revision.id, revision.validation_report)
        if passed:
            revision.status = RevisionStatus.VALIDATED.value
            project.current_revision_id = revision.id
            project.title = revision.title
            current_run.state = RunState.SUCCEEDED.value
            current_run.error = None
            record_event(
                session,
                current_run,
                "succeeded",
                "Игра прошла проверки и готова к запуску",
                {"revision_id": str(revision.id)},
            )
        else:
            revision.status = RevisionStatus.REJECTED.value
            if findings and current_run.repair_count < current_run.max_repairs:
                current_run.state = RunState.REPAIRING.value
                record_event(
                    session,
                    current_run,
                    "repair_scheduled",
                    "Найдены исправимые дефекты — запускаем ограниченный repair",
                    {"findings": [item.code for item in findings]},
                )
                enqueue_stage(session, "repair", current_run.id)
            else:
                current_run.state = RunState.FAILED.value
                current_run.error = (
                    "Browser validation is unverified"
                    if browser_passed is None
                    else "Validation failed after bounded repair"
                )
                record_event(
                    session,
                    current_run,
                    "failed",
                    "Кандидат не прошёл обязательные проверки",
                    {"findings": [item.code for item in findings]},
                )
    return passed
