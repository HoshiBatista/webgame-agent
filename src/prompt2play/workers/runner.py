"""Role-scoped staged workers; every paid call and submission is fenced."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import signal
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from prompt2play.generation import (
    GenerationControl,
    GenerationHarness,
    GenerationRequest,
    ProviderGateway,
)
from prompt2play.generation.workspace import GenerationStopped
from prompt2play.validation import IsolatedValidator
from prompt2play.workers.diagnostics import emit, exception_details, safe_message
from prompt2play.workers.model_catalog import CodexModelCatalog


class LeaseRejected(RuntimeError):
    """The coordinator denied this worker's credentials or current fence."""


class Coordinator:
    def __init__(self, server: str, token: str, *, client: httpx.Client | None = None) -> None:
        address = urlparse(server)
        if address.scheme not in ("http", "https") or not address.hostname or address.username:
            raise ValueError("Coordinator URL must be HTTP(S) without credentials")
        if address.scheme == "http" and address.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote coordinators require HTTPS")
        if not token:
            raise ValueError("Runner token is missing")
        self.client = client or httpx.Client(
            base_url=server.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + token},
            timeout=30,
            follow_redirects=False,
        )

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(path.lstrip("/"), json=payload)
        if response.status_code in (401, 403, 409):
            raise LeaseRejected(
                f"Coordinator rejected credentials or fence ({response.status_code})"
            )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Coordinator response is not an object")
        return value

    def close(self) -> None:
        self.client.close()


class StageLease:
    def __init__(self, coordinator: Coordinator, claim: dict[str, Any], cancel: threading.Event):
        self.coordinator, self.claim, self.cancel = coordinator, claim, cancel
        self.job = claim["job"]
        self.fence = int(self.job["stage_fence"])
        self.token = str(claim["lease_token"])
        self.seconds = float(claim.get("lease_seconds", 120))
        self.last_ack = time.monotonic()
        remaining = self.job.get("remaining_seconds", claim.get("remaining_seconds"))
        self.run_expires = (
            time.monotonic() + max(0, float(remaining)) if remaining is not None else float("inf")
        )
        self.finished = threading.Event()
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)

    def alive(self) -> bool:
        return (
            not self.cancel.is_set()
            and time.monotonic() < self.run_expires
            and time.monotonic() - self.last_ack < self.seconds - 5
        )

    def remaining(self, limit: float) -> float:
        """Every stage inherits the original run budget, including reclaimed work."""
        return min(limit, max(0, self.run_expires - time.monotonic()))

    def write(self, action: str, **payload: Any) -> dict[str, Any]:
        if not self.alive():
            self.cancel.set()
            raise LeaseRejected("Lease no longer acknowledged")
        try:
            return self.coordinator.post(
                f"api/worker/jobs/{self.job['id']}/{action}/",
                {"lease_token": self.token, "stage_fence": self.fence, **payload},
            )
        except LeaseRejected:
            self.cancel.set()
            raise

    def _heartbeat(self) -> None:
        while not self.finished.wait(max(0.05, min(20, self.seconds / 4, self.remaining(20)))):
            try:
                response = self.write("heartbeat")
                if response.get("cancelled"):
                    self.cancel.set()
                    return
                self.seconds = float(response.get("lease_seconds", self.seconds))
                if response.get("remaining_seconds") is not None:
                    self.run_expires = min(
                        self.run_expires, time.monotonic() + float(response["remaining_seconds"])
                    )
                self.last_ack = time.monotonic()
            except (httpx.HTTPError, ValueError, LeaseRejected):
                if not self.alive():
                    self.cancel.set()
                    return

    def __enter__(self) -> StageLease:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.finished.set()
        self.thread.join(timeout=31)


