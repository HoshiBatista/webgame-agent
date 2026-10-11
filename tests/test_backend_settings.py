"""Each public listener must start with its own Django application registry."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
