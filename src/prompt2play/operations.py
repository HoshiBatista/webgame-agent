"""Consistent, verified backups and restoration to a new empty destination.

Backups contain application data and credential hashes, never environment files
or plaintext provider/runner credentials. Protect the bundle as private data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

import psycopg

from prompt2play.adapters.artifacts.store import JSON, ArtifactStore, canonical

FORMAT = "prompt2play-backup-v1"
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_INTENT = re.compile(r"[a-f0-9]{32}\Z")


@dataclass(frozen=True)
class DatabaseConfig:
    engine: Literal["sqlite", "postgresql"]
    name: str
    host: str = ""
    port: str = "5432"
    user: str = ""
    password: str = ""


def database_config() -> DatabaseConfig:
    from django.conf import settings

    database = settings.DATABASES["default"]
    if database["ENGINE"] == "django.db.backends.sqlite3":
        return DatabaseConfig("sqlite", str(database["NAME"]))
    if database["ENGINE"] != "django.db.backends.postgresql":
        raise ValueError("Only SQLite and PostgreSQL backups are supported.")
    return DatabaseConfig(
        "postgresql",
        str(database["NAME"]),
        str(database.get("HOST", "")),
        str(database.get("PORT") or "5432"),
        str(database.get("USER", "")),
        str(database.get("PASSWORD", "")),
    )


def private_directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and any(path.iterdir())):
        raise ValueError("Destination must be a new empty directory.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def read_bytes(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def pg_environment(config: DatabaseConfig) -> dict[str, str]:
    environment = {
        name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL") if name in os.environ
    }
    environment["PGCONNECT_TIMEOUT"] = "10"
    if config.password:
        environment["PGPASSWORD"] = config.password
    return environment


def pg_arguments(config: DatabaseConfig) -> list[str]:
    return [
        "--host",
        config.host or "localhost",
        "--port",
        config.port,
        "--username",
        config.user,
        "--dbname",
        config.name,
    ]


def postgres(config: DatabaseConfig) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(
        host=config.host or "localhost",
        port=config.port,
        dbname=config.name,
        user=config.user,
        password=config.password,
        connect_timeout=10,
    )


def sqlite_references(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    result: list[tuple[str, str]] = []
    if "forge_candidate" in tables:
        result.extend(
            (str(row[0]), str(row[1]))
            for row in connection.execute("SELECT artifact_key, intent FROM forge_candidate")
        )
    if "forge_modelinvocation" in tables:
        result.extend(
            (str(row[0]), "")
            for row in connection.execute(
                "SELECT response_key FROM forge_modelinvocation WHERE response_key <> ''"
            )
        )
    if "forge_validationresult" in tables:
        for (raw,) in connection.execute("SELECT report FROM forge_validationresult"):
            report = json.loads(raw)
            result.extend(
                (entry["object_key"], "")
                for entry in report.get("evidence_files", [])
                if entry.get("object_key")
            )
    return result


def backup(destination: Path, artifacts: Path, config: DatabaseConfig) -> dict[str, Any]:
    private_directory(destination)
    try:
        references: list[tuple[str, str]]
        if config.engine == "sqlite":
            database = destination / "database.sqlite3"
            with (
                closing(
                    sqlite3.connect(Path(config.name).resolve().as_uri() + "?mode=ro", uri=True)
                ) as source,
                closing(sqlite3.connect(database)) as target,
            ):
                source.backup(target)
                references = sqlite_references(target)
            database.chmod(0o600)
        else:
            database = destination / "database.dump"
            with postgres(config) as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                row = connection.execute("SELECT pg_export_snapshot()").fetchone()
                if row is None:
                    raise ValueError("PostgreSQL snapshot unavailable.")
                snapshot = str(row[0])
                subprocess.run(
                    [
                        "pg_dump",
                        "--format=custom",
                        "--no-owner",
                        "--no-privileges",
                        "--snapshot",
                        snapshot,
                        "--file",
                        str(database),
                        *pg_arguments(config),
                    ],
                    env=pg_environment(config),
                    check=True,
                    timeout=300,
                    capture_output=True,
                )
                database.chmod(0o600)
                references = [
                    (str(row[0]), str(row[1]))
                    for row in connection.execute(
                        "SELECT artifact_key, intent FROM forge_candidate"
                    )
                ]
                references.extend(
                    (str(row[0]), "")
                    for row in connection.execute(
                        "SELECT response_key FROM forge_modelinvocation WHERE response_key <> ''"
                    )
                )
                for (report,) in connection.execute("SELECT report FROM forge_validationresult"):
                    references.extend(
                        (str(entry["object_key"]), "")
                        for entry in report.get("evidence_files", [])
                        if entry.get("object_key")
                    )
        source_store = ArtifactStore(artifacts)
        target_store = ArtifactStore(destination / "artifacts")
        for path in sorted(source_store.objects.iterdir()):
            if path.name.startswith("."):
                continue
            data = source_store.read(path.name)
            target_store.put_bytes(data)
        for path in sorted(source_store.pending.iterdir()):
            if path.name.startswith("."):
                continue
            if not _INTENT.fullmatch(path.name):
                raise ValueError("Invalid pending artifact inventory.")
            try:
                write_bytes(target_store.pending / path.name, read_bytes(path))
            except FileNotFoundError:
                # A concurrent finalization may remove its pending draft.
                continue
        for key, intent in references:
            if (target_store.objects / key).is_file():
                target_store.read(key)
                continue
            try:
                data = source_store.read(key)
            except FileNotFoundError:
                if not intent:
                    raise
                try:
                    data = read_bytes(source_store.pending / intent)
                except FileNotFoundError:
                    data = source_store.read(key)
            if hashlib.sha256(data).hexdigest() != key:
                raise ValueError("Database references unavailable or corrupted bytes.")
            target_store.put_bytes(data)
        files = {}
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                data = read_bytes(path)
                files[path.relative_to(destination).as_posix()] = {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
        manifest = {"format": FORMAT, "database_engine": config.engine, "files": files}
        write_bytes(destination / "manifest.json", canonical(cast(JSON, manifest)))
        return manifest
    except BaseException:
        # Failed backups are never reported as complete.
        shutil.rmtree(destination)
        raise


def verify(bundle: Path) -> dict[str, Any]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("Backup bundle must be a real directory.")
    raw_manifest = json.loads(read_bytes(bundle / "manifest.json"))
    if not isinstance(raw_manifest, dict):
        raise ValueError("Backup manifest must be an object.")
    manifest: dict[str, Any] = raw_manifest
    if manifest.get("format") != FORMAT or manifest.get("database_engine") not in (
        "sqlite",
        "postgresql",
    ):
        raise ValueError("Unsupported backup manifest.")
    inventory = manifest.get("files")
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("Backup inventory is missing.")
    expected_database = (
        "database.sqlite3" if manifest["database_engine"] == "sqlite" else "database.dump"
    )
    if expected_database not in inventory:
        raise ValueError("Database snapshot is missing.")
    actual = set()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise ValueError("Backup must not contain symlinks.")
        if path.is_file() and path.relative_to(bundle).as_posix() != "manifest.json":
            actual.add(path.relative_to(bundle).as_posix())
    if actual != set(inventory):
        raise ValueError("Backup file inventory differs from its manifest.")
    for name, record in inventory.items():
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != name
            or "\\" in name
        ):
            raise ValueError("Unsafe backup path.")
        permitted = name == expected_database or (
            len(relative.parts) == 3
            and relative.parts[0] == "artifacts"
            and (
                (relative.parts[1] == "objects" and bool(_HEX.fullmatch(relative.parts[2])))
                or (relative.parts[1] == "pending" and bool(_INTENT.fullmatch(relative.parts[2])))
            )
        )
        if not permitted or not isinstance(record, dict):
            raise ValueError("Unexpected backup file.")
        data = read_bytes(bundle / name)
        key = hashlib.sha256(data).hexdigest()
        if key != record.get("sha256") or len(data) != record.get("bytes"):
            raise ValueError("Backup checksum mismatch.")
        if (
            relative.parts[0] == "artifacts"
            and relative.parts[1] == "objects"
            and key != relative.parts[2]
        ):
            raise ValueError("Artifact identity mismatch.")
    return manifest


def restore(
    bundle: Path, destination: Path, config: DatabaseConfig | None = None
) -> dict[str, Any]:
    manifest = verify(bundle)
    private_directory(destination)
    try:
        # Copy verified bytes into a private controlled destination before any
        # database action, so changing the supplied bundle cannot change restore.
        for name, record in manifest["files"].items():
            data = read_bytes(bundle / name)
            if hashlib.sha256(data).hexdigest() != record["sha256"] or len(data) != record["bytes"]:
                raise ValueError("Backup changed during restoration.")
            target = destination / ("db.sqlite3" if name == "database.sqlite3" else name)
            write_bytes(target, data)
        if manifest["database_engine"] == "postgresql":
            if config is None or config.engine != "postgresql":
                raise ValueError(
                    "PostgreSQL restore needs explicit configuration of a new empty database."
                )
            with postgres(config) as connection:
                if connection.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
                ).fetchone() != (0,):
                    raise ValueError("PostgreSQL restore target must be empty.")
            subprocess.run(
                [
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "--single-transaction",
                    *pg_arguments(config),
                    str(destination / "database.dump"),
                ],
                env=pg_environment(config),
                check=True,
                timeout=300,
                capture_output=True,
            )
            (destination / "database.dump").unlink()
        return {
            "database_engine": manifest["database_engine"],
            "data_dir": str(destination.resolve()),
            "files": len(manifest["files"]),
            "recovery": "Run prompt2play manage recover before starting workers.",
        }
    except BaseException:
        shutil.rmtree(destination)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prompt2play operations")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("backup")
    create.add_argument("destination", type=Path)
    create.add_argument("--artifact-root", type=Path)
    recover = commands.add_parser("restore")
    recover.add_argument("bundle", type=Path)
    recover.add_argument("--data-dir", required=True, type=Path)
    recover.add_argument(
        "--postgresql",
        action="store_true",
        help="Use explicitly configured fresh PostgreSQL database.",
    )
    arguments = parser.parse_args(argv)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "prompt2play.adapters.django.config.settings")
    try:
        if arguments.command == "backup":
            from django.conf import settings

            artifacts = arguments.artifact_root or Path(str(settings.ARTIFACT_ROOT))
            result = backup(arguments.destination, artifacts, database_config())
        else:
            config = database_config() if arguments.postgresql else None
            result = restore(arguments.bundle, arguments.data_dir, config)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, sqlite3.Error, psycopg.Error, subprocess.SubprocessError) as exc:
        # Driver exception text can include credentials or server details.
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1
