"""Worker entry-point failures without Redis, PostgreSQL or model calls."""

from contextlib import nullcontext
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import prompt2play.application.workflow as workflow
import prompt2play.tasks as tasks
from prompt2play.models import GenerationRun, Project


def test_worker_storage_initialization_is_inside_the_workflow_guard(
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
    monkeypatch.setattr(tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(workflow, "_locked_run", lambda *_args: run)
    monkeypatch.setattr(
        tasks, "_artifacts", Mock(side_effect=PermissionError("Volume unavailable"))
    )
    dispatch = Mock()
    monkeypatch.setattr(tasks.dispatch_outbox, "delay", dispatch)

    assert tasks.generate_task.run(str(run.id)) is False
    assert run.state == "failed"
    assert run.lease_token is None
    dispatch.assert_called_once()


def test_worker_retries_database_failure_before_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    class Retried(Exception):
        pass

    retry = Mock(side_effect=Retried)
    monkeypatch.setattr(tasks.generate_task, "retry", retry)
    error = OperationalError("connection unavailable", {}, OSError("database offline"))
    monkeypatch.setattr(tasks, "generate_run", Mock(side_effect=error))

    with pytest.raises(Retried):
        tasks.generate_task.run(str(uuid4()))
    assert retry.call_args.kwargs["exc"] is error
    assert retry.call_args.kwargs["max_retries"] == 5
