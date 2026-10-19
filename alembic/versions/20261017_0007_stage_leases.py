"""Persist exclusive, expiring stage ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261017_0007"
down_revision: str | None = "20261017_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add leases without assuming migration one used historical metadata."""

    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("generation_runs")}
    if "lease_token" not in columns:
        op.add_column("generation_runs", sa.Column("lease_token", sa.Uuid(), nullable=True))
    if "lease_expires_at" not in columns:
        op.add_column(
            "generation_runs",
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    """Remove stage ownership metadata."""

    op.drop_column("generation_runs", "lease_expires_at")
    op.drop_column("generation_runs", "lease_token")
