"""Separate idempotency records and allow shared artifact digests."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261017_0002"
down_revision: str | None = "20261012_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply stabilization changes to both legacy and fresh version-one schemas."""

    connection = op.get_bind()
    inspector = inspect(connection)
    if not inspector.has_table("idempotency_records"):
        op.create_table(
            "idempotency_records",
            sa.Column("key", sa.String(length=200), nullable=False),
            sa.Column("operation", sa.String(length=64), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=True),
            sa.Column("run_id", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["run_id"], ["generation_runs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("key"),
        )

    inspector = inspect(connection)
    unique_constraints = {item["name"] for item in inspector.get_unique_constraints("revisions")}
    if "revisions_artifact_digest_key" in unique_constraints:
        op.drop_constraint("revisions_artifact_digest_key", "revisions", type_="unique")
    indexes = {item["name"] for item in inspect(connection).get_indexes("revisions")}
    if "ix_revisions_artifact_digest" not in indexes:
        op.create_index(
            "ix_revisions_artifact_digest",
            "revisions",
            ["artifact_digest"],
            unique=False,
        )
    revision_columns = {item["name"] for item in inspect(connection).get_columns("revisions")}
    if "spec" not in revision_columns:
        op.add_column("revisions", sa.Column("spec", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Restore the original uniqueness rule and remove idempotency reservations."""

    connection = op.get_bind()
    inspector = inspect(connection)
    revision_columns = {item["name"] for item in inspector.get_columns("revisions")}
    if "spec" in revision_columns:
        op.drop_column("revisions", "spec")
    indexes = {item["name"] for item in inspector.get_indexes("revisions")}
    if "ix_revisions_artifact_digest" in indexes:
        op.drop_index("ix_revisions_artifact_digest", table_name="revisions")
    unique_constraints = {
        item["name"] for item in inspect(connection).get_unique_constraints("revisions")
    }
    if "revisions_artifact_digest_key" not in unique_constraints:
        op.create_unique_constraint(
            "revisions_artifact_digest_key", "revisions", ["artifact_digest"]
        )
    if inspect(connection).has_table("idempotency_records"):
        op.drop_table("idempotency_records")
