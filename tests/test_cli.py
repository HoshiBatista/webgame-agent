"""Configuration and setup keep passwords out of shell and process arguments."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from prompt2play import cli


def test_local_configuration_is_data_with_environment_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("# comment\nMODEL=local\nLITERAL=$(touch /tmp/never-run)\n")
    monkeypatch.setenv("PROMPT2PLAY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL", "process")
    result = cli.configured_environment()
    assert result["MODEL"] == "process"
    assert result["LITERAL"] == "$(touch /tmp/never-run)"
    assert result["DJANGO_SETTINGS_MODULE"] == cli.SETTINGS


def test_invalid_config_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPT2PLAY_DATA_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("bad-name=value\n")
    with pytest.raises(ValueError, match="NAME=value"):
        cli.configured_environment()


def test_setup_passes_password_only_in_child_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMPT2PLAY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", "authored-password-fixture")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(args: list[str], env: dict[str, str]) -> int:
        calls.append((args, env.copy()))
        return 0

    monkeypatch.setattr(cli, "django_command", run)
    assert (
        cli.setup(
            argparse.Namespace(password_env="TEST_ADMIN_PASSWORD", noinput=True, username="admin")
        )
        == 0
    )
    assert calls[0][0] == ["migrate", "--noinput"]
    assert calls[1][1]["PROMPT2PLAY_SETUP_PASSWORD"] == "authored-password-fixture"
    assert all("authored-password-fixture" not in args for args, _ in calls)
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    assert "DJANGO_SECRET_KEY=" in (tmp_path / ".env").read_text()


@pytest.mark.parametrize("blank_key", [False, True])
def test_setup_adds_signing_key_to_existing_database_config_and_preserves_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blank_key: bool
) -> None:
    monkeypatch.setenv("PROMPT2PLAY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", "authored-password-fixture")
    config = tmp_path / ".env"
    original = "# authored existing config\nDB_HOST=fixture-database\nDB_PORT=55432"
    if blank_key:
        original += "\nDJANGO_SECRET_KEY="
    config.write_text(original)
    calls: list[dict[str, str]] = []

    def run(_args: list[str], env: dict[str, str]) -> int:
        calls.append(env.copy())
        return 0

    monkeypatch.setattr(cli, "django_command", run)
    arguments = argparse.Namespace(
        password_env="TEST_ADMIN_PASSWORD", noinput=True, username="admin"
    )
    assert cli.setup(arguments) == 0
    key = cli.configured_environment()["DJANGO_SECRET_KEY"]
    assert len(key) >= 48
    assert calls[0]["DJANGO_SECRET_KEY"] == key
    assert calls[0]["DB_HOST"] == "fixture-database"
    assert config.read_text().startswith(original + "\n")
    assert config.stat().st_mode & 0o777 == 0o600
    saved = config.read_bytes()
    assert cli.setup(arguments) == 0
    assert config.read_bytes() == saved
    assert calls[2]["DJANGO_SECRET_KEY"] == key


def test_setup_keeps_key_in_discovered_config_when_data_directory_is_redirected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROMPT2PLAY_DATA_DIR", raising=False)
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", "authored-password-fixture")
    discovery = tmp_path / ".prompt2play"
    discovery.mkdir()
    actual_data = tmp_path / "actual-data"
    config = discovery / ".env"
    config.write_text(f"PROMPT2PLAY_DATA_DIR={actual_data}\nDB_HOST=fixture-database\n")
    calls: list[dict[str, str]] = []

    def run(_args: list[str], env: dict[str, str]) -> int:
        calls.append(env.copy())
        return 0

    monkeypatch.setattr(cli, "django_command", run)
    assert (
        cli.setup(
            argparse.Namespace(password_env="TEST_ADMIN_PASSWORD", noinput=True, username="admin")
        )
        == 0
    )
    assert actual_data.is_dir()
    assert not (actual_data / ".env").exists()
    assert calls[0]["PROMPT2PLAY_DATA_DIR"] == str(actual_data)
    assert calls[0]["DJANGO_SECRET_KEY"] == cli.configured_environment()["DJANGO_SECRET_KEY"]
    assert config.stat().st_mode & 0o777 == 0o600


def test_setup_preserves_process_signing_key_precedence_and_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMPT2PLAY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DJANGO_SECRET_KEY", "authored-process-signing-key-fixture")
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", "authored-password-fixture")
    config = tmp_path / ".env"
    original = "DB_HOST=fixture-database\nDJANGO_SECRET_KEY=authored-file-signing-key-fixture\n"
    config.write_text(original)
    calls: list[dict[str, str]] = []

    def run(_args: list[str], env: dict[str, str]) -> int:
        calls.append(env.copy())
        return 0

    monkeypatch.setattr(cli, "django_command", run)
    assert (
        cli.setup(
            argparse.Namespace(password_env="TEST_ADMIN_PASSWORD", noinput=True, username="admin")
        )
        == 0
    )
    assert all(
        environment["DJANGO_SECRET_KEY"] == "authored-process-signing-key-fixture"
        for environment in calls
    )
    assert config.read_text() == original
    assert config.stat().st_mode & 0o777 == 0o600


def test_setup_rejects_explicit_empty_process_signing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMPT2PLAY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DJANGO_SECRET_KEY", "")
    with pytest.raises(ValueError, match="empty"):
        cli.setup(argparse.Namespace(password_env="", noinput=True, username="admin"))
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize(
    ("command", "module_name", "arguments"),
    [
        ("worker", "prompt2play.workers.runner", ["--role", "generator", "--once"]),
        (
            "evaluate",
            "prompt2play.evaluation",
            ["--model", "fixture-model", "--output", "fixture-output"],
        ),
        ("backup", "prompt2play.operations", ["fixture-bundle"]),
        (
            "restore",
            "prompt2play.operations",
            ["fixture-bundle", "--data-dir", "fixture-target"],
        ),
    ],
)
def test_in_process_commands_apply_and_restore_local_database_and_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    module_name: str,
    arguments: list[str],
) -> None:
    monkeypatch.setenv("PROMPT2PLAY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DB_PORT", "7788")
    configured_keys = ["DB_HOST", "DJANGO_DB_PATH", "PROMPT2PLAY_RUNNER_TOKEN", "OPENAI_API_KEY"]
    for name in configured_keys:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "DB_HOST=fixture-host\n"
        "DB_PORT=6666\n"
        "DJANGO_DB_PATH=fixture.sqlite3\n"
        "PROMPT2PLAY_RUNNER_TOKEN=runner-fixture\n"
        "OPENAI_API_KEY=provider-fixture\n"
    )
    expected = {
        "DB_HOST": "fixture-host",
        "DB_PORT": "7788",
        "DJANGO_DB_PATH": "fixture.sqlite3",
        "PROMPT2PLAY_RUNNER_TOKEN": "runner-fixture",
        "OPENAI_API_KEY": "provider-fixture",
    }
    received: list[list[str]] = []

    def run(argv: list[str]) -> int:
        received.append(argv)
        assert {name: os.environ[name] for name in expected} == expected
        return 23

    module = ModuleType(module_name)
    module.__dict__["main"] = run
    monkeypatch.setitem(sys.modules, module_name, module)
    assert cli.main([command, *arguments]) == 23
    assert received == [[command, *arguments] if command in {"backup", "restore"} else arguments]
    assert all(name not in os.environ for name in configured_keys)
    assert os.environ["DB_PORT"] == "7788"


def test_local_environment_restores_after_failed_and_repeated_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROMPT2PLAY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PROMPT2PLAY_RUNNER_TOKEN", raising=False)
    (tmp_path / ".env").write_text("PROMPT2PLAY_RUNNER_TOKEN=first-fixture\n")
    calls: list[str] = []

    def run(_argv: list[str]) -> int:
        calls.append(os.environ["PROMPT2PLAY_RUNNER_TOKEN"])
        raise ValueError("Authored failure fixture")

    module = ModuleType("prompt2play.workers.runner")
    module.__dict__["main"] = run
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert cli.main(["worker", "--role", "generator"]) == 1
    assert "PROMPT2PLAY_RUNNER_TOKEN" not in os.environ
    (tmp_path / ".env").write_text("PROMPT2PLAY_RUNNER_TOKEN=second-fixture\n")
    assert cli.main(["worker", "--role", "generator"]) == 1
    assert calls == ["first-fixture", "second-fixture"]
    assert "PROMPT2PLAY_RUNNER_TOKEN" not in os.environ
