"""Fence automatic revision promotion against newer creator choices."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261017_0008"
down_revision: str | None = "20261017_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill selection counters while supporting fresh metadata-based installs."""

    for table, column in (
        ("projects", "selection_version"),
        ("generation_runs", "project_version"),
    ):
        columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
        if column not in columns:
            op.add_column(
                table, sa.Column(column, sa.Integer(), nullable=False, server_default="0")
            )
            op.alter_column(table, column, server_default=None)


def downgrade() -> None:
    """Remove promotion counters."""

    op.drop_column("generation_runs", "project_version")
    op.drop_column("projects", "selection_version")
