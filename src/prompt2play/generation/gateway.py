"""Typed adapters around audited Codex and Responses transports, with one ledger."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

from prompt2play.contracts.models import stable
from prompt2play.legacy.worker.core import ProviderError
from prompt2play.legacy.worker.providers import CodexProvider, OpenAIProvider
from prompt2play.pricing import reservation_usage

from .workspace import GenerationControl, GenerationStopped, invocation_reservation


@dataclass(frozen=True)
class GatewayReply:
    data: dict[str, Any]
    usage: dict[str, int]
    invocation_key: str
    reused: bool = False


class InvocationJournal(Protocol):
    def reserve(
        self,
        key: str,
        reserved_tokens: int,
        operation: str,
        request_sha256: str,
        *,
        estimate: dict[str, int] | None = None,
    ) -> dict[str, Any] | None: ...
    def settle(
        self, key: str, *, data: dict[str, Any] | None, usage: dict[str, int] | None, status: str
    ) -> None: ...


class ModelGateway(Protocol):
    name: str
    model: str
    capabilities: frozenset[str]

    def generate(
        self,
        prompt: str,
        schema: dict[str, Any],
        role: str,
        control: GenerationControl,
        *,
        max_output: int = 16000,
    ) -> GatewayReply: ...


class ProviderGateway:
    capabilities = frozenset({"structured_output", "file_operations"})

    def __init__(
        self,
        provider: str,
        model: str = "",
        *,
        timeout: float = 300,
        executable: str = "codex",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        journal: InvocationJournal | None = None,
    ) -> None:
        if provider not in ("codex", "openai"):
            raise ValueError("Supported providers are codex and openai")
        self.name, self.model, self.journal = provider, model, journal
        self.provider: Any = (
            cast(Any, CodexProvider)(model=model, timeout=timeout, executable=executable)
            if provider == "codex"
            else cast(Any, OpenAIProvider)(
                model=model, timeout=timeout, api_key=api_key, base_url=base_url
            )
        )
        self.records: list[dict[str, Any]] = []
        self.lock = threading.RLock()

    def preflight(self) -> None:
        self.provider.preflight()

    @property
    def is_replay(self) -> bool:
        """True only when this gateway has reused every recorded structured response."""
        with self.lock:
            return bool(self.records) and all(
                record["status"] == "reused" for record in self.records
            )

    def generate(
        self,
        prompt: str,
        schema: dict[str, Any],
        role: str,
        control: GenerationControl,
        *,
        max_output: int = 16000,
    ) -> GatewayReply:
        control.guard()
        if control.cost_limit_nano is not None and (
            control.pricing.get("model") != self.model
            or control.pricing.get("provider") != self.name
        ):
            raise GenerationStopped("Model differs from the frozen job tariff")
        request_sha = hashlib.sha256(
            stable(
                {
                    "provider": self.name,
                    "model": self.model,
                    "prompt": prompt,
                    "schema": schema,
                    "role": role,
                    "max_output": max_output,
                }
            ).encode()
        ).hexdigest()
        key = role + ":" + request_sha
        reservation = control.estimate(prompt, max_output, stable(schema))
        journal_tokens = invocation_reservation(prompt, max_output)
        reused = None
        if self.journal:
            if control.cost_limit_nano is not None:
                reused = self.journal.reserve(
                    key,
                    journal_tokens,
                    role,
                    request_sha,
                    estimate=reservation_usage(prompt, max_output, stable(schema)),
                )
            else:
                reused = self.journal.reserve(key, journal_tokens, role, request_sha)
        if reused:
            control.guard()
            data = cast(dict[str, Any], reused["data"])
            cached_usage = cast(dict[str, int], reused["usage"])
            with self.lock:
                self.records.append(
                    {
                        "key": key,
                        "role": role,
                        "request_sha256": request_sha,
                        "usage": cached_usage,
                        "seconds": 0,
                        "status": "reused",
                    }
                )
            return GatewayReply(data, cached_usage, key, reused=True)
        try:
            control.reserve(key, reservation)
            # Evaluation journals can persist the local dispatch boundary. A
            # reservation alone cannot prove the provider was ever attempted.
            marker = getattr(self.journal, "mark_started", None)
            if callable(marker):
                marker(key)
            # The durable write may have consumed the remaining lease/deadline.
            # Recheck before dispatch, with the same known-zero failure path.
            control.guard()
        except Exception:
            # The durable intent exists, but the provider was never dispatched.
            # Preserve that known zero cost rather than inventing uncertain spend.
            zero_usage = dict.fromkeys(control.usage, 0)
            if key in control.reservations:
                control.settle(key, zero_usage)
            try:
                if self.journal:
                    self.journal.settle(key, data=None, usage=zero_usage, status="not_started")
            finally:
                with self.lock:
                    self.records.append(
                        {
                            "key": key,
                            "role": role,
                            "request_sha256": request_sha,
                            "usage": zero_usage,
                            "seconds": 0,
                            "status": "not_started",
                        }
                    )
            raise
        started = time.monotonic()
        expired = threading.Event()

        def deadline() -> None:
            expired.set()
            control.cancel.set()

        timer = threading.Timer(max(0.01, control.deadline - started), deadline)
        timer.daemon = True
        timer.start()
        usage: dict[str, int] | None = None
        try:
            reply = self.provider.generate(
                prompt, schema, role, control.cancel, max_output=max_output, model=self.model
            )
            usage = cast(dict[str, int], reply.usage)
            control.settle(key, usage)
            if self.journal:
                self.journal.settle(key, data=reply.data, usage=usage, status="completed")
            control.guard()
            with self.lock:
                self.records.append(
                    {
                        "key": key,
                        "role": role,
                        "request_sha256": request_sha,
                        "usage": usage,
                        "seconds": time.monotonic() - started,
                        "status": "completed",
                    }
                )
            return GatewayReply(cast(dict[str, Any], reply.data), usage, key)
        except Exception as exc:
            if key in control.reservations:
                usage = cast(dict[str, int] | None, getattr(exc, "usage", None))
                control.settle(key, usage)
                if self.journal:
                    self.journal.settle(
                        key,
                        data=None,
                        usage=usage,
                        status="interrupted_unknown" if usage is None else "failed",
                    )
            with self.lock:
                self.records.append(
                    {
                        "key": key,
                        "role": role,
                        "request_sha256": request_sha,
                        "usage": usage,
                        "seconds": time.monotonic() - started,
                        "status": "failed",
                    }
                )
            if expired.is_set():
                raise GenerationStopped("Run deadline exceeded during model call") from exc
            raise
        finally:
            timer.cancel()


__all__ = ["GatewayReply", "InvocationJournal", "ModelGateway", "ProviderError", "ProviderGateway"]
