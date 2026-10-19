"""Password and opaque-session primitives for closed creator access."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from prompt2play.models import AuthSession, User

PBKDF2_ITERATIONS = 600_000


def normalize_username(username: str) -> str:
    """Produce the canonical case-insensitive username key."""

    return unicodedata.normalize("NFKC", username).strip().casefold()


def hash_password(password: str) -> str:
    """Hash a password with a random salt and an explicit upgradeable format."""

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    salt_text = base64.urlsafe_b64encode(salt).decode()
    digest_text = base64.urlsafe_b64encode(digest).decode()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_text}${digest_text}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password without leaking comparison timing."""

    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            base64.urlsafe_b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    """Return the database-safe digest for an opaque session token."""

    return hashlib.sha256(token.encode()).hexdigest()


def create_auth_session(session: Session, user: User, ttl_hours: int) -> tuple[AuthSession, str]:
    """Create and persist a login session, returning its one-time raw token."""

    token = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        token_digest=token_digest(token),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    session.add(auth_session)
    return auth_session, token


def resolve_user(session: Session, token: str | None) -> User | None:
    """Resolve an active, unexpired opaque session."""

    if not token:
        return None
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.token_digest == token_digest(token))
    )
    if auth_session is None or auth_session.expires_at <= datetime.now(UTC):
        return None
    user = auth_session.user
    return user if user.is_active else None
