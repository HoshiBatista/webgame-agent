"""Authentication primitive tests that do not require infrastructure."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy.orm import Session

from prompt2play.auth import hash_password, normalize_username, resolve_user, verify_password
from prompt2play.models import AuthSession, User


def test_username_normalization_is_unicode_and_case_insensitive() -> None:
    assert normalize_username("  Ａdmin  ") == "admin"
    assert normalize_username("ИВАН") == normalize_username("иван")


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("a sufficiently long password")
    second = hash_password("a sufficiently long password")

    assert first != second
    assert verify_password("a sufficiently long password", first)
    assert not verify_password("wrong password", first)
    assert not verify_password("password", "invalid")


def test_expired_session_is_not_resolved() -> None:
    user = User(
        id=uuid4(),
        username="creator",
        username_normalized="creator",
        password_hash="hash",
    )
    expired = AuthSession(
        token_digest="digest",
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    expired.user = user
    session = Mock(spec=Session)
    session.scalar.return_value = expired

    assert resolve_user(session, "token") is None
