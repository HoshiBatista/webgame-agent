"""Request idempotency policy tests without infrastructure dependencies."""

from contextlib import nullcontext
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from prompt2play.api.app import _request_hash, _reserve_idempotency, _scoped_idempotency_key
from prompt2play.models import GenerationRun, IdempotencyRecord


def test_request_hash_is_stable_and_payload_sensitive() -> None:
    first = _request_hash("create_project", "Игра про пчелу")
    assert first == _request_hash("create_project", "Игра про пчелу")
    assert first != _request_hash("create_project", "Игра про кота")


def test_idempotency_keys_are_scoped_to_the_creator() -> None:
    first_user = uuid4()
    second_user = uuid4()
    assert _scoped_idempotency_key(first_user, None) is None
    assert _scoped_idempotency_key(first_user, "browser-request") == _scoped_idempotency_key(
        first_user, "browser-request"
    )
    assert _scoped_idempotency_key(first_user, "browser-request") != _scoped_idempotency_key(
        second_user, "browser-request"
    )


def test_missing_key_skips_idempotency_storage() -> None:
    session = Mock(spec=Session)
    assert _reserve_idempotency(session, None, "create_project", "hash") == (None, None)
    session.get.assert_not_called()


def test_equivalent_key_returns_the_committed_run() -> None:
    project_id = uuid4()
    run_id = uuid4()
    record = IdempotencyRecord(
        key="same-request",
        operation="create_project",
        request_hash="hash",
        project_id=project_id,
        run_id=run_id,
    )
    run = GenerationRun(id=run_id, project_id=project_id, prompt="Игра про пчелу")
    session = Mock(spec=Session)
    session.get.side_effect = [record, run]

    reserved, existing = _reserve_idempotency(session, "same-request", "create_project", "hash")

    assert reserved is record
    assert existing is run


def test_reused_key_with_different_payload_is_rejected() -> None:
    record = IdempotencyRecord(
        key="same-request",
        operation="create_project",
        request_hash="old-hash",
    )
    session = Mock(spec=Session)
    session.get.return_value = record

    with pytest.raises(HTTPException) as error:
        _reserve_idempotency(session, "same-request", "create_project", "new-hash")

    assert error.value.status_code == 409


def test_new_key_is_reserved_without_creating_a_run() -> None:
    session = Mock(spec=Session)
    session.get.return_value = None
    session.begin_nested.return_value = nullcontext()

    record, existing = _reserve_idempotency(session, "new-request", "create_project", "hash")

    assert record is not None
    assert record.key == "new-request"
    assert existing is None
    session.add.assert_called_once_with(record)
    session.flush.assert_called_once_with()
