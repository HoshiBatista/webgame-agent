"""Add closed creator accounts, opaque sessions, and project ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261017_0003"
down_revision: str | None = "20261017_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add identity tables safely when migration one created current metadata."""

    connection = op.get_bind()
    inspector = inspect(connection)
    if not inspector.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("username", sa.String(length=80), nullable=False),
            sa.Column("username_normalized", sa.String(length=80), nullable=False),
            sa.Column("password_hash", sa.String(length=256), nullable=False),
            sa.Column("is_admin", sa.Boolean(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_users_username_normalized", "users", ["username_normalized"], unique=True
        )

    inspector = inspect(connection)
    if not inspector.has_table("auth_sessions"):
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("token_digest", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_auth_sessions_token_digest", "auth_sessions", ["token_digest"], unique=True
        )
        op.create_index(
            "ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], unique=False
        )

    project_columns = {item["name"] for item in inspect(connection).get_columns("projects")}
    if "owner_id" not in project_columns:
        op.add_column("projects", sa.Column("owner_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            "fk_projects_owner_id_users",
            "projects",
            "users",
            ["owner_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_projects_owner_id", "projects", ["owner_id"], unique=False)


def downgrade() -> None:
    """Remove creator ownership and authentication storage."""

    connection = op.get_bind()
    project_columns = {item["name"] for item in inspect(connection).get_columns("projects")}
    if "owner_id" in project_columns:
        indexes = {item["name"] for item in inspect(connection).get_indexes("projects")}
        if "ix_projects_owner_id" in indexes:
            op.drop_index("ix_projects_owner_id", table_name="projects")
        owner_foreign_key = next(
            (
                item["name"]
                for item in inspect(connection).get_foreign_keys("projects")
                if item["constrained_columns"] == ["owner_id"]
            ),
            None,
        )
        if owner_foreign_key:
            op.drop_constraint(owner_foreign_key, "projects", type_="foreignkey")
        op.drop_column("projects", "owner_id")
    if inspect(connection).has_table("auth_sessions"):
        op.drop_table("auth_sessions")
    if inspect(connection).has_table("users"):
        op.drop_table("users")