class RemoteJournal:
    """Uncertain responses stay charged and never trigger automatic replay."""

    def __init__(self, lease: StageLease, control: GenerationControl):
        self.lease, self.control = lease, control
        self.invocations: dict[str, str] = {}
        self.lock = threading.RLock()

    def reserve(
        self, key: str, reserved_tokens: int, operation: str, request_sha256: str
    ) -> dict[str, Any] | None:
        with self.lock:
            result = self.lease.write(
                "reserve",
                invocation_key=key,
                reserved_tokens=reserved_tokens,
                operation=operation,
                prompt_sha256=request_sha256,
            )
            emit(
                "model_reserved",
                job_id=self.lease.job["id"],
                stage_fence=self.lease.fence,
                invocation_key=key,
                operation=operation,
                reserved_tokens=reserved_tokens,
                state=result["state"],
            )
            if result["state"] == "completed":
                response = result["response"]
                if not isinstance(response, dict) or not {"data", "usage"} <= response.keys():
                    raise GenerationStopped("Completed invocation response is unavailable")
                return response
            if (
                result["state"] != "reserved"
                or result["stage_fence"] != self.lease.fence
                or key in self.invocations
            ):
                raise GenerationStopped(
                    "Ambiguous invocation retained; explicit reconciliation is required"
                )
            self.invocations[key] = str(result["id"])
            return None

    def settle(
        self,
        key: str,
        *,
        data: dict[str, Any] | None,
        usage: dict[str, int] | None,
        status: str,
    ) -> None:
        with self.lock:
            payload: dict[str, Any] = {
                "invocation_id": self.invocations[key],
                "state": "completed" if status == "completed" else "ambiguous",
                "response": {"data": data, "usage": usage} if status == "completed" else {},
            }
            if usage is not None:
                payload["usage"] = self.control.snapshot()["usage"]
                payload["invocation_usage"] = usage
            emit(
                "model_receipt",
                job_id=self.lease.job["id"],
                stage_fence=self.lease.fence,
                invocation_key=key,
                status=status,
                usage=usage,
            )
            try:
                self.lease.write("settle", **payload)
            except (LeaseRejected, httpx.HTTPError):
                if usage is not None:
                    # Accounting-only endpoint cannot store output or advance a cancelled job.
                    # Server retains the conservative reservation if this receipt also fails.
                    with contextlib.suppress(httpx.HTTPError, LeaseRejected, ValueError):
                        self.lease.coordinator.post(
                            f"api/worker/jobs/{self.lease.job['id']}/account/",
                            {"invocation_id": self.invocations[key], "invocation_usage": usage},
                        )
                raise


def generation_request(claim: dict[str, Any], mode: str) -> GenerationRequest:
    job = claim["job"]
    candidate = claim.get("candidate") or {}
    base = candidate if job["stage"] == "repair" else (claim.get("base_version") or {})
    checkpoint = job.get("checkpoint") or {}
    strategy = checkpoint.get("strategy", "structural")
    report = candidate.get("validation", {})
    findings = [item for item in report.get("checks", []) if item.get("status") == "failed"]
    changed = checkpoint.get("files") if strategy in ("local", "structural") else None
    return GenerationRequest(
        prompt=job["prompt"],
        kind="repair" if job["stage"] == "repair" else job["kind"],
        mode=mode,
        base_files={}
        if strategy == "regenerate" and job["stage"] == "repair"
        else base.get("files", {}),
        base_spec=base.get("spec", {}),
        base_plan=base.get("plan", {}),
        findings=findings,
        changed_files=frozenset(changed) if changed else None,
        parent_id=job.get("base_version_id"),
        attempt_id=f"{job['id']}:{job.get('attempts', 0) + 1}",
        replan=strategy in ("replan", "regenerate") and job["stage"] == "repair",
    )


def generate_stage(lease: StageLease, args: argparse.Namespace) -> None:
    control = GenerationControl.bounded(
        lease.remaining(args.deadline),
        token_limit=lease.job["budget_tokens"],
        cancel=lease.cancel,
        fence_check=lease.alive,
        usage=dict(lease.job["usage"]),
    )
    gateway = ProviderGateway(
        lease.job["provider"],
        lease.job.get("model") or args.model,
        timeout=args.call_timeout,
        executable=args.codex,
        journal=RemoteJournal(lease, control),
    )
    gateway.preflight()
    candidate = GenerationHarness().attempt(
        generation_request(lease.claim, args.mode), gateway, control
    )
    data = candidate.as_dict()
    identity = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    lease.write("candidates", idempotency_key=identity, **data)


def evidence_payload(report: dict[str, Any], directory: Path) -> dict[str, str]:
    result = {}
    for item in report.get("evidence_files", []):
        path = (directory / item["path"]).resolve()
        if not path.is_relative_to(directory.resolve()) or path.is_symlink():
            raise ValueError("Evidence path escapes its dedicated directory")
        data = path.read_bytes()
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Evidence file differs from the report")
        result[item["path"]] = base64.b64encode(data).decode("ascii")
    return result


