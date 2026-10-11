"""Measurement bookkeeping uses fake generation; it never counts fixtures as live evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from prompt2play import evaluation
from prompt2play.adapters.artifacts.store import ArtifactStore
from prompt2play.generation import CandidateSubmission
from prompt2play.generation.gateway import ProviderGateway
from prompt2play.generation.workspace import GenerationControl
from prompt2play.legacy.validator.evidence import artifact_manifest
from prompt2play.legacy.worker.core import ProviderError, Reply
from prompt2play.paths import PACKAGE_ROOT
from prompt2play.validation import REQUIRED_CHECKS

manifest = cast(Callable[..., dict[str, Any]], artifact_manifest)


def config(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        output=tmp_path,
        deadline=10,
        tokens=100_000,
        provider="codex",
        model="test-double",
        call_timeout=5,
        codex="fixture",
        mode="single_author",
        repairs=2,
        plan_tokens=100,
        code_tokens=100,
        image="fixture",
        validation_timeout=1,
    )


def authored_case() -> dict[str, Any]:
    return {
        "id": "fixture",
        "prompt": "Authored fixture, no model call",
        "revision": "Change color",
        "rubric": ["Test bookkeeping only"],
    }


@pytest.mark.parametrize("first_outcome", ["failed", "unverified"])
def test_failed_candidates_are_committed_and_only_defects_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_outcome: str
) -> None:
    submitted: list[CandidateSubmission] = []

    class FakeGateway:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def preflight(self) -> None:
            pass

    class FakeHarness:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def attempt(self, *args: Any) -> CandidateSubmission:
            candidate = CandidateSubmission(
                {"game.js": f"fixture-{len(submitted)}"},
                "<!-- never executed -->",
                {},
                {},
                {"scope": "test-double"},
                dict(evaluation.EMPTY_USAGE),
                "Fixture",
                "fixture",
            )
            submitted.append(candidate)
            return candidate

    class FakeValidator:
        def __init__(self, *_args: Any) -> None:
            pass

        def validate(
            self,
            files: dict[str, str],
            html: str,
            spec: dict[str, Any],
            *_args: Any,
            **_kwargs: Any,
        ) -> dict[str, Any]:
            status = first_outcome if len(submitted) == 1 else "passed"
            artifact = manifest(files, html, spec)
            checks = [
                {"name": name, "status": "passed", "artifact_sha256": artifact["html_sha256"]}
                for name in REQUIRED_CHECKS
            ]
            if status != "passed":
                checks[0]["status"] = "failed" if status == "failed" else "skipped"
            return {
                "schema_version": 2,
                "artifact": artifact,
                "status": status,
                "checks": checks,
                "errors": ["authored defect"] if status == "failed" else [],
                "scope": {"isolated": True, "real_input": True},
                "suite_sha256": "fixture",
                "validator_image_sha256": "fixture",
            }

    monkeypatch.setattr(evaluation, "ProviderGateway", FakeGateway)
    monkeypatch.setattr(evaluation, "GenerationHarness", FakeHarness)
    monkeypatch.setattr(evaluation, "IsolatedValidator", FakeValidator)
    result = evaluation.run_case(authored_case(), tmp_path / "run", config(tmp_path))
    record = result["record"]
    assert len(record["attempts"]) == (2 if first_outcome == "failed" else 1)
    assert record["outcome"] == ("passed" if first_outcome == "failed" else "unverified")
    store = ArtifactStore(tmp_path / "objects")
    for attempt in record["attempts"]:
        assert store.read_json(attempt["artifact_key"])["html"] == "<!-- never executed -->"
    assert (tmp_path / "run" / "result.json").is_file()


def test_provider_failure_is_retained_without_paid_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RejectedGateway:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def preflight(self) -> None:
            raise RuntimeError("secret error details must not be logged")

    monkeypatch.setattr(evaluation, "ProviderGateway", RejectedGateway)
    result = evaluation.run_case(authored_case(), tmp_path / "failure", config(tmp_path))
    assert result["candidate"] is None and len(result["record"]["attempts"]) == 1
    assert "secret error" not in (tmp_path / "failure" / "result.json").read_text()


def test_suite_denominator_keeps_failures_and_only_successful_bases_revise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps(
            {"cases": [{**authored_case(), "id": "ok"}, {**authored_case(), "id": "failed"}]}
        )
    )
    calls: list[tuple[str, bool]] = []

    def fake_run(
        case: dict[str, Any],
        folder: Path,
        args: argparse.Namespace,
        *,
        base: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        calls.append((case["id"], base is not None))
        return {
            "record": {
                "kind": "revision" if base else "generation",
                "outcome": "passed" if case["id"] == "ok" else "failed",
            },
            "candidate": {"source": "test-double"} if case["id"] == "ok" else None,
        }

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    output = tmp_path / "results"
    assert (
        evaluation.main(["--suite", str(suite), "--output", str(output), "--model", "fixture"]) == 1
    )
    report = json.loads((output / "report.json").read_text())
    assert (report["generations"], report["playable"], report["revisions"]) == (4, 2, 1)
    assert calls.count(("failed", True)) == 0
    assert report["scope"].startswith("Live generation harness")


@pytest.mark.parametrize(
    "arguments", [["--runs", "0"], ["--repairs", "3"], ["--tokens", "0"], ["--deadline", "0"]]
)
def test_evaluation_rejects_unbounded_or_invalid_protocol(arguments: list[str]) -> None:
    with pytest.raises(ValueError):
        evaluation.main(["--model", "fixture", *arguments])


class DurableFixture:
    """Uses the real paid-call journal; replies and browser observations are authored."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.provider_calls = 0
        self.harness_calls: list[str] = []
        self.validator_paths: list[Path] = []
        self.validation_interrupt = False
        self.repair_interrupt = False
        self.first_fails = False
        self.provider_error: BaseException | None = None
        owner = self

        class Provider:
            def preflight(self) -> None:
                pass

            def generate(self, *_args: Any, **_kwargs: Any) -> Any:
                owner.provider_calls += 1
                if owner.provider_error:
                    raise owner.provider_error
                usage = {
                    **evaluation.EMPTY_USAGE,
                    "input_tokens": 3,
                    "output_tokens": 4,
                    "total_tokens": 7,
                    "calls": 1,
                }
                return cast(Any, Reply)({"fixture": "structured reply"}, usage)

        def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
            actual = ProviderGateway(*args, **kwargs)
            actual.provider = Provider()
            return actual

        class Harness:
            def __init__(self, **_kwargs: Any) -> None:
                pass

            def attempt(
                self, request: Any, gateway: ProviderGateway, control: Any
            ) -> CandidateSubmission:
                owner.harness_calls.append(request.attempt_id)
                gateway.generate(
                    "Authored " + request.attempt_id, {}, "draft", control, max_output=10
                )
                if owner.repair_interrupt and request.attempt_id.endswith(":2"):
                    owner.repair_interrupt = False
                    raise KeyboardInterrupt("Authored process interruption after paid reply")
                return CandidateSubmission(
                    {"game.js": "// " + request.attempt_id},
                    "<!-- never executed -->",
                    {},
                    {},
                    {"scope": "test-double"},
                    dict(control.usage),
                    "Fixture",
                    "fixture",
                )

        class Validator:
            def __init__(self, *_args: Any) -> None:
                pass

            def validate(
                self,
                files: dict[str, str],
                html: str,
                spec: dict[str, Any],
                _cancel: Any,
                evidence_dir: Path,
                **_kwargs: Any,
            ) -> dict[str, Any]:
                owner.validator_paths.append(evidence_dir)
                (evidence_dir / "fixture-evidence.txt").write_text(
                    "Authored observation " + str(len(owner.validator_paths))
                )
                if owner.validation_interrupt:
                    owner.validation_interrupt = False
                    raise KeyboardInterrupt("Authored validator interruption")
                artifact = manifest(files, html, spec)
                checks = [
                    {"name": name, "status": "passed", "artifact_sha256": artifact["html_sha256"]}
                    for name in REQUIRED_CHECKS
                ]
                failed = owner.first_fails and len(owner.validator_paths) == 1
                if failed:
                    checks[0]["status"] = "failed"
                return {
                    "schema_version": 2,
                    "artifact": artifact,
                    "status": "failed" if failed else "passed",
                    "checks": checks,
                    "errors": [],
                    "scope": {"isolated": True, "real_input": True},
                    "suite_sha256": "fixture",
                    "validator_image_sha256": "fixture",
                }

        monkeypatch.setattr(evaluation, "ProviderGateway", gateway)
        monkeypatch.setattr(evaluation, "GenerationHarness", Harness)
        monkeypatch.setattr(evaluation, "IsolatedValidator", Validator)


