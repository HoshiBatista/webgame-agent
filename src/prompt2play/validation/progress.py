"""Bounded, request-bound progress from the trusted container harness."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


def read_object(path: Path, limit: int) -> dict[str, Any]:
    """Do not follow a container-written symlink or read an unbounded stream."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                return {}
            data = source.read(limit + 1)
        if len(data) > limit:
            return {}
        value = json.loads(data)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


class ProgressWatchdog:
    """Only completed operations extend the idle deadline, never status heartbeats."""

    def __init__(self, request_hash: str, now: float) -> None:
        self.request_hash = request_hash
        self.last_completed_at = now
        self.completed = 0
        self.active: dict[str, Any] = {"kind": "infrastructure", "phase": "launch"}

    def observe(self, directory: Path, now: float) -> bool:
        value = read_object(directory / "progress.json", 8192)
        count, active = value.get("completed"), value.get("active")
        if (
            value.get("version") != 1
            or value.get("request_sha256") != self.request_hash
            or type(count) is not int
            or count < self.completed
            or not isinstance(active, dict)
            or active.get("kind") not in ("game", "infrastructure")
            or not isinstance(active.get("phase"), str)
        ):
            return False
        self.active = active
        if count == self.completed:
            return False
        self.completed = count
        self.last_completed_at = now
        return True

    def stalled(self, now: float, idle_timeout: float) -> bool:
        return now - self.last_completed_at > idle_timeout

    def findings(self, directory: Path, artifact_hash: str) -> list[dict[str, Any]]:
        value = read_object(directory / "partial-results.json", 1_000_000)
        checks = value.get("checks")
        if value.get("request_sha256") != self.request_hash or not isinstance(checks, list):
            return []
        result: list[dict[str, Any]] = []
        for check in checks[:96]:
            if (
                isinstance(check, dict)
                and check.get("status") == "failed"
                and isinstance(check.get("name"), str)
                and check.get("artifact_sha256") == artifact_hash
                and len(json.dumps(check).encode()) <= 16_000
            ):
                result.append(check)
        return result
