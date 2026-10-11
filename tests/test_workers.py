"""Paid-call fencing and restart accounting, with explicitly fake HTTP transports."""

from __future__ import annotations

import base64
import hashlib
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from prompt2play.evaluation import EMPTY_USAGE, FileJournal
from prompt2play.generation import GenerationControl
from prompt2play.generation.workspace import GenerationStopped
from prompt2play.workers.runner import (
    Coordinator,
    LeaseRejected,
    RemoteJournal,
    StageLease,
    evidence_payload,
    generation_request,
)


@pytest.fixture(autouse=True)
def fake_model_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    # Worker tests must not inspect the developer's actual Codex account.
    monkeypatch.setattr(
        "prompt2play.workers.model_catalog.discover_codex_models",
        lambda _executable: [{"id": "fixture-model", "label": "Fixture", "is_default": True}],
    )


def claim() -> dict[str, Any]:
    return {
        "lease_token": "authored-fixture-token",
        "lease_seconds": 120,
        "job": {
            "id": "authored-job",
            "stage_fence": 3,
            "stage": "plan",
            "kind": "generate",
            "prompt": "Authored transport fixture",
            "usage": dict(EMPTY_USAGE),
        },
        "base_version": None,
        "candidate": None,
    }


def test_expired_run_rejects_writes_despite_fresh_stage_lease() -> None:
    sent: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    client = httpx.Client(base_url="http://localhost/", transport=httpx.MockTransport(serve))
    values = dict(claim(), remaining_seconds=0)
    lease = StageLease(
        Coordinator("http://localhost", "fixture", client=client), values, threading.Event()
    )
    assert lease.remaining(600) == 0
    with pytest.raises(LeaseRejected, match="acknowledged"):
        lease.write("reserve")
    assert not sent
    assert lease.cancel.is_set()
    client.close()


@pytest.mark.parametrize(
    "failure,expected",
    [
        (GenerationStopped("authored provider failure"), 1),
        (LeaseRejected("authored expired lease"), 2),
    ],
)
def test_once_worker_reports_failed_claimed_stage_to_caller(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    from prompt2play.workers import runner

    paths: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=claim() if request.url.path.endswith("claim/") else {})

    def fail_stage(_lease: StageLease, _args: Any) -> None:
        raise failure

    client = httpx.Client(base_url="http://localhost/", transport=httpx.MockTransport(serve))
    coordinator = Coordinator("http://localhost", "fixture", client=client)
    monkeypatch.setattr(runner, "Coordinator", lambda *_args: coordinator)
    monkeypatch.setattr(runner, "generate_stage", fail_stage)
    assert runner.main(["--role", "generator", "--once"]) == expected
    assert ("/api/worker/jobs/authored-job/fail/" in paths) is (expected == 1)
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    final = records[-1]
    assert final["event"] == ("stage_failed" if expected == 1 else "stage_lease_rejected")
    assert final["job_id"] == "authored-job" and final["stage_fence"] == 3
    assert final["exceptions"][0]["message"] == str(failure)
    assert "authored-fixture-token" not in json.dumps(records)


@pytest.mark.parametrize(
    "role,provider", [("validator", "codex"), ("generator", "codex"), ("generator", "openai")]
)
def test_worker_claim_without_model_matches_api_contract(
    monkeypatch: pytest.MonkeyPatch, role: str, provider: str
) -> None:
    import json

    from prompt2play.adapters.django.forge.serializers import ClaimSerializer
    from prompt2play.workers import runner

    requests: list[dict[str, Any]] = []

    def serve(request: httpx.Request) -> httpx.Response:
        values = json.loads(request.content)
        serializer = ClaimSerializer(data=values)
        assert serializer.is_valid(), serializer.errors
        requests.append(values)
        return httpx.Response(200, json={"job": None})

    client = httpx.Client(base_url="http://localhost/", transport=httpx.MockTransport(serve))
    coordinator = Coordinator("http://localhost", "fixture", client=client)
    monkeypatch.setattr(runner, "Coordinator", lambda *_args: coordinator)
    assert runner.main(["--role", role, "--provider", provider, "--once"]) == 0
    assert len(requests) == 1


