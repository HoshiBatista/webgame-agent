"""Reproducible live strategy comparison; replay and infrastructure stay explicit."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from prompt2play.adapters.artifacts.store import JSON, ArtifactStore
from prompt2play.application.policy import decide, repair_route
from prompt2play.contracts.models import stable
from prompt2play.generation import (
    GenerationControl,
    GenerationHarness,
    GenerationRequest,
    ProviderGateway,
)
from prompt2play.generation.retries import CODEX_TIMEOUT_RECEIPT
from prompt2play.generation.workspace import GenerationStopped
from prompt2play.legacy.validator.evidence import report_matches
from prompt2play.paths import PACKAGE_ROOT, RESOURCE_ROOT
from prompt2play.validation import IsolatedValidator

SUITE_PATH = RESOURCE_ROOT / "evaluation" / "cases-v2.json"
EMPTY_USAGE = {
    "input_tokens": 0,
    "cached_input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
    "calls": 0,
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".pending")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FileJournal:
    """Durable structured responses, never raw reasoning or automatic uncertain retries."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
        self.lock = threading.RLock()

    def accounting(self) -> tuple[dict[str, int], int]:
        usage = dict(EMPTY_USAGE)
        uncertain = 0
        for entry in self.records.values():
            if entry.get("usage"):
                for name in usage:
                    usage[name] += entry["usage"].get(name, 0)
            elif entry["state"] != "completed":
                uncertain += entry["reserved_tokens"]
        return usage, uncertain

    def operation_metrics(self) -> dict[str, int]:
        """Local attempts and receipts are distinct from uncertain remote spend."""
        metrics = {
            "attempted_provider_operations": 0,
            "known_reported_requests": 0,
            "unknown_usage_operations": 0,
            "dispatch_uncertain_reservations": 0,
            "not_started_operations": 0,
            "reused_response_reads": 0,
        }
        with self.lock:
            for entry in self.records.values():
                usage = entry.get("usage")
                reported = usage.get("calls", 0) if isinstance(usage, dict) else 0
                # Settled older journals lack start markers; their receipts or
                # interrupted response prove a local attempt. A bare old intent
                # remains uncertain and never becomes a claimed paid request.
                attempted = entry["state"] != "not_started" and (
                    entry.get("started") is True
                    or reported > 0
                    or entry["state"] in ("interrupted_unknown", "timed_out")
                )
                metrics["attempted_provider_operations"] += int(attempted)
                metrics["known_reported_requests"] += reported
                metrics["unknown_usage_operations"] += int(attempted and usage is None)
                metrics["dispatch_uncertain_reservations"] += int(entry["state"] == "reserved")
                metrics["not_started_operations"] += int(entry["state"] == "not_started")
                metrics["reused_response_reads"] += entry.get("reused_response_reads", 0)
        return metrics

    def mark_started(self, key: str) -> None:
        """Persist the local attempt boundary, without asserting remote acceptance."""
        with self.lock:
            self.records[key]["started"] = True
            write_json(self.path, self.records)

    def reserve(
        self,
        key: str,
        reserved_tokens: int,
        operation: str,
        request_sha256: str,
        *,
        estimate: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        with self.lock:
            existing = self.records.get(key)
            if existing:
                if (
                    existing["operation"] != operation
                    or existing["request_sha256"] != request_sha256
                ):
                    raise GenerationStopped("Invocation key conflicts with its recorded request")
                if existing["state"] == "completed":
                    existing["reused_response_reads"] = existing.get("reused_response_reads", 0) + 1
                    write_json(self.path, self.records)
                    return {"data": existing["data"], "usage": existing["usage"]}
                if existing["state"] == "rejected_response":
                    return dict(existing["data"])
                if existing["state"] == "timed_out":
                    return dict(CODEX_TIMEOUT_RECEIPT)
                raise GenerationStopped(
                    "Uncertain call is preserved; explicit reconciliation required"
                )
            self.records[key] = {
                "state": "reserved",
                "reserved_tokens": reserved_tokens,
                "operation": operation,
                "request_sha256": request_sha256,
                "started": False,
            }
            write_json(self.path, self.records)
            return None

    def settle(
        self, key: str, *, data: dict[str, Any] | None, usage: dict[str, int] | None, status: str
    ) -> None:
        with self.lock:
            self.records[key].update(state=status, data=data, usage=usage)
            write_json(self.path, self.records)


def run_case(
    case: dict[str, Any],
    folder: Path,
    args: argparse.Namespace,
    *,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    # A process crash releases this lock; an uncertain paid call remains in the
    # journal. Concurrent evaluators must not race the same case checkpoint.
    with (folder / "run.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("This evaluation case is already running") from exc
        return _run_case(case, folder, args, base=base)


def _request_hash(
    case: dict[str, Any], base: dict[str, Any] | None, args: argparse.Namespace
) -> str:
    from prompt2play.generation.runtime import runtime_digest

    fields = (
        "mode",
        "provider",
        "model",
        "deadline",
        "tokens",
        "repairs",
        "plan_tokens",
        "code_tokens",
        "call_timeout",
        "validation_timeout",
        "image",
    )
    return hashlib.sha256(
        stable(
            {
                "case": case,
                "base": base,
                "limits": {name: getattr(args, name) for name in fields},
                "runtime_sha256": runtime_digest(),
            }
        ).encode()
    ).hexdigest()


def _request(
    case: dict[str, Any],
    base: dict[str, Any] | None,
    folder: Path,
    args: argparse.Namespace,
    state: dict[str, Any],
    store: ArtifactStore,
) -> GenerationRequest:
    prompt = case["revision"] if base else case["prompt"]
    attempts = state["attempts"]
    if not attempts:
        return GenerationRequest(
            prompt,
            kind="revise" if base else "generate",
            mode=args.mode,
            base_files=base.get("files", {}) if base else {},
            base_spec=base.get("spec", {}) if base else {},
            base_plan=base.get("plan", {}) if base else {},
            parent_id=base.get("artifact_key") if base else None,
            attempt_id=folder.name + ":1",
        )
    previous = attempts[-1]
    payload = cast(dict[str, Any], store.read_json(previous["artifact_key"]))
    report = cast(dict[str, Any], store.read_json(previous["report_key"]))
    strategy = previous["repair_strategy"]
    files = previous["repair_files"]
    return GenerationRequest(
        prompt,
        kind="repair",
        mode=args.mode,
        base_files={} if strategy == "regenerate" else payload["files"],
        base_spec=payload["spec"],
        base_plan=payload["plan"],
        findings=[entry for entry in report.get("checks", []) if entry.get("status") == "failed"],
        changed_files=frozenset(files) if files and strategy in ("local", "structural") else None,
        parent_id=previous["artifact_key"],
        attempt_id=folder.name + f":{len(attempts) + 1}",
        replan=strategy in ("replan", "regenerate"),
    )


def _run_case(
    case: dict[str, Any],
    folder: Path,
    args: argparse.Namespace,
    *,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_sha = _request_hash(case, base, args)
    result_path = folder / "result.json"
    if result_path.exists():
        recorded = json.loads(result_path.read_text())
        if recorded.get("request_sha256") != request_sha:
            raise ValueError("Completed evaluation is immutable; choose a new output directory")
        restored = (
            ArtifactStore(args.output / "objects").read_json(recorded["final_artifact_key"])
            if recorded["outcome"] == "passed"
            else None
        )
        return {
            "record": recorded,
            "candidate": {**restored, "artifact_key": recorded["final_artifact_key"]}
            if restored
            else None,
        }
    state_path = folder / "state.json"
    resumed = state_path.exists()
    if resumed:
        state = json.loads(state_path.read_text())
        if state.get("schema_version") != 2 or state.get("request_sha256") != request_sha:
            raise ValueError("Unfinished evaluation differs; choose a new output directory")
    else:
        if (folder / "invocations.json").exists():
            raise ValueError(
                "Uncheckpointed calls need explicit reconciliation; deadline is unknown"
            )
        started = time.time()
        state = {
            "schema_version": 2,
            "request_sha256": request_sha,
            "started_at": started,
            "expires_at": started + args.deadline,
            "attempts": [],
            "pending": None,
        }
        write_json(state_path, state)
    journal = FileJournal(folder / "invocations.json")
    usage, uncertain = journal.accounting()
    prior_calls = usage["calls"]
    prior_metrics = journal.operation_metrics()
    control = GenerationControl.bounded(
        min(args.deadline, state["expires_at"] - time.time()),
        token_limit=args.tokens,
        usage=dict(usage),
        uncertain_tokens=uncertain,
    )
    gateway = ProviderGateway(
        args.provider, args.model, timeout=args.call_timeout, executable=args.codex, journal=journal
    )
    store = ArtifactStore(args.output / "objects")
    harness = GenerationHarness(
        plan_output_tokens=args.plan_tokens, code_output_tokens=args.code_tokens
    )
    attempts: list[dict[str, Any]] = state["attempts"]
    final: dict[str, Any] | None = None
    outcome = "failed"
    timer = threading.Timer(max(0, control.deadline - time.monotonic()), control.cancel.set)
    timer.daemon = True
    timer.start()
    try:
        while len(attempts) <= args.repairs:
            if attempts and attempts[-1]["action"] != "repair":
                break
            control.guard()
            pending = state["pending"]
            if pending is None:
                request = _request(case, base, folder, args, state, store)
                gateway.preflight()
                control.guard()
                candidate = harness.attempt(request, gateway, control)
                payload = candidate.as_dict()
                intent, key = store.prepare(payload)
                pending = {
                    "number": len(attempts) + 1,
                    "artifact_key": key,
                    "intent": intent,
                    "validation_runs": [],
                }
                state["pending"] = pending
                write_json(state_path, state)
            if pending["number"] != len(attempts) + 1:
                raise ValueError("Evaluation attempt checkpoint is inconsistent")
            store.commit(pending["intent"], pending["artifact_key"])
            payload = cast(dict[str, Any], store.read_json(pending["artifact_key"]))
            final = {**payload, "artifact_key": pending["artifact_key"]}
            control.guard()
            if "report_key" not in pending:
                previous_path = pending.get("validation")
                validation_path = args.output / previous_path if previous_path else None
                if validation_path is None or not validation_path.is_file():
                    # An interrupted validator may have written partial evidence.
                    # Preserve it and run the same immutable bytes in a new folder.
                    evidence_dir = (
                        folder / f"attempt-{pending['number']}" / ("browser-" + uuid.uuid4().hex)
                    )
                    evidence_dir.mkdir(parents=True, exist_ok=False)
                    validation_path = evidence_dir / "validation.json"
                    relative_path = validation_path.relative_to(args.output).as_posix()
                    pending["validation"] = relative_path
                    pending["validation_runs"].append(relative_path)
                    write_json(state_path, state)
                    remaining = max(0.01, control.deadline - time.monotonic())
                    report = IsolatedValidator(
                        args.image, min(args.validation_timeout, remaining)
                    ).validate(
                        payload["files"],
                        payload["html"],
                        payload["spec"],
                        control.cancel,
                        evidence_dir,
                        release_scenarios=case.get("revision_acceptance", case.get("acceptance"))
                        if base
                        else case.get("acceptance"),
                    )
                    write_json(validation_path, report)
                else:
                    report = json.loads(validation_path.read_text())
                # The report must describe the candidate whose bytes were committed.
                if not cast(Any, report_matches)(
                    report, payload["files"], payload["html"], payload["spec"]
                ):
                    raise ValueError("Validation report differs from the immutable candidate")
                report_intent, report_key = store.prepare(cast(dict[str, JSON], report))
                pending.update(report_key=report_key, report_intent=report_intent)
                write_json(state_path, state)
            store.commit(pending["report_intent"], pending["report_key"])
            report = cast(dict[str, Any], store.read_json(pending["report_key"]))
            control.guard()
            decision = decide(report, pending["number"], args.repairs)
            attempt = {
                "number": pending["number"],
                "artifact_key": pending["artifact_key"],
                "report_key": pending["report_key"],
                "artifact": report["artifact"],
                "outcome": decision.outcome,
                "action": decision.action,
                "reason": decision.reason,
                "completed_at": time.time(),
                "validation": pending["validation"],
                "validation_runs": pending["validation_runs"],
            }
            outcome = decision.outcome
            if decision.action == "repair":
                previous = attempts[-1].get("failure_fingerprint") if attempts else None
                route = repair_route(report, list(payload["files"]), previous)
                attempt.update(
                    repair_strategy=route.strategy,
                    repair_files=list(route.files),
                    failure_fingerprint=route.fingerprint,
                )
            attempts.append(attempt)
            state["pending"] = None
            write_json(state_path, state)
        if attempts and attempts[-1].get("artifact_key"):
            key = attempts[-1]["artifact_key"]
            final = {**store.read_json(key), "artifact_key": key}
            outcome = attempts[-1]["outcome"]
    except Exception as exc:
        # Persist categories without provider stderr, prompt dumps, or raw reasoning.
        failure = {
            "number": len(attempts) + 1,
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "reason": str(exc)[:500]
            if isinstance(exc, (GenerationStopped, ValueError))
            else "Provider/infrastructure call failed; no blind replay",
        }
        pending = state.get("pending")
        if pending is not None:
            failure["artifact_key"] = pending["artifact_key"]
            failure["validation_runs"] = pending["validation_runs"]
        attempts.append(failure)
        outcome = "failed"
    finally:
        timer.cancel()
    metrics = journal.operation_metrics()
    metrics["attempted_provider_operations_this_session"] = (
        metrics["attempted_provider_operations"] - prior_metrics["attempted_provider_operations"]
    )
    metrics["reused_response_reads_this_session"] = (
        metrics["reused_response_reads"] - prior_metrics["reused_response_reads"]
    )
    record = {
        "case_id": case["id"],
        "kind": "revision" if base else "generation",
        "mode": args.mode,
        "provider": args.provider,
        "model": args.model,
        "live": metrics["attempted_provider_operations"] > 0,
        "provider_operations": metrics,
        "provider_operations_scope": (
            "Local provider attempts and reported request receipts; start markers do not prove "
            "remote acceptance or payment. Bare reserved intents remain dispatch-uncertain. "
            "Legacy new_provider_calls/provider_calls_this_session count reported requests only."
        ),
        "new_provider_calls": control.usage["calls"],
        "provider_calls_this_session": control.usage["calls"] - prior_calls,
        "resumed_invocations": resumed,
        "outcome": outcome,
        "duration_seconds": round(max(0, time.time() - state["started_at"]), 3),
        "started_at": state["started_at"],
        "expires_at": state["expires_at"],
        "attempts": attempts,
        "accounting": control.snapshot(),
        "final_artifact_key": final["artifact_key"] if final else None,
        "rubric": case["rubric"],
        "human_review": "pending",
        "webview": "unknown-host",
        "request_sha256": request_sha,
    }
    write_json(result_path, record)
    print(
        json.dumps(
            {key: record[key] for key in ("case_id", "kind", "mode", "outcome", "duration_seconds")}
        ),
        flush=True,
    )
    return {"record": record, "candidate": final if outcome == "passed" else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prompt2play evaluate")
    parser.add_argument("--suite", type=Path, default=SUITE_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=("single_author", "four_author"), default="single_author")
    parser.add_argument("--provider", choices=("codex", "openai"), default="codex")
    parser.add_argument("--model", required=True)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--image", default="prompt2play-validator:local")
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--repairs", type=int, default=2)
    parser.add_argument("--deadline", type=float, default=600)
    parser.add_argument("--call-timeout", type=float, default=240)
    parser.add_argument("--tokens", type=int, default=180_000)
    parser.add_argument("--plan-tokens", type=int, default=6000)
    parser.add_argument("--code-tokens", type=int, default=10_000)
    parser.add_argument("--validation-timeout", type=float, default=90)
    parser.add_argument("--no-revisions", action="store_true")
    args = parser.parse_args(argv)
    if args.runs < 1 or not 0 <= args.repairs <= 2 or args.tokens <= 0 or args.deadline <= 0:
        raise ValueError("Evaluation requires positive limits and at most two extra candidates")
    args.output = (
        args.output
        or Path(".prompt2play/evaluations")
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        / args.mode
    ).resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    cases = [case for case in suite["cases"] if not args.cases or case["id"] in args.cases]
    if not cases or (args.cases and set(args.cases) - {case["id"] for case in cases}):
        raise ValueError("Unknown evaluation case")
    protocol = {
        "schema_version": 1,
        "suite_sha256": hashlib.sha256(stable(suite).encode()).hexdigest(),
        "mode": args.mode,
        "provider": args.provider,
        "model": args.model,
        "runs": args.runs,
        "max_extra_candidates": args.repairs,
        "token_limit": args.tokens,
        "deadline_seconds": args.deadline,
        "plan_output_tokens": args.plan_tokens,
        "code_output_tokens": args.code_tokens,
        "cases": [case["id"] for case in cases],
        "revisions_enabled": not args.no_revisions,
        "validator_image": args.image,
        "validation_timeout_seconds": args.validation_timeout,
        "provider_call_timeout_seconds": args.call_timeout,
        "scope": "Live generation harness + immutable CAS + isolated validator; coordinator HTTP measured separately",
    }
    from prompt2play.generation.runtime import runtime_digest

    protocol["runtime_sha256"] = runtime_digest()
    inputs = list((PACKAGE_ROOT / "generation").glob("*.py"))
    inputs += list((PACKAGE_ROOT / "contracts").glob("*.py"))
    inputs += list((PACKAGE_ROOT / "validation").glob("*.py"))
    inputs += list((PACKAGE_ROOT / "legacy" / "validator").glob("*.py"))
    inputs += list((PACKAGE_ROOT / "legacy" / "validator").glob("*.mjs"))
    inputs += list((RESOURCE_ROOT / "legacy" / "prompts").glob("*.txt"))
    inputs += list((PACKAGE_ROOT / "contracts" / "schemas").glob("*.json"))
    inputs += list((RESOURCE_ROOT / "knowledge").glob("*.json"))
    inputs += [
        Path(__file__),
        PACKAGE_ROOT / "legacy" / "worker" / "providers.py",
        PACKAGE_ROOT / "application" / "policy.py",
    ]
    protocol["source_sha256"] = {
        path.relative_to(PACKAGE_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(inputs)
    }
    protocol_path = args.output / "protocol.json"
    if protocol_path.exists() and json.loads(protocol_path.read_text()) != protocol:
        raise ValueError("Protocol differs from the existing run; choose a new output directory")
    if not protocol_path.exists():
        write_json(protocol_path, protocol)
    records = []
    for case in cases:
        first_success = None
        for run in range(1, args.runs + 1):
            result = run_case(case, args.output / f"{case['id']}-{run}", args)
            records.append(result["record"])
            first_success = first_success or result["candidate"]
        if not args.no_revisions and first_success:
            records.append(
                run_case(case, args.output / f"{case['id']}-revision", args, base=first_success)[
                    "record"
                ]
            )
    generations = [record for record in records if record["kind"] == "generation"]
    revisions = [record for record in records if record["kind"] == "revision"]
    report = {
        **protocol,
        "results": records,
        "generations": len(generations),
        "playable": sum(record["outcome"] == "passed" for record in generations),
        "revisions": len(revisions),
        "passed_revisions": sum(record["outcome"] == "passed" for record in revisions),
        "limitations": [
            "Small sample does not establish arbitrary-genre reliability",
            "Human rubric review pending",
            "Contest WebView host unknown",
            "Codex output target is a reservation, not a CLI-enforced token cap",
        ],
    }
    if not (args.output / "report.json").exists():
        write_json(args.output / "report.json", report)
    return 0 if report["playable"] == len(generations) else 1