def test_interrupted_validation_resumes_committed_candidate_and_preserves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = DurableFixture(monkeypatch)
    fixture.validation_interrupt = True
    args, folder = config(tmp_path), tmp_path / "case"
    with pytest.raises(KeyboardInterrupt):
        evaluation.run_case(authored_case(), folder, args)
    original_state = json.loads((folder / "state.json").read_text())
    old_evidence = fixture.validator_paths[0] / "fixture-evidence.txt"
    old_bytes = old_evidence.read_bytes()
    result = evaluation.run_case(authored_case(), folder, args)["record"]
    assert result["outcome"] == "passed" and fixture.provider_calls == 1
    assert fixture.harness_calls == ["case:1"]
    assert result["accounting"]["usage"]["total_tokens"] == 7
    assert result["live"] and result["new_provider_calls"] == 1
    assert result["provider_calls_this_session"] == 0
    assert result["attempts"][0]["artifact_key"] == original_state["pending"]["artifact_key"]
    assert len(result["attempts"][0]["validation_runs"]) == 2
    assert fixture.validator_paths[0] != fixture.validator_paths[1]
    assert old_evidence.read_bytes() == old_bytes


def test_resume_keeps_original_deadline_and_stops_before_provider_or_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = DurableFixture(monkeypatch)
    fixture.validation_interrupt = True
    current = [1000.0]
    monkeypatch.setattr(time, "time", lambda: current[0])
    args, folder = config(tmp_path), tmp_path / "case"
    with pytest.raises(KeyboardInterrupt):
        evaluation.run_case(authored_case(), folder, args)
    current[0] = 1011.0
    result = evaluation.run_case(authored_case(), folder, args)["record"]
    assert result["outcome"] == "failed" and result["expires_at"] == 1010.0
    assert result["duration_seconds"] == 11.0
    assert fixture.provider_calls == 1 and len(fixture.validator_paths) == 1
    assert result["accounting"]["usage"]["total_tokens"] == 7


