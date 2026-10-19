"""Migration SQL contracts, without a database or mutable ORM schema inputs."""

from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from prompt2play.models import Base

ROOT = Path(__file__).resolve().parents[2]


def migration_config(output: StringIO) -> Config:
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


def test_full_offline_upgrade_includes_schema_and_publication_backfill() -> None:
    output = StringIO()
    command.upgrade(migration_config(output), "head", sql=True)
    sql = output.getvalue()
    assert sql.count("CREATE TABLE ") == 14  # Includes alembic_version.
    assert sql.count("CREATE TABLE public_games (") == 1
    assert "INSERT INTO public_games" in sql
    assert "SELECT DISTINCT ON (r.project_id)" in sql
    assert "ALTER TABLE projects ADD COLUMN selection_version" in sql
    assert "ALTER TABLE generation_runs ADD COLUMN lease_token" in sql
    assert "DROP CONSTRAINT revisions_artifact_digest_key" in sql


def test_full_offline_downgrade_does_not_repeat_removed_foreign_keys() -> None:
    output = StringIO()
    command.downgrade(migration_config(output), "head:base", sql=True)
    sql = output.getvalue()
    assert sql.count("DROP CONSTRAINT fk_projects_forked_from_revision_id_revisions") == 1
    initial = sql.split("-- Running downgrade 20261012_0001 ->", maxsplit=1)[1]
    assert "DROP CONSTRAINT" not in initial
    assert "DROP TABLE projects" in initial
    assert sql.index("DROP TABLE generation_runs") < sql.index("DROP TABLE revisions")
    assert sql.index("DROP TABLE revisions") < sql.index("DROP TABLE projects")


def test_initial_schema_is_independent_of_current_application_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = sa.MetaData()
    sa.Table("future_table", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    monkeypatch.setattr(Base, "metadata", metadata)
    output = StringIO()
    command.upgrade(migration_config(output), "20261012_0001", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE projects" in sql
    assert "CREATE TABLE revisions" in sql
    assert "UNIQUE (artifact_digest)" in sql
    for future_name in ("future_table", "owner_id", "forked_from_revision_id", "lease_token"):
        assert future_name not in sql
