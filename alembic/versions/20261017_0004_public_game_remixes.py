"""Add stable public games, likes, and remix provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "20261017_0004"
down_revision: str | None = "20261017_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create community tables and preserve previously shared revisions."""

    connection = op.get_bind()
    offline = context.is_offline_mode()
    if offline or "forked_from_revision_id" not in {
        item["name"] for item in inspect(connection).get_columns("projects")
    }:
        op.add_column("projects", sa.Column("forked_from_revision_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            "fk_projects_forked_from_revision_id_revisions",
            "projects",
            "revisions",
            ["forked_from_revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_projects_forked_from_revision_id",
            "projects",
            ["forked_from_revision_id"],
            unique=False,
        )

    created_public_games = offline or not inspect(connection).has_table("public_games")
    if created_public_games:
        op.create_table(
            "public_games",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("revision_id", sa.Uuid(), nullable=False),
            sa.Column("author_id", sa.Uuid(), nullable=False),
            sa.Column("title", sa.String(length=100), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id"),
            sa.UniqueConstraint("revision_id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_public_games_author_id", "public_games", ["author_id"], unique=False)

    if offline or not inspect(connection).has_table("public_game_likes"):
        op.create_table(
            "public_game_likes",
            sa.Column("public_game_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["public_game_id"], ["public_games.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("public_game_id", "user_id"),
        )

    if created_public_games:
        # Revision UUIDs are already unique and provide stable publication IDs.
        # Keep the data migration server-side so offline SQL includes it too.
        op.execute(
            sa.text(
                """
                INSERT INTO public_games
                    (id, project_id, revision_id, author_id, title, slug, created_at, updated_at)
                SELECT DISTINCT ON (r.project_id)
                       r.id, r.project_id, r.id, p.owner_id,
                       r.title, r.public_slug, r.created_at, r.created_at
                FROM revisions r
                JOIN projects p ON p.id = r.project_id
                WHERE r.public_slug IS NOT NULL AND p.owner_id IS NOT NULL
                ORDER BY r.project_id, r.created_at DESC, r.id DESC
                """
            )
        )


def downgrade() -> None:
    """Remove public feed state while preserving legacy revision slugs."""

    connection = op.get_bind()
    if context.is_offline_mode():
        op.drop_table("public_game_likes")
        op.drop_table("public_games")
        op.drop_index("ix_projects_forked_from_revision_id", table_name="projects")
        op.drop_constraint(
            "fk_projects_forked_from_revision_id_revisions", "projects", type_="foreignkey"
        )
        op.drop_column("projects", "forked_from_revision_id")
        return
    if inspect(connection).has_table("public_game_likes"):
        op.drop_table("public_game_likes")
    if inspect(connection).has_table("public_games"):
        op.drop_table("public_games")
    columns = {item["name"] for item in inspect(connection).get_columns("projects")}
    if "forked_from_revision_id" in columns:
        indexes = {item["name"] for item in inspect(connection).get_indexes("projects")}
        if "ix_projects_forked_from_revision_id" in indexes:
            op.drop_index("ix_projects_forked_from_revision_id", table_name="projects")
        foreign_key = next(
            (
                item["name"]
                for item in inspect(connection).get_foreign_keys("projects")
                if item["constrained_columns"] == ["forked_from_revision_id"]
            ),
            None,
        )
        if foreign_key:
            op.drop_constraint(foreign_key, "projects", type_="foreignkey")
        op.drop_column("projects", "forked_from_revision_id")
