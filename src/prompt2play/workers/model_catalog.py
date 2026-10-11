"""Read the connected Codex catalog without starting a thread or inference turn."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from typing import Any

from prompt2play.workers.diagnostics import emit

MAX_MODELS = 64


class CatalogUnavailable(RuntimeError):
    """A bounded, non-sensitive discovery failure code."""


async def _catalog(executable: str) -> list[dict[str, Any]]:
    process = await asyncio.create_subprocess_exec(
        executable,
        "app-server",
        "--listen",
        "stdio://",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=256 * 1024,
    )
    assert process.stdin is not None and process.stdout is not None
    stdin, stdout = process.stdin, process.stdout

    async def send(message: dict[str, Any]) -> None:
        stdin.write((json.dumps(message) + "\n").encode())
        await stdin.drain()

    async def call(method: str, request_id: int, params: dict[str, Any]) -> dict[str, Any]:
        await send({"id": request_id, "method": method, "params": params})
        for _ in range(128):
            line = await stdout.readline()
            if not line:
                raise CatalogUnavailable("closed")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise CatalogUnavailable("invalid_response")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                # Raw RPC errors can contain configuration paths or credentials.
                raise CatalogUnavailable("rpc_error")
            result = message.get("result")
            if not isinstance(result, dict):
                raise CatalogUnavailable("invalid_response")
            return result
        raise CatalogUnavailable("notification_limit")

    try:
        await call(
            "initialize",
            1,
            {"clientInfo": {"name": "prompt2play", "title": "Prompt2Play", "version": "0.1.0"}},
        )
        await send({"method": "initialized", "params": {}})
        models: dict[str, dict[str, Any]] = {}
        cursor = None
        seen_cursors: set[str] = set()
        for page in range(4):
            response = await call(
                "model/list", page + 2, {"limit": 20, "includeHidden": False, "cursor": cursor}
            )
            rows = response.get("data")
            if not isinstance(rows, list) or len(rows) > MAX_MODELS:
                raise CatalogUnavailable("invalid_response")
            for row in rows:
                if not isinstance(row, dict):
                    raise CatalogUnavailable("invalid_model")
                if row.get("hidden") is True:
                    continue
                name, label = row.get("model"), row.get("displayName")
                if (
                    not isinstance(name, str)
                    or not 1 <= len(name) <= 120
                    or not isinstance(label, str)
                    or not 1 <= len(label) <= 120
                    or any(ord(char) < 32 for char in name + label)
                ):
                    raise CatalogUnavailable("invalid_model")
                models[name] = {
                    "id": name,
                    "label": label,
                    "is_default": row.get("isDefault") is True,
                }
                if len(models) > MAX_MODELS:
                    raise CatalogUnavailable("model_limit")
            cursor = response.get("nextCursor")
            if cursor is None:
                return list(models.values())
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise CatalogUnavailable("invalid_cursor")
            seen_cursors.add(cursor)
        raise CatalogUnavailable("page_limit")
    finally:
        # Also reap on timeouts, malformed responses and worker cancellation.
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 1)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()


def discover_codex_models(executable: str, timeout: float = 12) -> list[dict[str, Any]]:
    """Use the same executable, user configuration and login as generation."""

    async def bounded() -> list[dict[str, Any]]:
        return await asyncio.wait_for(_catalog(executable), timeout)

    try:
        return asyncio.run(bounded())
    except TimeoutError:
        raise CatalogUnavailable("timeout") from None
    except (OSError, ValueError):
        raise CatalogUnavailable("transport_error") from None


class CodexModelCatalog:
    """Refresh only between stages; do not extend an active generation lease."""

    def __init__(self, executable: str) -> None:
        self.executable = executable
        self.next_refresh = 0.0
        self.value: dict[str, Any] = {}

    def capabilities(self) -> dict[str, Any]:
        if time.monotonic() < self.next_refresh:
            return self.value
        try:
            models = discover_codex_models(self.executable)
            self.value = {"codex_models": models, "model_catalog_status": "ready"}
            retry = 300
            emit("model_catalog_refreshed", provider="codex", count=len(models))
        except CatalogUnavailable as exc:
            # Clear stale choices instead of presenting an old account's catalog.
            self.value = {"codex_models": [], "model_catalog_status": "unavailable"}
            retry = 60
            emit("model_catalog_unavailable", provider="codex", reason=str(exc))
        self.value["model_catalog_checked_at"] = datetime.now(UTC).isoformat()
        self.next_refresh = time.monotonic() + retry
        return self.value
