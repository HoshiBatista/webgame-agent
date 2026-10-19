"""Idempotently provision the initial administrator from environment settings."""

from __future__ import annotations

from sqlalchemy import delete, select, update

from prompt2play.auth import hash_password, normalize_username, verify_password
from prompt2play.config import get_settings
from prompt2play.db import SessionLocal
from prompt2play.models import AuthSession, Project, User


def bootstrap_admin() -> User:
    """Create or refresh the configured admin and claim legacy ownerless projects."""

    settings = get_settings()
    username = (settings.admin_username or "").strip()
    password = settings.admin_password.get_secret_value() if settings.admin_password else ""
    if not username or len(username) > 80:
        raise RuntimeError("P2P_ADMIN_USERNAME must contain 1-80 characters")
    if len(password) < 12:
        raise RuntimeError("P2P_ADMIN_PASSWORD must contain at least 12 characters")

    normalized = normalize_username(username)
    with SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.username_normalized == normalized))
        if user is None:
            user = User(
                username=username,
                username_normalized=normalized,
                password_hash=hash_password(password),
                is_admin=True,
                is_active=True,
            )
            session.add(user)
            session.flush()
        else:
            user.username = username
            if not verify_password(password, user.password_hash):
                user.password_hash = hash_password(password)
                session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            user.is_admin = True
            user.is_active = True
        session.execute(update(Project).where(Project.owner_id.is_(None)).values(owner_id=user.id))
        return user


def main() -> None:
    """CLI entry point used by the deployment bootstrap job."""

    user = bootstrap_admin()
    print(f"Administrator ready: {user.username}")


if __name__ == "__main__":
    main()
