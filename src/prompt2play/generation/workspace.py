"""Capability-scoped draft data and run-wide budgets; no generated code execution."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from prompt2play.contracts.source_policy import source_findings
from prompt2play.pricing import cost_bounds, reservation_usage


class GenerationStopped(RuntimeError):
    """Cancellation, fence expiry, deadline, or a hard budget stops the attempt."""


class GenerationPaused(GenerationStopped):
    """A durable checkpoint is available; stop dispatch without marking failure."""


class BudgetExhausted(GenerationStopped):
    """A resumable admission stop; completed work and receipts must be saved."""


@dataclass(frozen=True)
class WorkspaceLimits:
    max_files: int = 16
    max_file_bytes: int = 180_000
    max_total_bytes: int = 600_000
    max_turns: int | None = None
    max_quick_checks: int | None = None
    max_operations: int | None = None


@dataclass
class GenerationControl:
    deadline: float
    token_limit: int = 400_000
    cancel: threading.Event = field(default_factory=threading.Event)
    fence_check: Callable[[], bool] = lambda: True
    usage: dict[str, int] = field(
        default_factory=lambda: {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }
    )
    cost_limit_nano: int | None = None
    pricing: dict[str, Any] = field(default_factory=dict)
    spent_nano: int = 0
    uncertain_cost_nano: int = 0
    uncertain_tokens: int = 0
    reservations: dict[str, int] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @classmethod
    def bounded(cls, seconds: float | None = None, **kwargs: Any) -> GenerationControl:
        return cls(
            deadline=time.monotonic() + seconds if seconds is not None else float("inf"), **kwargs
        )

    def guard(self, *, check_budget: bool = True) -> None:
        if self.cancel.is_set():
            raise GenerationStopped("Generation cancelled or lease lost")
        if time.monotonic() >= self.deadline:
            raise GenerationStopped("Run deadline exceeded")
        if not self.fence_check():
            raise GenerationStopped("Current execution fence is no longer owned")
        if not check_budget:
            return
        with self.lock:
            if self.cost_limit_nano is not None:
                if self.spent_nano + self.uncertain_cost_nano > self.cost_limit_nano:
                    raise BudgetExhausted("Расчётный долларовый бюджет исчерпан")
            elif self.usage["total_tokens"] + self.uncertain_tokens > self.token_limit:
                raise BudgetExhausted("Run token budget exceeded")

    def reserve(self, key: str, amount: int) -> None:
        self.guard()
        with self.lock:
            if key in self.reservations:
                raise GenerationStopped("Invocation already reserved")
            committed, limit = self._budget()
            if committed + sum(self.reservations.values()) + amount > limit:
                raise BudgetExhausted(
                    "Следующий запрос не помещается в оставшийся долларовый бюджет"
                    if self.cost_limit_nano is not None
                    else f"Cannot reserve {amount} tokens within remaining run budget"
                )
            self.reservations[key] = amount

    def settle(self, key: str, usage: dict[str, int] | None) -> None:
        with self.lock:
            reservation = self.reservations.pop(key)
            if usage is None:
                self._hold(reservation)
            else:
                if any(
                    type(usage.get(name)) is not int or usage[name] < 0
                    for name in ("input_tokens", "output_tokens", "total_tokens", "calls")
                ):
                    self._hold(reservation)
                    raise GenerationStopped(
                        "Provider usage is malformed; reservation remains charged"
                    )
                if self.cost_limit_nano is not None:
                    try:
                        self.spent_nano += cost_bounds(usage, self.pricing)[1]
                    except ValueError as exc:
                        self._hold(reservation)
                        raise GenerationStopped(
                            "Invalid cost receipt; reservation retained"
                        ) from exc
                for name in self.usage:
                    self.usage[name] += usage.get(name, 0)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "usage": dict(self.usage),
                "uncertain_tokens": self.uncertain_tokens,
                "reservations": dict(self.reservations),
                "reservation_unit": "nano_usd" if self.cost_limit_nano is not None else "tokens",
                "cost_limit_nano": self.cost_limit_nano,
                "spent_nano": self.spent_nano,
                "uncertain_cost_nano": self.uncertain_cost_nano,
                "pricing": self.pricing,
            }

    def _hold(self, amount: int) -> None:
        if self.cost_limit_nano is not None:
            self.uncertain_cost_nano += amount
        else:
            self.uncertain_tokens += amount

    def _budget(self) -> tuple[int, int]:
        if self.cost_limit_nano is not None:
            return self.spent_nano + self.uncertain_cost_nano, self.cost_limit_nano
        return self.usage["total_tokens"] + self.uncertain_tokens, self.token_limit

    def estimate(self, prompt: str, max_output: int, schema: str = "") -> int:
        if self.cost_limit_nano is not None:
            return cost_bounds(reservation_usage(prompt, max_output, schema), self.pricing)[1]
        return invocation_reservation(prompt, max_output)

    def available_budget(self) -> int:
        """Headroom in the active unit, including outstanding/unknown calls."""
        self.guard()
        with self.lock:
            committed, limit = self._budget()
            return max(0, limit - committed - sum(self.reservations.values()))

    def available_tokens(self) -> int:
        if self.cost_limit_nano is not None:
            raise ValueError("Dollar budgets do not have a total-token ceiling")
        return self.available_budget()


def invocation_reservation(prompt: str, max_output: int) -> int:
    """Shared conservative bound used by dispatch and the actual invocation ledger."""
    return len(prompt.encode()) + max_output + 1024


def normalized_path(path: str) -> str:
    if not isinstance(path, str) or len(path) > 120 or path != unicodedata.normalize("NFC", path):
        raise ValueError("Path must be a bounded NFC name")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or any(
        part in ("", ".", "..") or part.startswith(".") for part in path.split("/")
    ):
        raise ValueError("Absolute, traversal, and hidden paths are forbidden")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*\.(js|css|json|svg)", path):
        raise ValueError("Unsupported source path or extension")
    if any(
        part.lower() in ("runtime", "trusted", "node_modules") for part in parsed.parts
    ) or parsed.name.lower().startswith("runtime"):
        raise ValueError("Trusted runtime files are immutable")
    return path


class DraftWorkspace:
    """Only text data is admitted; no links, special files, or host paths exist."""

    def __init__(
        self,
        control: GenerationControl,
        limits: WorkspaceLimits,
        files: dict[str, str] | None = None,
        *,
        allowed_paths: set[str] | None = None,
    ) -> None:
        self.control, self.limits = control, limits
        self.allowed_paths = allowed_paths
        self.files: dict[str, str] = {}
        self.closed = False
        self.operations = 0
        self.quick_checks = 0
        self.noops = 0
        self.history: list[dict[str, Any]] = []
        for name, source in (files or {}).items():
            self.write(name, source, create=True)
        self.operations = 0
        self.history = []

    def _guard(self, path: str | None = None) -> str | None:
        # Applying an already-paid response must survive a reported cost overrun.
        # Cancellation, lease fencing, deadlines and source quotas still apply.
        self.control.guard(check_budget=False)
        if self.closed:
            raise GenerationStopped("Draft was already submitted")
        self.operations += 1
        if self.limits.max_operations is not None and self.operations > self.limits.max_operations:
            raise GenerationStopped("Draft operation budget exceeded")
        if path is not None:
            path = normalized_path(path)
            if self.allowed_paths is not None and path not in self.allowed_paths:
                raise ValueError("Path is outside this attempt's file capability")
        return path

    def read(self, path: str) -> str:
        self._guard(path)
        return self.files[path]

    def write(self, path: str, content: str, *, create: bool = False) -> None:
        self._guard(path)
        if (
            not isinstance(content, str)
            or not content.strip()
            or len(content.encode()) > self.limits.max_file_bytes
        ):
            raise ValueError("Source is empty or exceeds the per-file byte limit")
        if create and path in self.files:
            raise ValueError("Create cannot overwrite an existing file")
        if not create and path not in self.files:
            raise ValueError("Replace requires an existing file")
        if any(name.casefold() == path.casefold() and name != path for name in self.files):
            raise ValueError("Case-colliding paths are forbidden")
        before = self.files.get(path)
        if before == content:
            self.noops += 1
            raise ValueError("No-op write does not create a revision")
        proposed = {**self.files, path: content}
        if (
            len(proposed) > self.limits.max_files
            or sum(len(value.encode()) for value in proposed.values()) > self.limits.max_total_bytes
        ):
            raise ValueError("Draft file or byte quota exceeded")
        self.files[path] = content
        self.history.append(
            {
                "operation": "create" if create else "replace",
                "path": path,
                "before": hashlib.sha256(before.encode()).hexdigest() if before else None,
                "after": hashlib.sha256(content.encode()).hexdigest(),
            }
        )

    def patch(self, path: str, old: str, new: str) -> None:
        self._guard(path)
        current = self.files[path]
        if not old or current.count(old) != 1:
            raise ValueError("Patch anchor must match exactly once")
        self.write(path, current.replace(old, new, 1))

    def delete(self, path: str) -> None:
        self._guard(path)
        del self.files[path]
        self.history.append({"operation": "delete", "path": path})

    def check(self) -> list[dict[str, Any]]:
        self._guard()
        self.quick_checks += 1
        if (
            self.limits.max_quick_checks is not None
            and self.quick_checks > self.limits.max_quick_checks
        ):
            raise GenerationStopped("Quick-check budget exceeded")
        return quick_check(self.files, self.control)

    def submit(self) -> dict[str, str]:
        self._guard()
        if not self.files:
            raise ValueError("Cannot submit an empty draft")
        self.closed = True
        return dict(self.files)


def quick_check(files: dict[str, str], control: GenerationControl) -> list[dict[str, Any]]:
    """Shared source policy plus parse-only syntax. A pass cannot approve a game."""
    findings: list[dict[str, Any]] = []
    node = shutil.which("node")
    with tempfile.TemporaryDirectory(prefix="p2p-parse-") as directory:
        for name, source in files.items():
            control.guard(check_budget=False)
            for violation in source_findings(
                source, javascript=name.endswith(".js"), runtime_managed=True
            ):
                findings.append(
                    {
                        "code": "offline_source",
                        "file": name,
                        "scope": "local",
                        "message": violation.message,
                        "construct": violation.code,
                    }
                )
            if name.endswith(".js"):
                if not node:
                    findings.append(
                        {
                            "code": "syntax_unavailable",
                            "file": name,
                            "scope": "infrastructure",
                            "message": "Parse-only Node syntax checker unavailable",
                        }
                    )
                    continue
                path = Path(directory) / Path(name).name
                path.write_text(source, encoding="utf-8")
                remaining = max(0.01, min(10, control.deadline - time.monotonic()))
                try:
                    result = subprocess.run(
                        [node, "--check", str(path)],
                        capture_output=True,
                        text=True,
                        timeout=remaining,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    findings.append(
                        {
                            "code": "syntax_timeout",
                            "file": name,
                            "scope": "infrastructure",
                            "message": "Parse-only syntax deadline exceeded",
                        }
                    )
                    continue
                control.guard(check_budget=False)
                if result.returncode:
                    findings.append(
                        {
                            "code": "javascript_syntax",
                            "file": name,
                            "scope": "local",
                            "message": result.stderr.replace(directory, "<draft>")[-1500:],
                        }
                    )
    return findings