def test_idle_worker_recovers_transport_failure_without_replaying_stage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    from prompt2play.workers import runner

    calls = 0

    def serve(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/worker/claim/"
        if calls == 1:
            raise httpx.ReadError("authored transient reset", request=request)
        # Revocation after reconnect must exit instead of retrying forever.
        return httpx.Response(403, json={"error": "revoked"})

    client = httpx.Client(base_url="http://localhost/", transport=httpx.MockTransport(serve))
    coordinator = Coordinator("http://localhost", "fixture", client=client)
    monkeypatch.setattr(runner, "Coordinator", lambda *_args: coordinator)
    assert runner.main(["--role", "validator", "--poll", "0.001"]) == 2
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert calls == 2
    assert [row["event"] for row in records] == [
        "worker_started",
        "claim_connection_failed",
        "worker_rejected",
    ]
    assert records[1]["exceptions"][0]["message"] == "authored transient reset"


@pytest.mark.parametrize("status", [401, 403, 409])
def test_auth_and_fence_rejection_stop_writes(status: int) -> None:
    client = httpx.Client(
        base_url="http://localhost/",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"error": "authored rejection"})
        ),
    )
    cancel = threading.Event()
    lease = StageLease(Coordinator("http://localhost", "fixture", client=client), claim(), cancel)
    with pytest.raises(LeaseRejected):
        lease.write("reserve")
    assert cancel.is_set()
    with pytest.raises(LeaseRejected, match="acknowledged"):
        lease.write("candidates")
    client.close()


@pytest.mark.parametrize(
    "server", ["http://remote.example", "file:///etc/passwd", "https://user:pass@example.com"]
)
def test_coordinator_rejects_unsecured_or_credential_urls(server: str) -> None:
    with pytest.raises(ValueError):
        Coordinator(server, "fixture")


def test_remote_journal_reuses_only_completed_responses_and_sends_fence() -> None:
    requests: list[dict[str, Any]] = []

    def serve(request: httpx.Request) -> httpx.Response:
        import json

        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "i",
                "state": "completed",
                "stage_fence": 2,
                "response": {"data": {"source": "fixture"}, "usage": EMPTY_USAGE},
            },
        )

    client = httpx.Client(base_url="http://localhost/", transport=httpx.MockTransport(serve))
    lease = StageLease(
        Coordinator("http://localhost", "fixture", client=client), claim(), threading.Event()
    )
    journal = RemoteJournal(lease, GenerationControl.bounded())
    response = journal.reserve("author:hash", 100, "author", "a" * 64)
    assert response and response["data"] == {"source": "fixture"}
    assert requests[0]["stage_fence"] == 3
    assert requests[0]["lease_token"] == "authored-fixture-token"
    client.close()


@pytest.mark.parametrize("state,fence", [("ambiguous", 3), ("reserved", 2)])
def test_old_or_ambiguous_invocation_never_replays(state: str, fence: int) -> None:
    client = httpx.Client(
        base_url="http://localhost/",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"id": "i", "state": state, "stage_fence": fence}
            )
        ),
    )
    lease = StageLease(
        Coordinator("http://localhost", "fixture", client=client), claim(), threading.Event()
    )
    with pytest.raises(GenerationStopped, match="Ambiguous"):
        RemoteJournal(lease, GenerationControl.bounded()).reserve("key", 100, "author", "a" * 64)
    client.close()


def test_disk_journal_survives_restart_without_double_paid_call(tmp_path: Path) -> None:
    path = tmp_path / "journal.json"
    journal = FileJournal(path)
    assert journal.reserve("completed", 100, "author", "a" * 64) is None
    usage = {**EMPTY_USAGE, "input_tokens": 10, "output_tokens": 20, "total_tokens": 30, "calls": 1}
    journal.settle("completed", data={"source": "fixture"}, usage=usage, status="completed")
    journal.reserve("interrupted", 80, "author", "b" * 64)
    resumed = FileJournal(path)
    assert resumed.reserve("completed", 100, "author", "a" * 64) == {
        "data": {"source": "fixture"},
        "usage": usage,
    }
    with pytest.raises(GenerationStopped, match="Uncertain"):
        resumed.reserve("interrupted", 80, "author", "b" * 64)
    assert resumed.accounting() == (usage, 80)


def test_repair_request_obeys_application_strategy_and_base_plan() -> None:
    values = claim()
    values["job"].update(
        stage="repair", attempts=1, checkpoint={"strategy": "regenerate", "files": ["game.js"]}
    )
    values["candidate"] = {
        "files": {"game.js": "broken fixture"},
        "spec": {"title": "Fixture"},
        "plan": {"schema_version": 1},
        "validation": {"checks": [{"status": "failed", "name": "input"}]},
    }
    request = generation_request(values, "single_author")
    assert request.kind == "repair" and request.replan
    assert request.base_files == {} and request.base_plan == {"schema_version": 1}
    assert request.findings == [{"status": "failed", "name": "input"}]


def test_evidence_upload_binds_exact_bytes_and_rejects_escape(tmp_path: Path) -> None:
    data = b"authored evidence fixture"
    (tmp_path / "shot.png").write_bytes(data)
    report = {
        "evidence_files": [
            {"path": "shot.png", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        ]
    }
    assert base64.b64decode(evidence_payload(report, tmp_path)["shot.png"]) == data
    (tmp_path / "shot.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="differs"):
        evidence_payload(report, tmp_path)
    report["evidence_files"][0]["path"] = "../escape.png"
    with pytest.raises(ValueError, match="escapes"):
        evidence_payload(report, tmp_path)