def test_interrupted_repair_reconstructs_same_attempt_and_reuses_paid_reply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = DurableFixture(monkeypatch)
    fixture.first_fails = fixture.repair_interrupt = True
    args, folder = config(tmp_path), tmp_path / "case"
    with pytest.raises(KeyboardInterrupt):
        evaluation.run_case(authored_case(), folder, args)
    checkpoint = json.loads((folder / "state.json").read_text())
    first_report_path = args.output / checkpoint["attempts"][0]["validation"]
    original_report = first_report_path.read_bytes()
    result = evaluation.run_case(authored_case(), folder, args)["record"]
    assert result["outcome"] == "passed" and fixture.provider_calls == 2
    assert fixture.harness_calls == ["case:1", "case:2", "case:2"]
    assert [attempt["number"] for attempt in result["attempts"]] == [1, 2]
    assert result["accounting"]["usage"]["total_tokens"] == 14
    assert result["provider_calls_this_session"] == 0
    assert result["provider_operations"]["attempted_provider_operations"] == 2
    assert result["provider_operations"]["attempted_provider_operations_this_session"] == 0
    assert result["provider_operations"]["reused_response_reads_this_session"] == 1
    assert first_report_path.read_bytes() == original_report


def test_resume_recovers_report_commit_without_rerunning_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = DurableFixture(monkeypatch)
    args, folder = config(tmp_path), tmp_path / "case"
    original_write = evaluation.write_json
    interrupted = [False]

    def crash_after_report_checkpoint(path: Path, value: Any) -> None:
        original_write(path, value)
        pending = value.get("pending") or {}
        if path.name == "state.json" and pending.get("report_key") and not interrupted[0]:
            interrupted[0] = True
            raise KeyboardInterrupt("Authored report commit interruption")

    monkeypatch.setattr(evaluation, "write_json", crash_after_report_checkpoint)
    with pytest.raises(KeyboardInterrupt):
        evaluation.run_case(authored_case(), folder, args)
    monkeypatch.setattr(evaluation, "write_json", original_write)
    result = evaluation.run_case(authored_case(), folder, args)["record"]
    assert result["outcome"] == "passed" and fixture.provider_calls == 1
    assert len(fixture.validator_paths) == 1


def test_completed_and_unfinished_evaluation_reject_changed_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = DurableFixture(monkeypatch)
    args, folder = config(tmp_path), tmp_path / "case"
    fixture.validation_interrupt = True
    with pytest.raises(KeyboardInterrupt):
        evaluation.run_case(authored_case(), folder, args)
    args.tokens += 1
    with pytest.raises(ValueError, match="differs"):
        evaluation.run_case(authored_case(), folder, args)
    args.tokens -= 1
    evaluation.run_case(authored_case(), folder, args)
    args.validation_timeout += 1
    with pytest.raises(ValueError, match="immutable"):
        evaluation.run_case(authored_case(), folder, args)


def test_evaluation_case_lock_rejects_concurrent_runner(tmp_path: Path) -> None:
    import fcntl

    folder = tmp_path / "case"
    folder.mkdir()
    with (folder / "run.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already running"):
            evaluation.run_case(authored_case(), folder, config(tmp_path))


