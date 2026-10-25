"""One ephemeral app-server turn using the operator's existing Codex login.

No environment is attached to the thread or turn. This is an enforced protocol
capability boundary, not an instruction asking an otherwise privileged agent to
behave. The subprocess inherits no application/database/provider secrets.
"""

import json
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from ..errors import GenerationError
from ..prompts import build_messages
from ..schema import response_schema

MAX_CONTEXT_BYTES = 256000
CONTEXT_WINDOW = 872000
AUTO_COMPACT_TOKEN_LIMIT = 800000
VERIFIED_CLI_VERSIONS = {
    "codex-cli 0.163.0-alpha.10.2", "codex-cli 0.163.0-alpha.11.2",
    "codex-cli 0.164.0-alpha.11.1",
}

DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "code_mode",
    "code_mode_host",
    "apps",
    "plugins",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "in_app_browser",
    "view_image",
    "image_generation",
    "multi_agent",
    "multi_agent_v2",
    "memories",
    "hooks",
    "goals",
    "workspace_dependencies",
    "unbounded_connection_retries",
    "shell_snapshot",
    "sleep_tool",
    "current_time_reminder",
    "request_permissions_tool",
    "send_message_to_user_async",
    "deferred_executor",
    "token_budget",
    "context_management",
    "tool_suggest",
    "skill_search",
    "code_mode_only",
    "async_compaction",
)


def codex_home():
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def available_models():
    """Actual authenticated catalog cache; never invent a fallback model list."""
    try:
        # A cloud web process sees only a non-secret catalog, never the worker's
        # credential directory. Generation still uses its own full local cache.
        path = Path(os.environ.get("GAMEFORGE_CODEX_CATALOG", codex_home() / "models_cache.json"))
        catalog = json.loads(path.read_text())
        result = []
        for model in catalog.get("models", []):
            if model.get("visibility") == "hide" or not model.get("slug"):
                continue
            result.append(
                {
                    "id": model["slug"],
                    "name": model.get("display_name", model["slug"]),
                    "reasoning_efforts": model.get("supported_reasoning_levels", []),
                    "default_reasoning_effort": model.get("default_reasoning_level"),
                }
            )
        return result
    except (OSError, ValueError, TypeError):
        return []


def binary():
    configured = os.environ.get("GAMEFORGE_CODEX_BINARY")
    path = configured or shutil.which("codex")
    if not path:
        raise GenerationError(
            "codex_unavailable", "Codex CLI не найден. Администратору нужно настроить подключение Codex."
        )
    return path


