"""Each public listener must start with its own Django application registry."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest


@pytest.mark.django_db
def test_new_jobs_pin_the_adaptive_default_and_explicit_legacy_remains_available(
    monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    from prompt2play.adapters.django.forge import services
    from prompt2play.adapters.django.forge.models import Project, User

    monkeypatch.delenv("PROMPT2PLAY_PIPELINE_VERSION", raising=False)
    configured = runpy.run_path(str(Path(settings.BASE_DIR) / "config/settings.py"))
    settings.FORGE_PIPELINE_VERSION = configured["FORGE_PIPELINE_VERSION"]
    user = User.objects.create_user("pipeline-fixture")
    for explicit in (None, "legacy-v1"):
        project = Project.objects.create(title="Fixture", prompt="Fixture", created_by=user)
        values = {"kind": "generate", "prompt": "Fixture", "provider": "codex", "model": ""}
        if explicit:
            values["pipeline_version"] = explicit
        job = cast(Any, services.create_job)(project, user, values)
        assert job.checkpoint["pipeline_version"] == (explicit or "adaptive-v1")
        assert job.checkpoint["project_format"] == (
            "runtime-v1" if explicit else "runtime-modules-v2"
        )


def test_preview_listener_passes_system_checks_without_session_middleware(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment["PROMPT2PLAY_DATA_DIR"] = str(tmp_path / "data")
    environment["DJANGO_DEBUG"] = "1"
    environment["PROMPT2PLAY_APP_ORIGIN"] = "http://127.0.0.1:8000"
    environment["PROMPT2PLAY_PREVIEW_ORIGIN"] = "http://127.0.0.1:8001"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "django",
            "check",
            "--settings=prompt2play.adapters.django.config.preview_settings",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no issues" in result.stdout
