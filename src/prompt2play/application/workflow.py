"""Persisted generation workflow use cases called by Celery tasks."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, Literal, ParamSpec, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from prompt2play.adapters.artifacts import ArtifactStore
from prompt2play.application.ports import ModelGateway, ModelResult
from prompt2play.config import Settings, get_settings
from prompt2play.contracts import (
    Finding,
    GameSpec,
    GeneratedGame,
    RevisionStatus,
    RunState,
    ValidationReport,
)
from prompt2play.feedback import build_feedback_context
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
from prompt2play.validation.revision import (
    is_targeted_revision,
    preserve_revision_invariants,
    validate_revision_invariants,
)
from prompt2play.validation.static import validate_html

GatewayFactory = Callable[[], ModelGateway]
StageParams = ParamSpec("StageParams")
_claim_context: ContextVar[tuple[UUID, int, UUID] | None] = ContextVar("stage_claim", default=None)


def _release_lease(run: GenerationRun) -> None:
    run.lease_token = None
    run.lease_expires_at = None


def _guard_stage(function: Callable[StageParams, bool]) -> Callable[StageParams, bool]:
    """Finish unexpected stage failures, including storage and soft time-limit errors."""

    @wraps(function)
    def guarded(*args: StageParams.args, **kwargs: StageParams.kwargs) -> bool:
        context = _claim_context.set(None)
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            claim = _claim_context.get()
            if claim is None:
                raise
            factory = cast(Callable[[], Session], args[0] if args else kwargs["session_factory"])
            run_id, fence, lease_token = claim
            with factory() as session, session.begin():
                run = _locked_run(session, run_id)
                if run is None:
                    return False
                if not (
                    run.lease_token == lease_token
                    or (run.lease_token is None and run.execution_fence == fence - 1)
                ):
                    return False
                if not _finish_cancelled(session, run):
                    run.state = RunState.FAILED.value
                    run.error = f"Stage {function.__name__} failed: {type(exc).__name__}"
                    _release_lease(run)
                    record_event(session, run, "failed", "Ошибка выполнения этапа генерации")
            return False
        finally:
            _claim_context.reset(context)

    return guarded


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
    project = session.get(Project, run.project_id)
    if project is None or project.archived:
        run.cancel_requested = True
    if run.cancel_requested:
        run.state = RunState.CANCELLED.value
        record_event(session, run, "cancelled", "Генерация отменена пользователем")
        _release_lease(run)
        return None
    if run.lease_token is not None:
        return None
    if active == RunState.REPAIRING and run.repair_count >= run.max_repairs:
        run.state = RunState.FAILED.value
        run.error = "Repair attempt limit reached"
        record_event(session, run, "failed", "Исчерпан лимит исправлений")
        return None
    run.execution_fence += 1
    run.lease_token = uuid4()
    run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=get_settings().stage_lease_seconds)
    _claim_context.set((run.id, run.execution_fence, run.lease_token))
    run.state = active.value
    record_event(session, run, active.value, message)
    session.flush()
    return run.execution_fence, run


def _finish_cancelled(session: Session, run: GenerationRun) -> bool:
    """Persist a cancellation noticed after an external model/browser call."""

    if not run.cancel_requested:
        return False
    if run.state == RunState.CANCELLED.value:
        _release_lease(run)
        return True
    run.state = RunState.CANCELLED.value
    _release_lease(run)
    record_event(session, run, "cancelled", "Генерация отменена пользователем")
    return True


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


def _analytics_context(session: Session, user_id: UUID) -> str:
    rows = session.execute(
        select(Revision.genre, AnalyticsEvent.event_type, func.count(AnalyticsEvent.id))
        .join(Revision, Revision.id == AnalyticsEvent.revision_id)
        .join(Project, Project.id == Revision.project_id)
        .where(Revision.status == RevisionStatus.VALIDATED.value)
        .where(Project.owner_id == user_id)
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
        if _finish_cancelled(session, run):
            return
        run.state = RunState.FAILED.value
        _release_lease(run)
        run.error = error[:2000]
        record_event(session, run, "failed", "Генерация завершилась с ошибкой")


@_guard_stage
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
            "Модель формирует механику и критерии игры",
        )
        if claimed is None:
            return False
        fence, run = claimed
        prompt = run.prompt
        if run.revision_instruction:
            prompt = f"{prompt}\nИзменение пользователя: {run.revision_instruction}"
        parent = session.get(Revision, run.parent_revision_id) if run.parent_revision_id else None
        if parent is not None and parent.spec is not None:
            prompt = (
                f"{prompt}\nТекущая спецификация, которую нужно сохранять вне запрошенных "
                f"изменений: {GameSpec.model_validate(parent.spec).model_dump_json()}"
            )
        project = session.get(Project, run.project_id)
        learning = (
            build_feedback_context(session, project.id, project.owner_id)
            if project is not None and project.owner_id is not None
            else None
        )
        run.feedback_snapshot = (
            {**learning.snapshot, "context": learning.text}
            if learning
            else {"feedback_ids": [], "context": None}
        )
        context = (
            _analytics_context(session, project.owner_id)
            if project is not None and project.owner_id is not None
            else "Недостаточно агрегированных данных; не делай выводов о прошлых играх."
        )
        if learning:
            context = f"{context}\n\nНакопленная обратная связь создателя:\n{learning.text}"

    try:
        gateway = gateway_factory()
        result = gateway.specify(prompt, context)
    except Exception as exc:
        fail_run(session_factory, run_id, fence, f"Model specification failed: {exc}")
        return False

    with session_factory() as session, session.begin():
        project = session.get(Project, run.project_id, with_for_update=True)
        current_run = _locked_run(session, run_id)
        if current_run is None or current_run.execution_fence != fence:
            return False
        if _finish_cancelled(session, current_run):
            return False
        _release_lease(current_run)
        specification = result.value
        parent = (
            session.get(Revision, current_run.parent_revision_id)
            if current_run.parent_revision_id
            else None
        )
        if parent is not None and parent.spec is not None:
            specification = preserve_revision_invariants(
                GameSpec.model_validate(parent.spec),
                specification,
                current_run.revision_instruction,
            )
        current_run.spec = specification.model_dump(mode="json")
        current_run.state = RunState.GENERATING.value
        if project is not None and project.title == "Новая игра":
            project.title = specification.title
        _record_invocation(session, run_id, "specification", gateway.model_name, result)
        record_event(
            session,
            current_run,
            "specified",
            "Спецификация готова",
            {"title": specification.title},
        )
        enqueue_stage(session, "generate", run_id)
    return True


@_guard_stage
def generate_run(
    session_factory: Callable[[], Session],
    gateway_factory: GatewayFactory,
    artifact_store: ArtifactStore | Callable[[], ArtifactStore],
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
            "Модель исправляет найденные дефекты" if repair else "Модель пишет игру",
        )
        if claimed is None:
            return False
        fence, run = claimed
        if not isinstance(artifact_store, ArtifactStore):
            artifact_store = artifact_store()
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
        snapshot = run.feedback_snapshot or {}
        saved_feedback_context = snapshot.get("context")
        feedback_context = (
            saved_feedback_context if isinstance(saved_feedback_context, str) else None
        )

    try:
        gateway = gateway_factory()
        result = gateway.generate(
            prompt,
            spec,
            parent_html=parent_html,
            revision_instruction=instruction,
            findings=findings,
            feedback_context=feedback_context,
        )
        stored = artifact_store.commit(result.value.html, spec, run_id)
    except Exception as exc:
        fail_run(session_factory, run_id, fence, f"Model generation failed: {exc}")
        return False

    with session_factory() as session, session.begin():
        session.get(Project, run.project_id, with_for_update=True)
        current_run = _locked_run(session, run_id)
        if current_run is None or current_run.execution_fence != fence:
            return False
        if _finish_cancelled(session, current_run):
            return False
        _release_lease(current_run)
        revision = Revision(
            project_id=current_run.project_id,
            parent_id=parent_id,
            artifact_digest=stored.digest,
            title=result.value.title,
            summary=result.value.summary,
            genre=spec.genre,
            audience=spec.audience,
            spec=spec.model_dump(mode="json"),
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


@_guard_stage
def validate_run(
    session_factory: Callable[[], Session],
    artifact_store: ArtifactStore | Callable[[], ArtifactStore],
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
        if not isinstance(artifact_store, ArtifactStore):
            artifact_store = artifact_store()
        revision_id = run.revision_id
        if revision_id is None:
            raise RuntimeError("Validation run has no revision")
        revision = session.get(Revision, revision_id)
        if revision is None:
            raise RuntimeError("Revision does not exist")
        digest = revision.artifact_digest
        revision_spec = GameSpec.model_validate(revision.spec) if revision.spec else None
        parent_id = revision.parent_id
        parent = session.get(Revision, parent_id) if parent_id else None
        parent_spec = GameSpec.model_validate(parent.spec) if parent and parent.spec else None
        parent_digest = parent.artifact_digest if parent else None
        revision_instruction = run.revision_instruction

    html = artifact_store.read_html(digest)
    static_findings, checks = validate_html(html)
    invariant_findings: list[Finding] = []
    if parent_spec is not None and revision_spec is not None:
        invariant_findings, invariant_checks = validate_revision_invariants(
            parent_spec, revision_spec, revision_instruction
        )
        checks.extend(invariant_checks)
    elif parent_id is not None:
        checks.append("revision_invariants_unverified: specification unavailable")
    browser_passed: bool | None = None
    browser_findings: list[Finding] = []
    browser_checks: list[str] = []
    if not static_findings and not invariant_findings and settings.browser_validation:
        html_path = artifact_store.entrypoint_path(digest)
        if parent_digest is not None and is_targeted_revision(revision_instruction):
            browser_passed, browser_findings, browser_checks = validate_in_browser(
                html_path,
                settings.browser_timeout_ms,
                parent_html_path=artifact_store.entrypoint_path(parent_digest),
            )
        else:
            browser_passed, browser_findings, browser_checks = validate_in_browser(
                html_path, settings.browser_timeout_ms
            )
    elif not settings.browser_validation:
        browser_checks.append("browser_unverified: disabled by configuration")

    findings = static_findings + invariant_findings + browser_findings
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
        project = session.get(Project, run.project_id, with_for_update=True)
        current_run = _locked_run(session, run_id)
        if current_run is None or current_run.execution_fence != fence:
            return False
        if _finish_cancelled(session, current_run):
            return False
        _release_lease(current_run)
        revision = session.get(Revision, revision_id)
        if revision is None or project is None:
            raise RuntimeError("Validated revision or project no longer exists")
        revision.validation_report = report.model_dump(mode="json")
        artifact_store.write_validation(revision.id, revision.validation_report)
        if passed:
            revision.status = RevisionStatus.VALIDATED.value
            promoted = run_can_promote(current_run, project)
            if promoted:
                project.current_revision_id = revision.id
                project.title = revision.title
            current_run.state = RunState.SUCCEEDED.value
            current_run.error = None
            record_event(
                session,
                current_run,
                "succeeded",
                "Игра прошла проверки и готова к запуску",
                {"revision_id": str(revision.id), "promoted": promoted},
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


def run_can_promote(run: GenerationRun, project: Project) -> bool:
    """A later restore or revision request always takes precedence over an old run."""

    return not project.archived and run.project_version == project.selection_version


def recover_pending_stages(session: Session, grace_seconds: int) -> int:
    """Redeliver old unclaimed commands after pre-claim failures or broker delivery loss."""

    stages = {
        "accepted": "specify",
        "generating": "generate",
        "repairing": "repair",
        "static_validation": "validate",
    }
    now = datetime.now(UTC)
    runs = session.scalars(
        select(GenerationRun)
        .where(
            GenerationRun.state.in_(stages),
            GenerationRun.lease_token.is_(None),
            GenerationRun.updated_at < now - timedelta(seconds=grace_seconds),
        )
        .with_for_update(skip_locked=True)
    ).all()
    count = 0
    for run in runs:
        pending = session.scalar(
            select(OutboxEvent.id)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.payload["run_id"].as_string() == str(run.id),
            )
            .limit(1)
        )
        if pending is None:
            enqueue_stage(session, stages[run.state], run.id)
            record_event(
                session, run, "delivery_recovered", "Повторяем доставку незапущенного этапа"
            )
            run.updated_at = now
            count += 1
    return count


def expire_stale_runs(session: Session) -> int:
    """Fence timed-out executions without repeating model calls or expiring queued work."""

    now = datetime.now(UTC)
    terminal = {"succeeded", "failed", "cancelled"}
    runs = session.scalars(
        select(GenerationRun)
        .where(
            GenerationRun.state.not_in(terminal),
            GenerationRun.lease_expires_at <= now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for run in runs:
        run.execution_fence += 1
        _release_lease(run)
        if not _finish_cancelled(session, run):
            run.state = RunState.FAILED.value
            run.error = "Stage deadline exceeded; create a new generation request"
            record_event(session, run, "failed", "Превышено время выполнения этапа")
    return len(runs)
