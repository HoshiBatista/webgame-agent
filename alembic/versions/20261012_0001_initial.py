"""Create the Prompt2Play durable workflow schema."""

from collections.abc import Sequence

from alembic import op

from prompt2play.models import Base

revision: str = "20261012_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all version-one tables from the pinned metadata."""

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop the version-one schema."""

    Base.metadata.drop_all(bind=op.get_bind())