def test_unknown_usage_timeout_is_a_live_local_attempt_and_is_never_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = DurableFixture(monkeypatch)
    fixture.provider_error = cast(Any, ProviderError)("Authored timeout with no usage receipt")
    args, folder = config(tmp_path), tmp_path / "case"
    result = evaluation.run_case(authored_case(), folder, args)["record"]
    assert result["outcome"] == "failed" and result["live"]
    assert fixture.provider_calls == 1
    assert result["new_provider_calls"] == result["provider_calls_this_session"] == 0
    assert result["accounting"]["uncertain_tokens"] > 0
    metrics = result["provider_operations"]
    assert metrics["attempted_provider_operations"] == 1
    assert metrics["attempted_provider_operations_this_session"] == 1
    assert metrics["known_reported_requests"] == 0
    assert metrics["unknown_usage_operations"] == 1
    assert metrics["dispatch_uncertain_reservations"] == 0
    immutable = (folder / "result.json").read_bytes()
    assert evaluation.run_case(authored_case(), folder, args)["record"] == result
    assert fixture.provider_calls == 1 and (folder / "result.json").read_bytes() == immutable


def test_reserved_intent_without_dispatch_marker_is_uncertain_and_not_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = DurableFixture(monkeypatch)
    original = GenerationControl.reserve

    def interrupt_before_reserve(_self: GenerationControl, _key: str, _amount: int) -> None:
        raise KeyboardInterrupt("Authored crash after durable intent, before provider dispatch")

    monkeypatch.setattr(GenerationControl, "reserve", interrupt_before_reserve)
    args, folder = config(tmp_path), tmp_path / "case"
    with pytest.raises(KeyboardInterrupt):
        evaluation.run_case(authored_case(), folder, args)
    monkeypatch.setattr(GenerationControl, "reserve", original)
    result = evaluation.run_case(authored_case(), folder, args)["record"]
    assert fixture.provider_calls == 0 and result["live"] is False
    assert result["accounting"]["uncertain_tokens"] > 0
    assert result["provider_operations"]["attempted_provider_operations"] == 0
    assert result["provider_operations"]["dispatch_uncertain_reservations"] == 1
    assert result["provider_operations"]["unknown_usage_operations"] == 0


def test_started_unsettled_attempt_preserves_uncertainty_without_replay_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = DurableFixture(monkeypatch)
    fixture.provider_error = KeyboardInterrupt("Authored process interruption during provider call")
    args, folder = config(tmp_path), tmp_path / "case"
    with pytest.raises(KeyboardInterrupt):
        evaluation.run_case(authored_case(), folder, args)
    result = evaluation.run_case(authored_case(), folder, args)["record"]
    assert fixture.provider_calls == 1 and result["live"]
    metrics = result["provider_operations"]
    assert metrics["attempted_provider_operations"] == 1
    assert metrics["attempted_provider_operations_this_session"] == 0
    assert metrics["dispatch_uncertain_reservations"] == metrics["unknown_usage_operations"] == 1
    assert metrics["known_reported_requests"] == 0
    assert result["accounting"]["uncertain_tokens"] > 0


def test_helper_only_source_policy_change_rejects_reusing_frozen_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "package"
    helper = package / "contracts/source_policy.py"
    paths = [
        "contracts/source_policy.py",
        "evaluation.py",
        "legacy/worker/providers.py",
        "application/policy.py",
    ]
    for relative in paths:
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PACKAGE_ROOT / relative).read_bytes())
    monkeypatch.setattr(evaluation, "PACKAGE_ROOT", package)
    monkeypatch.setattr(evaluation, "RESOURCE_ROOT", package / "resources")
    monkeypatch.setattr(evaluation, "__file__", str(package / "evaluation.py"))
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps({"cases": [authored_case()]}))
    calls: list[str] = []

    def fake_run(case: dict[str, Any], _folder: Path, _args: argparse.Namespace) -> dict[str, Any]:
        calls.append(case["id"])
        return {"record": {"kind": "generation", "outcome": "failed"}, "candidate": None}

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    output = tmp_path / "results"
    arguments = [
        "--suite",
        str(suite),
        "--output",
        str(output),
        "--model",
        "fixture",
        "--runs",
        "1",
        "--no-revisions",
    ]
    assert evaluation.main(arguments) == 1
    protocol_path = output / "protocol.json"
    original = protocol_path.read_bytes()
    helper.write_text(helper.read_text() + "\n# Authored helper-only policy change\n")
    recorded_hash = json.loads(original)["source_sha256"]["contracts/source_policy.py"]
    assert recorded_hash != hashlib.sha256(helper.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Protocol differs"):
        evaluation.main(arguments)
    assert calls == [authored_case()["id"]]
    assert protocol_path.read_bytes() == original