def child_environment():
    allowed = {
        "HOME",
        "PATH",
        "TMPDIR",
        "USER",
        "LOGNAME",
        "SHELL",
        "CODEX_HOME",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def sanitized_catalog(destination):
    try:
        models = json.loads((codex_home() / "models_cache.json").read_text())["models"]
    except (OSError, ValueError, KeyError) as exc:
        raise GenerationError(
            "model_catalog_unavailable", "Каталог Codex недоступен; безопасный запуск отменён."
        ) from exc
    for model in models:
        model.update(
            shell_type="disabled",
            apply_patch_tool_type=None,
            experimental_supported_tools=[],
            tool_mode="direct",
            supports_search_tool=False,
            node_repl_disabled=True,
            include_skills_usage_instructions=False,
            include_plugin_usage_instructions=False,
            include_apps_usage_instructions=False,
        )
    path = Path(destination) / "models.json"
    path.write_text(json.dumps({"models": models}), encoding="utf-8")
    return path


def verify_cli_contract():
    try:
        version = subprocess.run(
            [binary(), "--version"], capture_output=True, text=True, timeout=5, env=child_environment()
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GenerationError("codex_unavailable", "Не удалось проверить версию Codex.") from exc
    if version not in VERIFIED_CLI_VERSIONS:
        raise GenerationError(
            "codex_profile_unverified",
            "Для этой версии Codex ещё не проверен профиль без инструментов. Нужна проверка адаптера; платный запрос не отправлен.",
        )
    return version


def command(catalog_path):
    args = [binary(), "app-server", "--stdio"]
    for feature in DISABLED_FEATURES:
        args.extend(["-c", f"features.{feature}=false"])
    settings = {
        "model_catalog_json": str(catalog_path),
        "developer_instructions": "",
        "model_context_window": CONTEXT_WINDOW,
        "model_auto_compact_token_limit": AUTO_COMPACT_TOKEN_LIMIT,
        "model_auto_compact_token_limit_scope": "total",
        "model_post_turn_compact_threshold_percent": 0,
        "tools.update_plan.enabled": False,
        "tools.experimental_request_user_input.enabled": False,
        "web_search": "disabled",
        "approval_policy": "never",
        "sandbox_mode": "read-only",
        "project_doc_max_bytes": 0,
        "features.skip_host_skill_discovery": True,
        "agents.enabled": False,
        "plugins._default.enabled": False,
        "apps._default.enabled": False,
        "model_providers.gameforge_codex.name": "GameForge Codex login",
        "model_providers.gameforge_codex.wire_api": "responses",
        "model_providers.gameforge_codex.requires_openai_auth": True,
        "model_providers.gameforge_codex.request_max_retries": 0,
        "model_providers.gameforge_codex.stream_max_retries": 0,
        "model_providers.gameforge_codex.stream_idle_timeout_ms": 60000,
        "include_apps_instructions": False,
        "include_environment_context": False,
        "include_collaboration_mode_instructions": False,
        "analytics.enabled": False,
        "otel.log_user_prompt": False,
        "otel.log_agent_responses": False,
    }
    for key, value in settings.items():
        args.extend(["-c", f"{key}={json.dumps(value)}"])
    return args


class Connection:
    def __init__(self, cwd):
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.next_id = 0
        self.pending = []
        self.process = subprocess.Popen(
            command(sanitized_catalog(cwd)),
            cwd=cwd,
            env=child_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

        assert self.process.stdin is not None and self.process.stdout is not None
        self.input = self.process.stdin
        self.output = self.process.stdout

        def receive():
            try:
                for line in self.output:
                    try:
                        self.events.put(json.loads(line))
                    except ValueError:
                        self.events.put({"transport_error": "invalid_json_line"})
            finally:
                self.events.put({"transport_error": "eof"})

        threading.Thread(target=receive, daemon=True, name="gameforge-codex-events").start()

    def send(self, method, params, *, notification=False):
        self.next_id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            payload["id"] = self.next_id
        try:
            self.input.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.input.flush()
        except (BrokenPipeError, OSError) as exc:
            raise GenerationError(
                "codex_disconnected", "Codex завершил соединение.", outcome_unknown=True
            ) from exc
        return self.next_id

    def next(self, is_cancelled, *, deadline=None):
        while True:
            if is_cancelled():
                raise GenerationError("cancelled", "Запуск остановлен пользователем.", outcome_unknown=True)
            if deadline and time.monotonic() > deadline:
                raise GenerationError("codex_startup_failed", "Codex не ответил при подготовке соединения.")
            try:
                event = self.events.get(timeout=0.1)
            except queue.Empty:
                continue
            if "transport_error" in event:
                raise GenerationError(
                    "codex_disconnected",
                    "Соединение с Codex оборвалось; повтор автоматически не отправляется.",
                    outcome_unknown=True,
                )
            # No server tool request may be approved by this adapter.
            if event.get("method") and "id" in event:
                self.input.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": event["id"],
                            "error": {
                                "code": -32601,
                                "message": "Tools are unavailable in mini-game generation",
                            },
                        }
                    )
                    + "\n"
                )
                self.input.flush()
                raise GenerationError(
                    "unexpected_tool",
                    "Codex попытался вызвать недоступный инструмент; вызов отклонён.",
                    outcome_unknown=True,
                )
            return event

    def rpc(self, method, params, is_cancelled):
        request_id = self.send(method, params)
        deadline = time.monotonic() + 30
        while True:
            event = self.next(is_cancelled, deadline=deadline)
            if event.get("id") == request_id:
                if "error" in event:
                    raise GenerationError(
                        "codex_configuration_error",
                        "Codex отклонил безопасную конфигурацию: "
                        + str(event["error"].get("message", ""))[:500],
                    )
                return event.get("result", {})
            self.pending.append(event)

    def close(self):
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if self.process.poll() is None:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=2)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()


def _usage(params):
    usage = (params.get("tokenUsage") or {}).get("total") or {}
    incoming, cached, outgoing = (
        usage.get("inputTokens"),
        usage.get("cachedInputTokens", 0),
        usage.get("outputTokens"),
    )
    if all(isinstance(v, int) and v >= 0 for v in (incoming, cached, outgoing)) and cached <= incoming:
        return {
            "input_tokens": incoming,
            "cached_input_tokens": cached,
            "output_tokens": outgoing,
            "cache_write_input_tokens": usage.get("cacheWriteInputTokens", 0),
        }
    return None


