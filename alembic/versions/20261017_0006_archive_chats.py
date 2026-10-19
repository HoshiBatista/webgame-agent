"""Archive creator chats without deleting published artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261017_0006"
down_revision: str | None = "20261017_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep publication references and fill the legacy archive flag."""

    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("projects")}
    if "archived" not in columns:
        op.add_column(
            "projects",
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("projects", "archived", server_default=None)


def downgrade() -> None:
    """Restore archived chats to the legacy visible history."""

    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("projects")}
    if "archived" in columns:
        op.drop_column("projects", "archived")
