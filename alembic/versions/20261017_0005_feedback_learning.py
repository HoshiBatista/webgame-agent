"""Add creator feedback memory and per-run application provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261017_0005"
down_revision: str | None = "20261017_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add bounded feedback storage safely for legacy and fresh schemas."""

    connection = op.get_bind()
    run_columns = {item["name"] for item in inspect(connection).get_columns("generation_runs")}
    if "feedback_snapshot" not in run_columns:
        op.add_column("generation_runs", sa.Column("feedback_snapshot", sa.JSON(), nullable=True))

    if not inspect(connection).has_table("game_feedback"):
        op.create_table(
            "game_feedback",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("revision_id", sa.Uuid(), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("reasons", sa.JSON(), nullable=False),
            sa.Column("comment", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_game_feedback_rating"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "revision_id", name="uq_game_feedback_user_revision"),
        )
        op.create_index("ix_game_feedback_project_id", "game_feedback", ["project_id"])
        op.create_index("ix_game_feedback_revision_id", "game_feedback", ["revision_id"])
        op.create_index("ix_game_feedback_user_id", "game_feedback", ["user_id"])


def downgrade() -> None:
    """Remove feedback memory and its run snapshots."""

    connection = op.get_bind()
    if inspect(connection).has_table("game_feedback"):
        op.drop_table("game_feedback")
    run_columns = {item["name"] for item in inspect(connection).get_columns("generation_runs")}
    if "feedback_snapshot" in run_columns:
        op.drop_column("generation_runs", "feedback_snapshot")
