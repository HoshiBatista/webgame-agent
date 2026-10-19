"""Workflow state-transition regressions without external infrastructure."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import prompt2play.application.workflow as workflow
from prompt2play.adapters.artifacts import ArtifactStore
from prompt2play.application.ports import ModelGateway
from prompt2play.application.workflow import _finish_cancelled
from prompt2play.config import Settings
from prompt2play.contracts import RunState
from prompt2play.models import GenerationRun, OutboxEvent, Project, Revision, RunEvent


def test_cancellation_seen_after_external_call_is_persisted() -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        prompt="Сделай игру про космос",
        state=RunState.GENERATING.value,
        cancel_requested=True,
    )
    session = Mock(spec=Session)
    session.scalar.return_value = 0

    assert _finish_cancelled(session, run) is True
    assert run.state == RunState.CANCELLED.value
    event = session.add.call_args.args[0]
    assert isinstance(event, RunEvent)
    assert event.event_type == "cancelled"


def test_external_call_continues_when_cancellation_was_not_requested() -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        prompt="Сделай игру про космос",
        cancel_requested=False,
    )
    session = Mock(spec=Session)

    assert _finish_cancelled(session, run) is False
    session.add.assert_not_called()


def test_provider_factory_error_finishes_run_instead_of_leaving_it_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = GenerationRun(
        id=uuid4(), project_id=uuid4(), prompt="Создай игру про космос", execution_fence=1
    )
    project = Project(id=run.project_id, prompt=run.prompt, owner_id=None)
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.begin.return_value = nullcontext()
    session.get.return_value = project
    monkeypatch.setattr(workflow, "_claim", lambda *_args: (1, run))
    fail = Mock()
    monkeypatch.setattr(workflow, "fail_run", fail)

    def broken_gateway() -> ModelGateway:
        raise RuntimeError("Provider configuration missing")

    assert not workflow.specify_run(lambda: session, broken_gateway, run.id)
    assert "Provider configuration missing" in fail.call_args.args[3]


def test_model_failure_cannot_overwrite_a_cancelled_run(monkeypatch: pytest.MonkeyPatch) -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        prompt="Создай игру про космос",
        state="cancelled",
        cancel_requested=True,
        execution_fence=2,
    )
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.begin.return_value = nullcontext()
    session.scalar.return_value = 1
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)

    workflow.fail_run(lambda: session, run.id, 2, "Provider timeout")

    assert run.state == "cancelled"
    assert run.error is None


def test_queued_work_cannot_restart_an_archived_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        prompt="Создай игру про космос",
        state="accepted",
        cancel_requested=False,
    )
    session = Mock(spec=Session)
    session.get.return_value = Project(id=run.project_id, archived=True)
    session.scalar.return_value = 0
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)

    assert workflow._claim(session, run.id, RunState.ACCEPTED, RunState.SPECIFYING, "start") is None
    assert run.state == "cancelled"
    session.flush.assert_not_called()


def test_duplicate_delivery_cannot_claim_an_active_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        prompt="Создай игру",
        state="generating",
        execution_fence=0,
        cancel_requested=False,
    )
    session = Mock(spec=Session)
    session.get.return_value = Project(id=run.project_id, archived=False)
    session.scalar.return_value = 0
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)

    assert workflow._claim(session, run.id, RunState.GENERATING, RunState.GENERATING, "first")
    assert (
        workflow._claim(session, run.id, RunState.GENERATING, RunState.GENERATING, "duplicate")
        is None
    )
    assert run.execution_fence == 1


def test_storage_failure_finishes_validation_and_releases_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        revision_id=uuid4(),
        state="static_validation",
        prompt="Создай игру",
        execution_fence=0,
        cancel_requested=False,
    )
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.begin.return_value = nullcontext()
    session.scalar.return_value = 0
    session.get.side_effect = [
        Project(id=run.project_id, archived=False),
        Revision(id=run.revision_id, artifact_digest="a" * 64, spec=None, parent_id=None),
    ]
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)
    store = Mock(spec=ArtifactStore)
    store.read_html.side_effect = FileNotFoundError("Missing artifact")

    assert not workflow.validate_run(lambda: session, store, Settings(), run.id)
    assert run.state == "failed"
    assert run.lease_token is None
    assert "FileNotFoundError" in (run.error or "")


def test_expired_execution_is_fenced_and_cannot_overwrite_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        state="generating",
        execution_fence=3,
        lease_token=uuid4(),
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        cancel_requested=False,
    )
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.begin.return_value = nullcontext()
    session.scalars.return_value.all.return_value = [run]
    session.scalar.return_value = 0
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)

    assert workflow.expire_stale_runs(session) == 1
    assert run.state == "failed"
    assert run.execution_fence == 4
    assert run.lease_token is None
    error = run.error
    workflow.fail_run(lambda: session, run.id, 3, "Late provider error")
    assert run.error == error


def test_late_duplicate_repair_cannot_exceed_attempt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        prompt="Создай игру",
        state="repairing",
        execution_fence=0,
        repair_count=2,
        max_repairs=2,
        cancel_requested=False,
    )
    session = Mock(spec=Session)
    session.get.return_value = Project(id=run.project_id, archived=False)
    session.scalar.return_value = 0
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)

    assert (
        workflow._claim(session, run.id, RunState.REPAIRING, RunState.REPAIRING, "repair") is None
    )
    assert run.state == "failed"
    assert run.execution_fence == 0
    assert run.repair_count == 2


def test_artifact_factory_failure_is_handled_inside_claimed_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        state="generating",
        execution_fence=0,
        cancel_requested=False,
    )
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.begin.return_value = nullcontext()
    session.get.return_value = Project(id=run.project_id, archived=False)
    session.scalar.return_value = 0
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)
    gateway = Mock()

    def unavailable() -> ArtifactStore:
        raise PermissionError("Storage unavailable")

    assert not workflow.generate_run(lambda: session, gateway, unavailable, run.id)
    assert run.state == "failed"
    assert run.lease_token is None
    gateway.assert_not_called()


@pytest.mark.parametrize("selection_version", [1, 2])
def test_candidate_promotion_respects_the_latest_creator_choice(
    monkeypatch: pytest.MonkeyPatch,
    selection_version: int,
) -> None:
    restored = uuid4()
    project = Project(
        id=uuid4(),
        prompt="demo",
        current_revision_id=restored,
        archived=False,
        selection_version=selection_version,
    )
    revision = Revision(
        id=uuid4(),
        project_id=project.id,
        artifact_digest="a" * 64,
        parent_id=None,
        spec=None,
        title="Late candidate",
    )
    run = GenerationRun(
        id=uuid4(),
        project_id=project.id,
        revision_id=revision.id,
        state="static_validation",
        execution_fence=0,
        project_version=1,
        cancel_requested=False,
    )
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.begin.return_value = nullcontext()
    session.get.side_effect = [project, revision, project, revision]
    session.scalar.return_value = 0
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)
    monkeypatch.setattr(workflow, "validate_in_browser", lambda *_args: (True, [], ["fixture"]))
    store = Mock(spec=ArtifactStore)
    store.read_html.return_value = (
        Path(__file__).parents[2] / "golden/smoke-game/index.html"
    ).read_text()

    assert workflow.validate_run(lambda: session, store, Settings(), run.id)
    assert run.state == "succeeded"
    assert revision.status == "validated"
    assert project.current_revision_id == (revision.id if selection_version == 1 else restored)


def test_missing_browser_runtime_does_not_schedule_model_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(id=uuid4(), archived=False)
    revision = Revision(
        id=uuid4(), project_id=project.id, artifact_digest="a" * 64, parent_id=None, spec=None
    )
    run = GenerationRun(
        id=uuid4(),
        project_id=project.id,
        revision_id=revision.id,
        state="static_validation",
        execution_fence=0,
        cancel_requested=False,
        repair_count=0,
        max_repairs=2,
    )
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.begin.return_value = nullcontext()
    session.get.side_effect = [project, revision, project, revision]
    session.scalar.return_value = 0
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)
    monkeypatch.setattr(
        workflow,
        "validate_in_browser",
        lambda *_args: (None, [], ["browser_unverified: runtime unavailable"]),
    )
    store = Mock(spec=ArtifactStore)
    store.read_html.return_value = (
        Path(__file__).parents[2] / "golden/smoke-game/index.html"
    ).read_text()

    assert not workflow.validate_run(lambda: session, store, Settings(), run.id)
    assert run.state == "failed"
    assert run.repair_count == 0
    assert revision.validation_report is not None
    assert revision.validation_report["browser_status"] == "unverified"
    assert all(not isinstance(call.args[0], OutboxEvent) for call in session.add.call_args_list)


def test_pending_preclaim_delivery_is_recovered_once(monkeypatch: pytest.MonkeyPatch) -> None:
    run = GenerationRun(
        id=uuid4(),
        project_id=uuid4(),
        state="accepted",
        updated_at=datetime.now(UTC) - timedelta(hours=1),
    )
    session = Mock(spec=Session)
    session.scalars.return_value.all.return_value = [run]
    session.scalar.side_effect = [None, 0]
    assert workflow.recover_pending_stages(session, 600) == 1
    command = session.add.call_args_list[0].args[0]
    assert isinstance(command, OutboxEvent)
    assert command.event_type == "specify"
    session.reset_mock()
    session.scalar.side_effect = None
    session.scalar.return_value = 1
    assert workflow.recover_pending_stages(session, 600) == 0
    session.add.assert_not_called()