def validate_stage(lease: StageLease, args: argparse.Namespace) -> None:
    candidate = lease.claim["candidate"]
    acceptance = None
    if args.acceptance:
        # Operator-controlled declaration is loaded only on a scoped validator runner.
        inventory = json.loads(Path(args.acceptance).read_text(encoding="utf-8"))
        acceptance = inventory.get(lease.job["project_id"], inventory.get("default"))
    with tempfile.TemporaryDirectory(prefix="p2p-evidence-") as temporary:
        directory = Path(temporary) / "evidence"
        report = IsolatedValidator(args.image, lease.remaining(args.validation_timeout)).validate(
            candidate["files"],
            candidate["html"],
            candidate["spec"],
            lease.cancel,
            directory,
            release_scenarios=acceptance,
        )
        lease.write(
            "validate",
            candidate_id=candidate["id"],
            report=report,
            evidence_files=evidence_payload(report, directory),
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="prompt2play worker")
    result.add_argument("--server", default="http://127.0.0.1:8000")
    result.add_argument("--role", choices=("generator", "validator"), required=True)
    result.add_argument("--token-env", default="PROMPT2PLAY_RUNNER_TOKEN")
    result.add_argument("--provider", choices=("codex", "openai"), default="codex")
    result.add_argument("--model", default="")
    result.add_argument("--codex", default="codex")
    result.add_argument("--mode", choices=("single_author", "four_author"), default="single_author")
    result.add_argument("--deadline", type=float, default=600)
    result.add_argument("--call-timeout", type=float, default=300)
    result.add_argument("--image", default="prompt2play-validator:local")
    result.add_argument("--validation-timeout", type=float, default=90)
    result.add_argument(
        "--acceptance", help="Trusted JSON map of project IDs to real-input scenarios"
    )
    result.add_argument("--poll", type=float, default=2)
    result.add_argument("--once", action="store_true", help="Claim and process at most one stage")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.deadline <= 0 or args.call_timeout <= 0 or args.poll <= 0:
        raise ValueError("Worker time limits must be positive")
    coordinator = Coordinator(args.server, os.environ.get(args.token_env, ""))
    stopping = threading.Event()
    active: list[threading.Event] = []

    def stop(_signum: int, _frame: object) -> None:
        stopping.set()
        for cancel in active:
            cancel.set()

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        capabilities = {
            "providers": [args.provider],
            "model": args.model,
            "validator": "docker",
            "requires_job_model": ["openai"]
            if args.role == "generator" and args.provider == "openai" and not args.model
            else [],
        }
        emit("worker_started", role=args.role, provider=args.provider, model=args.model)
        catalog = (
            CodexModelCatalog(args.codex)
            if args.role == "generator" and args.provider == "codex"
            else None
        )
        claim_failures = 0
        while not stopping.is_set():
            if catalog is not None:
                capabilities.update(catalog.capabilities())
                if stopping.is_set():
                    break
            try:
                claim = coordinator.post("api/worker/claim/", {"capabilities": capabilities})
            except LeaseRejected as exc:
                emit("worker_rejected", role=args.role, **exception_details(exc))
                return 2
            except httpx.HTTPError as exc:
                # A claim invokes no model. An unseen successful claim expires under
                # its existing fence; do not replay any stage, submission or paid call.
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code == 429 or exc.response.status_code >= 500
                )
                claim_failures += 1
                retry_seconds = min(30, args.poll * 2 ** min(claim_failures, 4))
                emit(
                    "claim_connection_failed",
                    role=args.role,
                    retry_seconds=retry_seconds if retryable and not args.once else None,
                    **exception_details(exc),
                )
                if args.once or not retryable:
                    return 1
                stopping.wait(retry_seconds)
                continue
            claim_failures = 0
            if not claim.get("job"):
                if args.once:
                    return 0
                stopping.wait(args.poll)
                continue
            cancel = threading.Event()
            active.append(cancel)
            stage_exit = 0
            with StageLease(coordinator, claim, cancel) as lease:
                started = time.monotonic()
                context = {
                    "role": args.role,
                    "job_id": lease.job["id"],
                    "stage": lease.job.get("stage"),
                    "stage_fence": lease.fence,
                    "attempt": lease.job.get("attempts", 0) + 1,
                    "provider": lease.job.get("provider", args.provider),
                    "model": lease.job.get("model") or args.model,
                }
                emit("stage_started", **context)
                try:
                    if args.role == "validator":
                        validate_stage(lease, args)
                    else:
                        generate_stage(lease, args)
                    emit(
                        "stage_completed",
                        duration_seconds=round(time.monotonic() - started, 3),
                        **context,
                    )
                except LeaseRejected as exc:
                    stage_exit = 2
                    emit(
                        "stage_lease_rejected",
                        secrets=[lease.token],
                        **context,
                        **exception_details(exc, [lease.token]),
                    )
                except Exception as exc:
                    stage_exit = 1
                    emit(
                        "stage_failed",
                        secrets=[lease.token],
                        **context,
                        duration_seconds=round(time.monotonic() - started, 3),
                        **exception_details(exc, [lease.token]),
                    )
                    if lease.alive():
                        lease.write(
                            "fail",
                            error=safe_message(f"{type(exc).__name__}: {exc}", [lease.token]),
                        )
            active.remove(cancel)
            if args.once:
                return stage_exit
        return 0
    finally:
        coordinator.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
