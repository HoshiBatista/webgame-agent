"""Backups are verified using real SQLite and an optional fresh PostgreSQL DB."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from prompt2play.adapters.artifacts.store import ArtifactStore
from prompt2play.operations import (
    DatabaseConfig,
    backup,
    database_config,
    postgres,
    restore,
    verify,
)


def sqlite_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    database = tmp_path / "source.sqlite3"
    artifacts = tmp_path / "source-artifacts"
    store = ArtifactStore(artifacts)
    intent, key = store.prepare({"html": "pending authored fixture"})
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE forge_candidate (artifact_key TEXT, intent TEXT)")
        connection.execute("INSERT INTO forge_candidate VALUES (?,?)", (key, intent))
        connection.execute("CREATE TABLE fixture (value TEXT)")
        connection.execute("INSERT INTO fixture VALUES (?)", ("restored authored value",))
    return database, artifacts, key


def test_sqlite_backup_restore_keeps_pending_candidate_and_database(tmp_path: Path) -> None:
    database, artifacts, key = sqlite_fixture(tmp_path)
    bundle = tmp_path / "bundle"
    manifest = backup(bundle, artifacts, DatabaseConfig("sqlite", str(database)))
    assert manifest["database_engine"] == "sqlite"
    assert not any("env" in name or "password" in name for name in manifest["files"])
    target = tmp_path / "restore"
    restored = restore(bundle, target)
    assert restored["database_engine"] == "sqlite"
    with closing(sqlite3.connect(target / "db.sqlite3")) as connection:
        assert connection.execute("SELECT value FROM fixture").fetchone() == (
            "restored authored value",
        )
    assert ArtifactStore(target / "artifacts").read_json(key)["html"] == "pending authored fixture"
    assert (bundle.stat().st_mode & 0o777) == 0o700


def test_restore_rejects_corruption_symlinks_and_existing_target(tmp_path: Path) -> None:
    database, artifacts, _ = sqlite_fixture(tmp_path)
    bundle = tmp_path / "bundle"
    backup(bundle, artifacts, DatabaseConfig("sqlite", str(database)))
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("preserve")
    with pytest.raises(ValueError, match="empty"):
        restore(bundle, occupied)
    assert (occupied / "keep").read_text() == "preserve"
    added = bundle / "foreign"
    added.symlink_to(database)
    with pytest.raises(ValueError, match="symlink"):
        verify(bundle)
    added.unlink()
    snapshot = bundle / "database.sqlite3"
    snapshot.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        restore(bundle, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def test_verify_rejects_manifest_traversal_and_extra_files(tmp_path: Path) -> None:
    database, artifacts, _ = sqlite_fixture(tmp_path)
    bundle = tmp_path / "bundle"
    backup(bundle, artifacts, DatabaseConfig("sqlite", str(database)))
    manifest_file = bundle / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_file.read_text())
    manifest["files"]["../outside"] = {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}
    manifest_file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify(bundle)
    del manifest["files"]["../outside"]
    manifest_file.write_text(json.dumps(manifest))
    (bundle / "extra").write_text("not in inventory")
    with pytest.raises(ValueError, match="inventory"):
        verify(bundle)


def test_failed_backup_cleans_incomplete_bundle(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    ArtifactStore(artifacts)
    bundle = tmp_path / "bundle"
    with pytest.raises(sqlite3.Error):
        backup(bundle, artifacts, DatabaseConfig("sqlite", str(tmp_path / "absent.db")))
    assert not bundle.exists()


@pytest.mark.django_db(transaction=True)
def test_postgresql_dump_restore_fresh_database(tmp_path: Path, settings: Any) -> None:
    from django.db import connection

    if (
        connection.vendor != "postgresql"
        or not shutil.which("pg_dump")
        or not shutil.which("pg_restore")
    ):
        pytest.skip("Requires PostgreSQL release database and client utilities.")
    from prompt2play.adapters.django.forge.models import Project

    Project.objects.create(title="Actual restore fixture", prompt="Authored backup fixture")
    source = database_config()
    artifacts = tmp_path / "artifacts"
    store = ArtifactStore(artifacts)
    key = store.put_bytes(b"authored immutable bytes")
    bundle = tmp_path / "bundle"
    backup(bundle, artifacts, source)
    database_name = "p2p_restore_" + uuid.uuid4().hex[:12]
    admin = DatabaseConfig(
        "postgresql", "postgres", source.host, source.port, source.user, source.password
    )
    with postgres(admin) as admin_connection:
        admin_connection.autocommit = True
        admin_connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
    target_config = DatabaseConfig(
        "postgresql", database_name, source.host, source.port, source.user, source.password
    )
    try:
        restored = restore(bundle, tmp_path / "target", target_config)
        assert restored["database_engine"] == "postgresql"
        with postgres(target_config) as restored_connection:
            row = restored_connection.execute("SELECT title FROM forge_project").fetchone()
            assert row == ("Actual restore fixture",)
        assert (
            ArtifactStore(tmp_path / "target" / "artifacts").read(key)
            == b"authored immutable bytes"
        )
        with pytest.raises(ValueError, match="empty"):
            restore(bundle, tmp_path / "refused-target", target_config)
    finally:
        with postgres(admin) as admin_connection:
            admin_connection.autocommit = True
            admin_connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )
