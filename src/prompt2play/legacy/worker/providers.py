"""Real providers. Credentials stay on the runner, never in checkpoint/logs."""

from __future__ import annotations
import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
import httpx
import jsonschema
from .core import (
    Reply,
    ProviderError,
    Cancelled,
    check_cancel,
    usage_record,
    empty_usage,
    PROMPT_BOUNDARY,
)


def parse_json(text, schema):
    try:
        result = json.loads(text)
        jsonschema.validate(result, schema)
        return result
    except jsonschema.ValidationError as exc:
        # Expose trusted schema coordinates, never the rejected instance/message.
        names = set()
        pending = [schema]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                names.update(node.get("properties", {}))
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        path = [
            part if isinstance(part, int) or part in names else "<dynamic>"
            for part in list(exc.absolute_path)[:40]
        ]
        diagnostic = {
            "category": "schema",
            "keyword": exc.validator,
            "instance_path": path,
            "schema_path": list(exc.absolute_schema_path)[:60],
        }
        location = "/" + "/".join(str(part) for part in path)
        error = ProviderError(
            "Provider returned invalid structured JSON; " + str(exc.validator) + " at " + location
        )
        error.structured_diagnostic = diagnostic
        raise error from None
    except (ValueError, TypeError, RecursionError):
        error = ProviderError("Provider returned invalid structured JSON")
        error.structured_diagnostic = {"category": "invalid_json"}
        raise error from None


def portable_output_schema(schema):
    """Provider wire subset; full original bounds still validate the received JSON.

    Strict-output transports differ in numeric/string/array constraint support.
    Types, required fields, enums and object closure remain enforced remotely;
    size/range/uniqueness constraints are enforced locally before any operation.
    """
    unsupported = {
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "uniqueItems",
    }
    if isinstance(schema, dict):
        return {
            key: portable_output_schema(value)
            for key, value in schema.items()
            if key not in unsupported
        }
    if isinstance(schema, list):
        return [portable_output_schema(value) for value in schema]
    return schema


def response_text(response):
    text = []
    for item in response.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "refusal":
                raise ProviderError("Model refused this generation request")
            if part.get("type") == "output_text":
                text.append(part.get("text", ""))
    return "".join(text)


class OpenAIProvider:
    name = "openai"

    def __init__(self, model=None, api_key=None, timeout=180, base_url="https://api.openai.com/v1"):
        self.model = model or os.environ.get("OPENAI_MODEL", "")
        self.key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.timeout = timeout
        # No model-controlled endpoint. Configurable only for tests/local operators.
        self.base_url = base_url.rstrip("/")

    def preflight(self):
        if not self.key:
            raise ProviderError(
                "OPENAI_API_KEY is not configured on this runner", usage=empty_usage()
            )

    def generate(self, prompt, schema, role, cancel, max_output=6000, model=""):
        self.preflight()
        model = model or self.model
        if not model:
            raise ProviderError(
                "Set OPENAI_MODEL or choose an available OpenAI model in the job",
                usage=empty_usage(),
            )
        check_cancel(cancel)
        return asyncio.run(self._guarded(prompt, schema, role, cancel, max_output, model))

    async def _guarded(self, prompt, schema, role, cancel, max_output, model):
        # A terminal response can arrive before the transport finishes closing.
        # Keep its accounting outside the cancellable task so a later timeout
        # cannot turn reported spend into an unknown full-call reservation.
        account = {"usage": None}
        task = asyncio.create_task(
            self._generate(prompt, schema, role, cancel, max_output, model, account)
        )

        async def watch_cancel():
            while not cancel.is_set():
                await asyncio.sleep(0.05)
            raise Cancelled("Job cancelled while waiting for OpenAI")

        watcher = asyncio.create_task(watch_cancel())
        try:
            done, _ = await asyncio.wait(
                {task, watcher}, timeout=self.timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if watcher in done:
                return watcher.result()
            if task in done:
                check_cancel(cancel)
                return task.result()
            raise ProviderError("OpenAI call exceeded wall timeout")
        except (Cancelled, ProviderError) as exc:
            if getattr(exc, "usage", None) is None:
                exc.usage = account["usage"]
            raise
        except Exception as exc:
            raise ProviderError(
                "OpenAI transport or response finalization failed; request was not replayed",
                usage=account["usage"],
            ) from exc
        finally:
            task.cancel()
            watcher.cancel()
            await asyncio.gather(task, watcher, return_exceptions=True)

    async def _generate(self, prompt, schema, role, cancel, max_output, model, account):
        instructions, boundary, task_data = prompt.partition(PROMPT_BOUNDARY)
        payload = {
            "model": model,
            "input": task_data if boundary else prompt,
            "store": False,
            "stream": True,
            "max_output_tokens": max_output,
            "prompt_cache_key": "game-forge-v3-" + role,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "forge_" + role,
                    "schema": portable_output_schema(schema),
                    "strict": True,
                }
            },
        }
        if boundary:
            payload["instructions"] = instructions
        known_usage = None
        # The outer task owns the wall deadline and cancellation. Reasoning may
        # legitimately pause between events, so a separate 10s read cap is wrong.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=min(10, self.timeout)),
            follow_redirects=False,
        ) as client:
            for attempt in range(3):
                check_cancel(cancel)
                try:
                    async with client.stream(
                        "POST",
                        self.base_url + "/responses",
                        headers={"Authorization": "Bearer " + self.key},
                        json=payload,
                    ) as response:
                        if response.status_code == 429 and attempt < 2:
                            await asyncio.sleep(min(2**attempt, 4))
                            continue
                        if response.status_code >= 400:
                            # A server failure may occur after billable work. Only
                            # explicit rejection/throttling proves no generation.
                            rejected = response.status_code in (400, 401, 403, 404, 422, 429)
                            raise ProviderError(
                                f"OpenAI HTTP {response.status_code}; verify model, limits and runner credentials",
                                usage=empty_usage() if rejected else None,
                            )
                        async for event in response_events(response):
                            kind = event.get("type")
                            if kind in (
                                "response.completed",
                                "response.failed",
                                "response.incomplete",
                            ):
                                final = event.get("response")
                                if not isinstance(final, dict):
                                    raise ProviderError("Malformed terminal OpenAI event")
                                try:
                                    known_usage = usage_record(final.get("usage"))
                                except ProviderError:
                                    known_usage = None
                                account["usage"] = known_usage
                                check_cancel(cancel)
                                if kind != "response.completed":
                                    raise ProviderError(
                                        "OpenAI generation failed or output limit was reached",
                                        usage=known_usage,
                                    )
                                if known_usage is None:
                                    raise ProviderError(
                                        "Provider did not report valid usage; request spend is unknown"
                                    )
                                # completed already contains the full response; do not
                                # wait for a server to close a keep-alive stream.
                                return Reply(parse_json(response_text(final), schema), known_usage)
                            check_cancel(cancel)
                            if kind == "error":
                                raise ProviderError("OpenAI generation stream reported an error")
                        raise ProviderError("OpenAI stream ended without a completed response")
                except (ProviderError, Cancelled) as exc:
                    if getattr(exc, "usage", None) is None and known_usage is not None:
                        exc.usage = known_usage
                    raise
                except httpx.HTTPError as exc:
                    check_cancel(cancel)
                    raise ProviderError(
                        "OpenAI network timeout/failure; request was not replayed",
                        usage=known_usage,
                    ) from exc
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    raise ProviderError(
                        "Malformed OpenAI response stream", usage=known_usage
                    ) from exc
        raise ProviderError("OpenAI retry limit reached", usage=empty_usage())


async def response_events(response):
    """Bounded SSE framing, including multiline data and a final unterminated frame."""
    pending = b""
    data = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > 32 * 1024 * 1024:
            raise ProviderError("OpenAI event stream exceeded safety limit")
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if len(line) > 4 * 1024 * 1024:
                raise ProviderError("OpenAI event line exceeded safety limit")
            line = line.rstrip(b"\r")
            if line.startswith(b"data:"):
                data.append(line[5:].lstrip(b" "))
            elif not line and data:
                raw = b"\n".join(data)
                data = []
                if raw != b"[DONE]":
                    value = json.loads(raw)
                    if not isinstance(value, dict):
                        raise ProviderError("Invalid OpenAI SSE object")
                    yield value
        if len(pending) > 4 * 1024 * 1024:
            raise ProviderError("OpenAI event line exceeded safety limit")
    if pending.startswith(b"data:"):
        data.append(pending[5:].lstrip(b" ").rstrip(b"\r"))
    if data:
        raw = b"\n".join(data)
        if raw != b"[DONE]":
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ProviderError("Invalid OpenAI SSE object")
            yield value


class CodexProvider:
    name = "codex"

    def __init__(self, model=None, timeout=300, executable="codex"):
        self.model = model or os.environ.get("CODEX_MODEL", "")
        self.timeout = timeout
        self.executable = executable

    def preflight(self):
        if not shutil.which(self.executable):
            raise ProviderError(
                "Codex CLI not found; install it and run codex login locally", usage=empty_usage()
            )

    def generate(self, prompt, schema, role, cancel, max_output=6000, model=""):
        check_cancel(cancel)
        self.preflight()
        executable = shutil.which(self.executable)
        if not executable:
            raise ProviderError(
                "Codex CLI is no longer available on this runner", usage=empty_usage()
            )
        with tempfile.TemporaryDirectory(prefix="forge-codex-") as directory:
            root = Path(directory)
            schema_file, output = root / "schema.json", root / "result.json"
            schema_file.write_text(json.dumps(portable_output_schema(schema)), encoding="utf-8")
            args = [
                executable,
                "exec",
                "--json",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "-c",
                "features.shell_tool=false",
                "-c",
                'web_search="disabled"',
                "--output-schema",
                str(schema_file),
                "--output-last-message",
                str(output),
                "--cd",
                directory,
            ]
            chosen = model or self.model
            if chosen:
                args += ["--model", chosen]
            # The CLI does not document a portable max-output flag. This is a
            # reservation target, never represented as a guaranteed CLI cap.
            args += ["-"]
            events_file = root / "events.ndjson"
            stderr_file = root / "stderr.log"
            with events_file.open("wb") as events, stderr_file.open("wb") as errors:
                allowed_env = {
                    "PATH",
                    "HOME",
                    "USER",
                    "LOGNAME",
                    "SHELL",
                    "TMPDIR",
                    "TMP",
                    "TEMP",
                    "SYSTEMROOT",
                    "WINDIR",
                    "APPDATA",
                    "LOCALAPPDATA",
                    "XDG_CONFIG_HOME",
                    "XDG_DATA_HOME",
                    "XDG_CACHE_HOME",
                    "CODEX_HOME",
                    "LANG",
                    "LC_ALL",
                    "TERM",
                    "SSL_CERT_FILE",
                    "SSL_CERT_DIR",
                    "HTTPS_PROXY",
                    "HTTP_PROXY",
                    "ALL_PROXY",
                    "NO_PROXY",
                }
                child_env = {k: v for k, v in os.environ.items() if k in allowed_env}
                try:
                    proc = subprocess.Popen(
                        args,
                        stdin=subprocess.PIPE,
                        stdout=events,
                        stderr=errors,
                        env=child_env,
                        cwd=directory,
                        start_new_session=(os.name != "nt"),
                    )
                except OSError as exc:
                    raise ProviderError(
                        "Codex process could not start; verify the executable and local permissions",
                        usage=empty_usage(),
                    ) from exc
                writer_error = []

                def write_prompt():
                    try:
                        proc.stdin.write(prompt.encode("utf-8"))
                        proc.stdin.close()
                    except (BrokenPipeError, OSError) as exc:
                        writer_error.append(exc)

                writer = threading.Thread(target=write_prompt, daemon=True)
                writer.start()
                start = time.monotonic()
                interrupted = None
                try:
                    while proc.poll() is None:
                        check_cancel(cancel)
                        if time.monotonic() - start > self.timeout:
                            raise ProviderError("Codex call exceeded wall timeout")
                        if (
                            events_file.stat().st_size > 8_000_000
                            or stderr_file.stat().st_size > 1_000_000
                        ):
                            raise ProviderError("Codex process output exceeded safety limit")
                        cancel.wait(0.1)
                except (Cancelled, ProviderError) as exc:
                    interrupted = exc
                finally:
                    if proc.poll() is None:
                        if os.name != "nt":
                            import signal

                            with contextlib.suppress(ProcessLookupError):
                                os.killpg(proc.pid, signal.SIGTERM)
                        else:
                            proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            if os.name != "nt":
                                with contextlib.suppress(ProcessLookupError):
                                    os.killpg(proc.pid, signal.SIGKILL)
                            else:
                                proc.kill()
                            proc.wait()
                    writer.join(timeout=1)
            # Read the bounded, flushed event log after process cleanup even on
            # cancellation. A completed turn may already have reported usage.
            usage = codex_usage(events_file)
            if interrupted is not None:
                interrupted.usage = usage
                raise interrupted
            if cancel.is_set():
                error = Cancelled("Job cancelled or lease lost")
                error.usage = usage
                raise error
            if events_file.stat().st_size > 8_000_000 or stderr_file.stat().st_size > 1_000_000:
                raise ProviderError("Codex process output exceeded safety limit", usage=usage)
            if proc.returncode or not output.exists():
                reason = codex_failure_reason(events_file, stderr_file)
                raise ProviderError("Codex generation failed; " + reason, usage=usage)
            if output.stat().st_size > 2_000_000:
                raise ProviderError("Codex structured output too large", usage=usage)
            if usage is None:
                raise ProviderError(
                    "Codex did not report usage; cannot safely reconcile the token budget"
                )
            try:
                data = parse_json(output.read_text(encoding="utf-8"), schema)
                check_cancel(cancel)
                return Reply(data, usage)
            except (ProviderError, Cancelled) as exc:
                exc.usage = usage
                raise
            except (OSError, UnicodeError) as exc:
                raise ProviderError(
                    "Codex structured output could not be read as UTF-8 JSON", usage=usage
                ) from exc


def codex_usage(path):
    """Recover terminal usage without reading unbounded process output or stderr."""
    try:
        with path.open("rb") as stream:
            data = stream.read(8_000_001)
    except OSError:
        return None
    if len(data) > 8_000_000:
        return None
    usage = None
    for line in data.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            try:
                usage = usage_record(event.get("usage"))
            except ProviderError:
                usage = None
    return usage


def codex_failure_reason(events_path, stderr_path):
    """Only fixed failure classifications leave private CLI logs, never their text."""
    fragments = []
    try:
        with events_path.open("rb") as stream:
            data = stream.read(8_000_001)
        if len(data) <= 8_000_000:
            for line in data.splitlines():
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(event, dict) and event.get("type") in ("error", "turn.failed"):
                    fragments.append(str(event.get("message", "")))
                    fragments.append(str((event.get("error") or {}).get("message", "")))
        with stderr_path.open("rb") as stream:
            fragments.append(stream.read(1_000_000).decode("utf-8", errors="replace"))
    except (OSError, TypeError, AttributeError):
        pass
    detail = " ".join(fragments).lower()
    if "schema" in detail or "response_format" in detail:
        return "structured-output schema was rejected; inspect the schema compatibility"
    if any(word in detail for word in ("unauthorized", "authentication", "login", "401")):
        return "local authentication was rejected; verify Codex login"
    if any(
        word in detail
        for word in ("model not", "model is not", "unsupported model", "model_not_found")
    ):
        return "configured model is unavailable for this Codex account"
    if any(word in detail for word in ("rate limit", "quota", "429")):
        return "provider rate or quota limit was reached"
    if any(
        word in detail
        for word in ("connection", "network", "dns", "certificate", "stream disconnected")
    ):
        return "provider connection failed; ambiguous request was not replayed"
    return "verify local login and CLI configuration"