def generate(request, *, on_event, is_cancelled):
    if is_cancelled():
        raise GenerationError("cancelled", "Запуск отменён до отправки.")
    model = request.get("model") or os.environ.get("GAMEFORGE_CODEX_MODEL", "gpt-6-luna")
    models = available_models()
    if not models or model not in {m["id"] for m in models}:
        raise GenerationError(
            "model_unavailable",
            "Модель отсутствует в доступном каталоге Codex. Обновите вход/каталог в Codex.",
        )
    verify_cli_contract()
    messages = build_messages(request)
    schema = response_schema(request)
    context_bytes = sum(
        len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        for value in (messages, schema)
    )
    if context_bytes > MAX_CONTEXT_BYTES:
        raise GenerationError(
            "context_limit",
            "Текущий контекст превышает формат мини-игры (256 000 UTF-8 байт вместе со схемой). Запрос не отправлен; исходники сохранены без обрезания.",
        )
    usage, text, started, thread_id, turn_id = None, "", False, None, None
    with tempfile.TemporaryDirectory(prefix="gameforge-model-") as cwd:
        try:
            connection = Connection(cwd)
        except OSError as exc:
            raise GenerationError("codex_unavailable", "Не удалось запустить локальный Codex CLI.") from exc
        try:
            connection.rpc(
                "initialize",
                {
                    "clientInfo": {"name": "gameforge_minigames", "version": "1.0.0"},
                    "capabilities": {"experimentalApi": True},
                },
                is_cancelled,
            )
            connection.send("initialized", {}, notification=True)
            effective = connection.rpc("config/read", {"includeLayers": False}, is_cancelled).get(
                "config", {}
            )
            # Map merging must disable every effective MCP entry explicitly.
            overrides = {
                "mcp_servers": {name: {"enabled": False} for name in effective.get("mcp_servers", {})}
            }
            result = connection.rpc(
                "thread/start",
                {
                    "ephemeral": True,
                    "cwd": cwd,
                    "model": model,
                    "modelProvider": "gameforge_codex",
                    "allowProviderModelFallback": False,
                    "environments": [],
                    "runtimeWorkspaceRoots": [],
                    "dynamicTools": [],
                    "selectedCapabilityRoots": [],
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "baseInstructions": messages[0]["content"],
                    "developerInstructions": "",
                    "config": overrides,
                },
                is_cancelled,
            )
            thread_id = result["thread"]["id"]
            if result.get("model") != model:
                raise GenerationError("model_mismatch", "Codex выбрал другую модель; запрос не отправлен.")
            # The boundary is repeated on the turn, so default environments cannot be reintroduced.
            # A pipe failure while sending can be ambiguous; mark before submission.
            started = True
            request_id = connection.send(
                "turn/start",
                {
                    "threadId": thread_id,
                    "environments": [],
                    "runtimeWorkspaceRoots": [],
                    "model": model,
                    "effort": "low",
                    "serviceTierForTurn": "default",
                    "input": [{"type": "text", "text": messages[1]["content"], "text_elements": []}],
                    "outputSchema": schema,
                },
            )
            on_event({"type": "provider_started", "message": "Codex создаёт игру одним запросом."})
            first = True
            while True:
                event = connection.pending.pop(0) if connection.pending else connection.next(is_cancelled)
                if event.get("id") == request_id:
                    if "error" in event:
                        raise GenerationError(
                            "codex_request_rejected",
                            "Codex отклонил запрос: " + str(event["error"].get("message", ""))[:300],
                            outcome_unknown=False,
                        )
                    turn_id = event.get("result", {}).get("turn", {}).get("id")
                method = event.get("method")
                params = event.get("params") or {}
                if method == "thread/tokenUsage/updated":
                    usage = _usage(params) or usage
                elif method == "item/agentMessage/delta":
                    text += params.get("delta", "")
                    if first:
                        on_event({"type": "first_output", "message": "Модель начала отдавать код игры."})
                        first = False
                elif method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                    text = params["item"].get("text", text)
                elif method == "item/started":
                    item_type = params.get("item", {}).get("type")
                    if item_type in {
                        "commandExecution",
                        "fileChange",
                        "mcpToolCall",
                        "dynamicToolCall",
                        "webSearch",
                        "imageGeneration",
                        "collabAgentToolCall",
                    }:
                        raise GenerationError(
                            "unexpected_tool",
                            "Вызов инструмента не разрешён в генерации мини-игры.",
                            outcome_unknown=True,
                        )
                elif method == "turn/completed":
                    turn = params.get("turn", {})
                    if turn.get("status") != "completed":
                        code = "cancelled" if turn.get("status") == "interrupted" else "codex_turn_failed"
                        raise GenerationError(
                            code,
                            "Codex не завершил ответ. " + (
                                "Полученный фрагмент сохранён, но не применён к игре."
                                if text else "Код ответа не получен; изменений игры нет."
                            ),
                            usage=usage,
                            outcome_unknown=True,
                            raw_response={"partial_response": text, "provider_error": turn.get("error")},
                        )
                    break
                if len(text.encode()) > 2000000:
                    raise GenerationError(
                        "response_too_large",
                        "Ответ превышает размер мини-игры.",
                        usage=usage,
                        outcome_unknown=True,
                    )
            try:
                response = json.loads(text)
            except ValueError as exc:
                raise GenerationError(
                    "invalid_json", "Модель вернула неверный JSON.", usage=usage, raw_response=text
                ) from exc
            return {
                "response": response,
                "usage": usage,
                "model": model,
                "raw_response": text,
                "provider_metadata": {
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "environment_access": False,
                },
            }
        except GenerationError as exc:
            exc.provider_metadata = {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "environment_access": False,
            }
            if exc.usage is None:
                exc.usage = usage
            if exc.raw_response is None:
                exc.raw_response = text or None
            if not started:
                exc.outcome_unknown = False
            if exc.code == "cancelled" and thread_id and turn_id:
                try:
                    connection.send("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                except GenerationError:
                    pass
            raise
        finally:
            connection.close()
