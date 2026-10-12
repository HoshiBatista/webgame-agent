"""Real Django APIs and real harness, with explicitly scripted model replies.

These tests execute no generated JavaScript and establish no live-model or
browser performance result.
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from django.test import Client
from django.utils import timezone

from prompt2play.adapters.django.forge import services as donor_services
from prompt2play.adapters.django.forge.authentication import secret_hash as donor_hash
from prompt2play.adapters.django.forge.models import (
    Candidate,
    Job,
    ModelInvocation,
    Project,
    Runner,
    User,
)
from prompt2play.generation import GenerationControl, ProviderGateway
from prompt2play.generation.workspace import GenerationStopped
from prompt2play.legacy.worker.core import Reply
from prompt2play.paths import RESOURCE_ROOT
from prompt2play.workers import runner as worker

services: Any = donor_services
secret_hash: Any = donor_hash
pytestmark = pytest.mark.django_db
USAGE = {
    "input_tokens": 3,
    "cached_input_tokens": 0,
    "output_tokens": 4,
    "total_tokens": 7,
    "calls": 1,
}


def coordinator(token: str) -> worker.Coordinator:
    django_client = Client()

    def transport(request: httpx.Request) -> httpx.Response:
        response = django_client.post(
            request.url.path,
            request.content,
            content_type="application/json",
            HTTP_AUTHORIZATION=request.headers["Authorization"],
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"content-type": response.get("content-type", "application/json")},
        )

    client = httpx.Client(
        base_url="http://localhost/",
        headers={"Authorization": "Bearer " + token},
        transport=httpx.MockTransport(transport),
    )
    return worker.Coordinator("http://localhost", token, client=client)


@pytest.fixture
def prepared(settings: Any, tmp_path: Path) -> tuple[Any, worker.Coordinator, dict[str, Any]]:
    settings.ARTIFACT_ROOT = tmp_path / "artifacts"
    user = User.objects.create_user("worker-fixture", password="fixture-password")
    project = Project.objects.create(
        title="Worker fixture", prompt="fixture request", created_by=user
    )
    runner = Runner.objects.create(
        name="fixture runner", token_hash=secret_hash("worker-fixture-token")
    )
    job = services.create_job(
        project,
        user,
        {"kind": "generate", "prompt": "Fixture game", "provider": "codex", "model": "fixture"},
    )
    transport = coordinator("worker-fixture-token")
    claim = transport.post("api/worker/claim/", {"capabilities": {"providers": ["codex"]}})
    assert claim["job"]["id"] == str(job.pk)
    return runner, transport, claim


def replies() -> list[dict[str, Any]]:
    example = RESOURCE_ROOT / "runtime" / "examples" / "dom"
    return [
        {
            "game_spec": json.loads((example / "spec.json").read_text()),
            "build_plan": {
                **json.loads((example / "plan.json").read_text()),
                **json.loads((Path(__file__).parent / "fixtures/design-contract.json").read_text()),
            },
        },
        {
            "operations": [
                {
                    "op": "create",
                    "path": "game.js",
                    "content": (example / "game.js").read_text(),
                    "old": "",
                    "new": "",
                },
                {"op": "submit", "path": "", "content": "", "old": "", "new": ""},
            ],
            "summary": "Scripted worker fixture",
        },
        json.loads((Path(__file__).parent / "fixtures/visual-review-ready.json").read_text()),
    ]


class ScriptedProvider:
    def __init__(self, outputs: list[dict[str, Any]], cancel_job: str | None = None) -> None:
        self.outputs, self.cancel_job, self.calls = outputs, cancel_job, 0

    def preflight(self) -> None:
        pass

    def generate(self, *_args: Any, **_kwargs: Any) -> Any:
        self.calls += 1
        if self.cancel_job:
            services.cancel_job(self.cancel_job)
        return cast(Any, Reply)(self.outputs.pop(0), dict(USAGE))


def arguments() -> argparse.Namespace:
    return argparse.Namespace(
        deadline=30, model="fixture", call_timeout=10, codex="fixture", mode="single_author"
    )


def test_worker_harness_posts_exact_native_candidate_and_persists_usage(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, transport, claim = prepared
    provider = ScriptedProvider(replies())

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        configured = ProviderGateway(*args, **kwargs)
        configured.provider = provider
        return configured

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    lease = worker.StageLease(transport, claim, threading.Event())
    worker.generate_stage(lease, arguments())
    assert provider.calls == 3
    candidate = Candidate.objects.get()
    job = Job.objects.get(pk=claim["job"]["id"])
    assert candidate.committed and job.stage == "validate" and job.status == "queued"
    assert job.usage["total_tokens"] == 21 and job.usage["calls"] == 3
    assert ModelInvocation.objects.filter(state="completed").count() == 3
    transport.close()


def test_paid_call_returning_after_cancel_only_accounts_cost_and_never_source(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
) -> None:
    _, transport, claim = prepared
    lease = worker.StageLease(transport, claim, threading.Event())
    control = GenerationControl.bounded(cancel=lease.cancel, fence_check=lease.alive)
    configured = ProviderGateway("codex", "fixture", journal=worker.RemoteJournal(lease, control))
    provider = ScriptedProvider([{"answer": "must not be reused"}], claim["job"]["id"])
    configured.provider = provider
    with pytest.raises(worker.LeaseRejected):
        configured.generate("scripted paid fixture", {}, "draft", control)
    job = Job.objects.get(pk=claim["job"]["id"])
    invocation = ModelInvocation.objects.get()
    assert provider.calls == 1 and job.status == "cancelled"
    assert job.usage["total_tokens"] == 7 and invocation.actual_usage == USAGE
    assert not invocation.response_key and not Candidate.objects.exists()
    transport.close()


@pytest.mark.parametrize("settlement_received", [False, True])
def test_paid_reply_with_lost_settlement_receipt_keeps_exact_accounting(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    settlement_received: bool,
) -> None:
    _, transport, claim = prepared
    original_post = transport.post

    def lost_receipt(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if path.endswith("/settle/"):
            if settlement_received:
                original_post(path, payload)
            raise httpx.ReadTimeout("Authored missing settlement receipt")
        return original_post(path, payload)

    monkeypatch.setattr(transport, "post", lost_receipt)
    lease = worker.StageLease(transport, claim, threading.Event())
    control = GenerationControl.bounded(cancel=lease.cancel, fence_check=lease.alive)
    gateway = ProviderGateway("codex", "fixture", journal=worker.RemoteJournal(lease, control))
    provider = ScriptedProvider([{"answer": "authored paid reply"}])
    gateway.provider = provider
    with pytest.raises(httpx.ReadTimeout):
        gateway.generate("same paid fixture", {}, "draft", control)
    job = Job.objects.get(pk=claim["job"]["id"])
    invocation = ModelInvocation.objects.get()
    assert provider.calls == 1 and job.usage["total_tokens"] == 7
    assert invocation.actual_usage == USAGE
    assert invocation.state == ("completed" if settlement_received else "ambiguous")
    assert bool(invocation.response_key) == settlement_received
    original_post(
        f"api/worker/jobs/{job.pk}/account/",
        {"invocation_id": str(invocation.pk), "invocation_usage": USAGE},
    )
    job.refresh_from_db()
    assert job.usage["total_tokens"] == 7 and job.usage["calls"] == 1
    assert not Candidate.objects.exists()
    transport.close()


def test_worker_reclaimed_completed_response_reuses_without_double_charge(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
) -> None:
    _, transport, claim = prepared
    first_lease = worker.StageLease(transport, claim, threading.Event())
    first_control = GenerationControl.bounded(
        cancel=first_lease.cancel, fence_check=first_lease.alive
    )
    first_gateway = ProviderGateway(
        "codex", "fixture", journal=worker.RemoteJournal(first_lease, first_control)
    )
    first_provider = ScriptedProvider([{"structured": "cached fixture"}])
    first_gateway.provider = first_provider
    first_gateway.generate("same paid fixture", {}, "draft", first_control)
    Job.objects.filter(pk=claim["job"]["id"]).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    resumed = transport.post("api/worker/claim/", {"capabilities": {"providers": ["codex"]}})
    assert resumed["job"]["usage"]["total_tokens"] == 7
    second_lease = worker.StageLease(transport, resumed, threading.Event())
    second_control = GenerationControl.bounded(
        cancel=second_lease.cancel, fence_check=second_lease.alive, usage=resumed["job"]["usage"]
    )
    second_gateway = ProviderGateway(
        "codex", "fixture", journal=worker.RemoteJournal(second_lease, second_control)
    )
    second_provider = ScriptedProvider([])
    second_gateway.provider = second_provider
    reply = second_gateway.generate("same paid fixture", {}, "draft", second_control)
    assert reply.reused and reply.data == {"structured": "cached fixture"}
    assert second_provider.calls == 0 and second_control.usage["total_tokens"] == 7
    assert Job.objects.get(pk=claim["job"]["id"]).usage["total_tokens"] == 7
    transport.close()


@pytest.mark.parametrize("budget", ["0.01", "10.00"])
def test_usd_worker_uses_frozen_model_and_real_ledger_without_total_token_gate(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    budget: str,
) -> None:
    from decimal import Decimal

    from prompt2play.adapters.django.forge.representations import job_data
    from prompt2play.pricing import cost_bounds, snapshot

    _, transport, claim = prepared
    pricing = snapshot("gpt-6-astra", "codex")
    Job.objects.filter(pk=claim["job"]["id"]).update(
        model="gpt-6-astra", budget_usd=Decimal(budget), pricing=pricing, budget_tokens=1
    )
    claim["job"] = cast(Any, job_data)(Job.objects.get(pk=claim["job"]["id"]))
    provider = ScriptedProvider(replies())

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        configured = ProviderGateway(*args, **kwargs)
        assert configured.model == "gpt-6-astra"
        configured.provider = provider
        return configured

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    lease = worker.StageLease(transport, claim, threading.Event())
    if budget == "0.01":
        with pytest.raises(GenerationStopped, match="бюджета"):
            worker.generate_stage(lease, arguments())
        assert lease.alive()  # the worker can persist the terminal budget reason
        assert provider.calls == 0 and not ModelInvocation.objects.exists()
    else:
        worker.generate_stage(lease, arguments())
        job = Job.objects.get(pk=claim["job"]["id"])
        assert provider.calls == 3 and job.usage["total_tokens"] == 21
        lower, upper = cost_bounds(USAGE, pricing)
        assert job.cost_nano == lower * 3 and job.cost_upper_nano == upper * 3
        assert cast(Any, job_data)(job)["cost"]["reserved_usd"] == "0.000000000"
        assert Candidate.objects.get().committed
    transport.close()


def test_usd_restart_replays_saved_responses_without_repricing_or_paid_calls(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from prompt2play.adapters.django.forge.representations import job_data
    from prompt2play.pricing import snapshot

    _, transport, claim = prepared
    Job.objects.filter(pk=claim["job"]["id"]).update(
        model="gpt-6-astra",
        budget_usd=Decimal("10"),
        pricing=snapshot("gpt-6-astra", "codex"),
        budget_tokens=1,
    )
    claim["job"] = cast(Any, job_data)(Job.objects.get(pk=claim["job"]["id"]))
    provider = ScriptedProvider(replies())

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        configured = ProviderGateway(*args, **kwargs)
        configured.provider = provider
        return configured

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    original = transport.post

    def unavailable(path: str, values: dict[str, Any]) -> dict[str, Any]:
        if path.endswith("/candidates/"):
            raise httpx.ReadTimeout("Authored failure before candidate delivery")
        return original(path, values)

    monkeypatch.setattr(transport, "post", unavailable)
    with pytest.raises(httpx.ReadTimeout):
        worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    before = Job.objects.get(pk=claim["job"]["id"])
    assert provider.calls == 3 and not Candidate.objects.exists()
    monkeypatch.setattr(transport, "post", original)
    Job.objects.filter(pk=before.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    resumed = transport.post("api/worker/claim/", {"capabilities": {"providers": ["codex"]}})
    worker.generate_stage(worker.StageLease(transport, resumed, threading.Event()), arguments())
    after = Job.objects.get(pk=before.pk)
    assert provider.calls == 3 and ModelInvocation.objects.count() == 3
    assert after.cost_nano == before.cost_nano and after.cost_upper_nano == before.cost_upper_nano
    assert after.usage == before.usage and Candidate.objects.get().committed
    transport.close()


@pytest.mark.parametrize("legacy", [False, True])
def test_timeout_continuation_reuses_plan_and_preserves_dollar_ledger(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    legacy: bool,
) -> None:
    from decimal import Decimal

    from prompt2play.adapters.django.forge import workflow
    from prompt2play.adapters.django.forge.timeout_recovery import resume_timeout
    from prompt2play.legacy.worker.core import CodexCallTimeout, ProviderError
    from prompt2play.pricing import snapshot

    _, transport, claim = prepared
    Job.objects.filter(pk=claim["job"]["id"]).update(
        budget_usd=Decimal("10"),
        pricing=snapshot("gpt-6-astra", "codex"),
        model="gpt-6-astra",
        budget_tokens=1,
    )
    original_job = Job.objects.get(pk=claim["job"]["id"])
    claim["job"].update(
        budget_usd="10", pricing=original_job.pricing, model="gpt-6-astra", budget_tokens=1
    )

    class InterruptedAuthor(ScriptedProvider):
        def generate(self, *args: Any, **kwargs: Any) -> Any:
            if self.calls == 1:
                self.calls += 1
                error = ProviderError if legacy else CodexCallTimeout
                raise cast(Any, error)("Codex call exceeded wall timeout")
            return super().generate(*args, **kwargs)

    provider = InterruptedAuthor(replies())

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        configured = ProviderGateway(*args, **kwargs)
        configured.provider = provider
        return configured

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    lease = worker.StageLease(transport, claim, threading.Event())
    if legacy:
        with pytest.raises(ProviderError):
            worker.generate_stage(lease, arguments())
        lease.write("fail", error="ProviderError: Codex call exceeded wall timeout")
        before = Job.objects.get(pk=original_job.pk)
        old_plan = ModelInvocation.objects.get(operation="plan")
        old_author = ModelInvocation.objects.get(operation="author")
        resumed = cast(Any, resume_timeout)(before.pk)
        assert resumed.usage == before.usage and resumed.pricing == before.pricing
        assert (
            resumed.budget_usd == before.budget_usd
            and resumed.cost_upper_nano == before.cost_upper_nano
        )
        assert resumed.attempts == before.attempts and resumed.resume_count == 1
        assert resumed.stage_fence > before.stage_fence
        assert resumed.budget_seconds is None and resumed.execution_expires_at is None
        with pytest.raises(Exception, match="unrecovered"):
            cast(Any, resume_timeout)(before.pk)
        claim = transport.post("api/worker/claim/", {"capabilities": {"providers": ["codex"]}})
        lease = worker.StageLease(transport, claim, threading.Event())
    worker.generate_stage(lease, arguments())
    job = Job.objects.get(pk=original_job.pk)
    assert provider.calls == 4 and job.stage == "validate" and job.status == "queued"
    assert job.usage["total_tokens"] == 21 and job.usage["calls"] == 3
    assert job.budget_usd == Decimal("10") and job.cost_upper_nano > 0
    failed = ModelInvocation.objects.get(state="ambiguous")
    assert failed.actual_usage is None and failed.reserved_cost_nano > 0
    assert cast(Any, workflow.invocation_data)(failed)["response"] == {
        "interruption": "codex_wall_timeout"
    }
    assert cast(Any, workflow.cost_summary)(job)["reserved_usd"] != "0.000000000"
    assert ModelInvocation.objects.filter(operation="plan").count() == 1
    assert (
        ModelInvocation.objects.filter(
            invocation_key__endswith=":retry:1", state="completed"
        ).count()
        == 1
    )
    if legacy:
        assert ModelInvocation.objects.get(pk=old_plan.pk).response_key == old_plan.response_key
        assert failed.pk == old_author.pk
        assert job.events.filter(data__reason="codex_wall_timeout").exists()
    transport.close()


@pytest.mark.parametrize(
    "blocker", ["cancelled", "completed", "network", "retried", "active", "missing_receipt"]
)
def test_operator_recovery_rejects_unsafe_or_exhausted_replays(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]], blocker: str
) -> None:
    from prompt2play.adapters.django.forge.errors import Conflict
    from prompt2play.adapters.django.forge.timeout_recovery import resume_timeout

    runner, transport, claim = prepared
    job = Job.objects.get(pk=claim["job"]["id"])
    Job.objects.filter(pk=job.pk).update(
        status=blocker if blocker in ("cancelled", "completed") else "failed",
        error=(
            "ProviderError: Network lost"
            if blocker == "network"
            else "CodexCallTimeout: Codex call exceeded wall timeout"
            if blocker == "missing_receipt"
            else "ProviderError: Codex call exceeded wall timeout"
        ),
    )
    ModelInvocation.objects.create(
        job=job,
        generator=runner,
        invocation_key="author:fixture" + (":retry:1" if blocker == "retried" else ""),
        operation="author",
        prompt_sha256="a" * 64,
        stage_fence=job.stage_fence,
        state="ambiguous",
        reserved_tokens=20000,
    )
    if blocker == "active":
        services.create_job(
            job.project,
            job.created_by,
            {"kind": "generate", "prompt": "New request", "provider": "codex"},
        )
    with pytest.raises(Conflict):
        cast(Any, resume_timeout)(job.pk)
    job.refresh_from_db()
    assert job.resume_count == 0 and job.status != "queued"
    assert ModelInvocation.objects.get(job=job).reserved_tokens == 20000
    transport.close()
