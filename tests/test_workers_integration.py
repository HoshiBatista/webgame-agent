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


@pytest.fixture(autouse=True)
def browser_transport_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    # Authored transport result only; real isolated execution is tested separately.
    from prompt2play.validation.runner import artifact_manifest

    def validate(
        _self: Any,
        files: dict[str, str],
        html: str,
        spec: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "artifact": artifact_manifest(files, html, spec),
            "status": "passed",
            "checks": [
                {
                    "name": f"mechanics:{width}",
                    "status": "passed",
                    "artifact_sha256": artifact_manifest(files, html, spec)["html_sha256"],
                    "evidence": {
                        "actual_input": True,
                        "cases": [
                            {
                                "id": case["id"],
                                "actions": case["actions"],
                                "passed": True,
                                "visible_changed": True,
                            }
                            for case in spec.get("mechanics_acceptance", [])
                        ],
                    },
                }
                for width in (1280, 390)
            ]
            if spec.get("mechanics_required")
            else [],
            "warnings": ["Authored transport fixture"],
            "evidence_files": [],
        }

    monkeypatch.setattr("prompt2play.workers.runner.IsolatedValidator.validate", validate)
    monkeypatch.setattr("prompt2play.workers.runner.IsolatedValidator.preflight", lambda _self: {})


def test_stale_validator_fails_before_provider_or_reservation(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, transport, claim = prepared

    def reject(_self: Any) -> None:
        raise ValueError("Validator image does not match trusted checking code")

    def forbidden_gateway(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Provider must not be constructed before the environment check")

    monkeypatch.setattr("prompt2play.workers.runner.IsolatedValidator.preflight", reject)
    monkeypatch.setattr(worker, "ProviderGateway", forbidden_gateway)
    with pytest.raises(ValueError, match="does not match"):
        worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    assert not ModelInvocation.objects.filter(job_id=claim["job"]["id"]).exists()


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
    claim = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
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
        deadline=30,
        model="fixture",
        call_timeout=10,
        codex="fixture",
        mode="single_author",
        image="fixture",
        validation_timeout=30,
    )


@pytest.mark.parametrize("user_rule_change", [False, True])
def test_pro_supervisor_plan_confirmation_reclaims_exact_saved_draft(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    user_rule_change: bool,
) -> None:
    import copy

    from prompt2play.adapters.django.forge import workflow
    from prompt2play.adapters.django.forge.reviews import decide_review
    from prompt2play.contracts.models import stable

    _, transport, original = prepared
    artifact_store = cast(Any, workflow).store()
    job_id = original["job"]["id"]
    Job.objects.filter(pk=job_id).update(
        creation_mode="pro",
        checkpoint={"pipeline_version": "adaptive-v1", "project_format": "runtime-v1"},
    )
    original["job"]["creation_mode"] = "pro"
    original["job"].update(pipeline_version="adaptive-v1", project_format="runtime-v1")
    proposal, author, source_review = replies()
    feedback = "Change MOVE to decrease the counter instead of increasing it."

    class FlowProvider:
        def __init__(self) -> None:
            self.roles: list[str] = []
            self.supervisors = 0

        def preflight(self) -> None:
            pass

        def generate(
            self, _prompt: str, _schema: dict[str, Any], role: str, *_args: Any, **_kwargs: Any
        ) -> Any:
            self.roles.append(role)
            job = Job.objects.get(pk=job_id)
            if role == "plan":
                data = copy.deepcopy(proposal)
                if job.review.get("feedback"):
                    data["build_plan"]["mechanics_changes"] = [
                        {
                            "case_id": "move",
                            "request_excerpt": "decrease the counter instead of increasing it",
                            "reason": "Apply the new user rule; preserve all other controls and checks.",
                        }
                    ]
                    for device in ("desktop", "touch"):
                        for assertion in data["build_plan"]["mechanics"][0][device]["assertions"]:
                            assertion["op"] = "less"
            elif role == "author":
                data = copy.deepcopy(author)
                if self.roles.count("author") > 1:
                    data["operations"][0].update(
                        op="replace",
                        content=data["operations"][0]["content"] + "\n// improved mobile layout",
                    )
            elif role == "visual_review":
                data = source_review
            else:
                draft = artifact_store.read_json(job.checkpoint["authoring_draft"]["key"])
                if role == "coverage_review":
                    data = {
                        "requirements": {
                            r["id"]: {
                                "status": "implemented",
                                "file": "game.js",
                                "excerpt": "function createGame(ctx)",
                                "explanation": "Authored source fixture",
                            }
                            for r in draft["adaptive"]["requirements"]["payload"]["items"]
                        }
                    }
                else:
                    self.supervisors += 1
                    updated = copy.deepcopy(draft["plan"])
                    updated["visual_design"]["composition"]["mobile"] += " Larger touch targets."
                    data = {
                        "action": "revise_plan" if self.supervisors == 1 else "continue",
                        "reason": "Authored technical revision",
                        "observation_ids": [draft["adaptive"]["observations"][-1]["id"]],
                        "affected_files": ["game.js"],
                        "task_ids": [],
                        "plan_json": stable(updated) if self.supervisors == 1 else "",
                    }
            return cast(Any, Reply)(data, dict(USAGE))

    provider = FlowProvider()

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        configured = ProviderGateway(*args, **kwargs)
        configured.provider = provider
        return configured

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    monkeypatch.setattr(ProviderGateway, "image_preflight", lambda _: False)
    capabilities = {
        "providers": ["codex"],
        "continuable_authoring_v1": True,
        "continuable_planning_v1": True,
        "adaptive_generation_v1": True,
        "interactive_plan_v1": True,
    }

    def approve_and_claim() -> dict[str, Any]:
        job = Job.objects.get(pk=job_id)
        cast(Any, decide_review)(
            job_id, stage_fence=job.stage_fence, action="approve", actor_id=job.created_by_id
        )
        return transport.post("api/worker/claim/", {"capabilities": capabilities})

    with pytest.raises(worker.AwaitingApproval, match="Plan awaits"):
        worker.generate_stage(
            worker.StageLease(transport, original, threading.Event()), arguments()
        )
    claimed = approve_and_claim()
    with pytest.raises(worker.AwaitingApproval, match="Revised plan awaits"):
        worker.generate_stage(worker.StageLease(transport, claimed, threading.Event()), arguments())
    job = Job.objects.get(pk=job_id)
    saved_key = job.checkpoint["authoring_draft"]["key"]
    saved = artifact_store.read_json(saved_key)
    assert saved["adaptive"]["decisions"][-1]["action"] == "revise_plan"
    if user_rule_change:
        cast(Any, decide_review)(
            job_id,
            stage_fence=job.stage_fence,
            action="revise",
            feedback=feedback,
            actor_id=job.created_by_id,
        )
        claimed = transport.post("api/worker/claim/", {"capabilities": capabilities})
        assert not claimed["draft"] and claimed["previous_draft"] == saved
        with pytest.raises(worker.AwaitingApproval, match="Plan awaits"):
            worker.generate_stage(
                worker.StageLease(transport, claimed, threading.Event()), arguments()
            )
        claimed = approve_and_claim()
    else:
        claimed = approve_and_claim()
        assert claimed["draft"] == saved and claimed["previous_proposal"] == {
            "spec": proposal["game_spec"],
            "plan": proposal["build_plan"],
        }
    worker.generate_stage(worker.StageLease(transport, claimed, threading.Event()), arguments())
    job.refresh_from_db()
    assert job.stage == "validate" and Candidate.objects.get().committed
    assert provider.roles.count("plan") == (2 if user_rule_change else 1)
    assert provider.roles.count("author") == 2
    assert artifact_store.read_json(saved_key) == saved
    if user_rule_change:
        controller = cast(Any, workflow).candidate_payload(Candidate.objects.get())["provenance"][
            "adaptive"
        ]
        assert controller["requirements"]["payload"]["user_feedback"][-1]["text"] == feedback
    assert job.usage["calls"] == ModelInvocation.objects.filter(state="completed").count()
    transport.close()


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
    resumed = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
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
    resumed = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
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
        claim = transport.post(
            "api/worker/claim/",
            {
                "capabilities": {
                    "providers": ["codex"],
                    "continuable_authoring_v1": True,
                    "continuable_planning_v1": True,
                }
            },
        )
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


def test_pro_pauses_before_code_and_approval_reuses_paid_plan(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, transport, claim = prepared
    job_id = claim["job"]["id"]
    Job.objects.filter(pk=job_id).update(creation_mode="pro")
    provider = ScriptedProvider(replies())

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        result = ProviderGateway(*args, **kwargs)
        result.provider = provider
        return result

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    lease = worker.StageLease(transport, claim, threading.Event())
    with pytest.raises(worker.AwaitingApproval):
        worker.generate_stage(lease, arguments())
    paused = Job.objects.get(pk=job_id)
    assert paused.status == "waiting" and paused.stage == "review_plan" and provider.calls == 1
    assert paused.usage["total_tokens"] == 7 and not Candidate.objects.exists()
    assert (
        transport.post(
            "api/worker/claim/",
            {
                "capabilities": {
                    "providers": ["codex"],
                    "interactive_plan_v1": True,
                    "continuable_authoring_v1": True,
                    "continuable_planning_v1": True,
                }
            },
        )["job"]
        is None
    )
    client = Client()
    client.force_login(paused.created_by)
    assert client.get(f"/api/projects/{paused.project_id}/").json()["active_job"]["id"] == job_id
    saved = client.get(f"/api/jobs/{job_id}/insights/").json()
    assert saved["proposal"]["plan"]["visual_design"] and saved["approval"] == "plan"
    accepted = client.post(
        f"/api/jobs/{job_id}/review/",
        {"action": "approve", "stage_fence": paused.stage_fence},
        content_type="application/json",
    )
    assert accepted.status_code == 200 and accepted.json()["status"] == "queued"
    duplicate = client.post(
        f"/api/jobs/{job_id}/review/",
        {"action": "approve", "stage_fence": paused.stage_fence},
        content_type="application/json",
    )
    assert duplicate.status_code == 409
    # An older worker cannot silently bypass the interactive gate.
    assert (
        transport.post(
            "api/worker/claim/",
            {
                "capabilities": {
                    "providers": ["codex"],
                    "continuable_authoring_v1": True,
                    "continuable_planning_v1": True,
                }
            },
        )["job"]
        is None
    )
    claim = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "interactive_plan_v1": True,
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
    worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    assert provider.calls == 3 and Candidate.objects.get().committed
    assert ModelInvocation.objects.filter(operation="plan").count() == 1
    transport.close()


def test_pro_plan_feedback_is_persisted_and_requires_fresh_confirmation(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from copy import deepcopy

    from prompt2play.adapters.django.forge.reviews import decide_review

    _, transport, claim = prepared
    job_id = claim["job"]["id"]
    Job.objects.filter(pk=job_id).update(creation_mode="pro")
    initial = replies()[0]
    revised = deepcopy(initial)
    revised["game_spec"]["rules"].append("User requested new rule")
    provider = ScriptedProvider([initial, revised])
    prompts: list[str] = []

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        result = ProviderGateway(*args, **kwargs)

        class RecordingProvider:
            def preflight(self) -> None:
                pass

            def generate(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
                prompts.append(prompt)
                return provider.generate(prompt, *args, **kwargs)

        result.provider = RecordingProvider()
        return result

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    with pytest.raises(worker.AwaitingApproval):
        worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    job = Job.objects.get(pk=job_id)
    cast(Any, decide_review)(
        job_id, stage_fence=job.stage_fence, action="revise", feedback="Add the requested rule"
    )
    claim = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "interactive_plan_v1": True,
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
    with pytest.raises(worker.AwaitingApproval):
        worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    assert provider.calls == 2 and "Add the requested rule" in prompts[1]
    job.refresh_from_db()
    assert job.status == "waiting" and job.usage["total_tokens"] == 14
    assert job.review["plan_key"] != job.review["previous_plan_key"]
    assert "approved_plan_key" not in job.review and not Candidate.objects.exists()
    services.cancel_job(job_id)
    with pytest.raises(Exception, match="Предложение уже изменилось"):
        cast(Any, decide_review)(job_id, stage_fence=job.stage_fence, action="approve")
    assert Job.objects.get(pk=job_id).status == "cancelled"
    transport.close()


def test_insights_exposes_draft_steps_without_claiming_a_saved_or_validated_game(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
) -> None:
    from prompt2play.adapters.django.forge import reviews, workflow

    runner, transport, claim = prepared
    job = Job.objects.get(pk=claim["job"]["id"])
    for role, data in (
        (
            "author",
            {
                "summary": "Draft rendering added",
                "operations": [
                    {"op": "create", "path": "game.js", "content": "PRIVATE_SOURCE_NOT_IN_INSIGHTS"}
                ],
            },
        ),
        ("visual_review", replies()[2]),
    ):
        intent, key = cast(Any, workflow.store)().prepare({"data": data, "usage": USAGE})
        cast(Any, workflow.store)().commit(intent, key)
        ModelInvocation.objects.create(
            job=job,
            generator=runner,
            invocation_key=role + ":fixture",
            operation=role,
            prompt_sha256="a" * 64,
            stage_fence=job.stage_fence,
            state="completed",
            reserved_tokens=1000,
            response_key=key,
        )
    detail = cast(Any, reviews.insights)(job)
    assert detail["author_steps"][0]["summary"] == "Draft rendering added"
    assert detail["author_steps"][0]["operations"] == [{"op": "create", "path": "game.js"}]
    assert detail["provenance"]["visual_quality"]["draft_only"] is True
    assert detail["validation"] is None and detail["files"] == []
    assert "PRIVATE_SOURCE_NOT_IN_INSIGHTS" not in json.dumps(detail)
    transport.close()


def test_rejected_model_response_is_feedback_and_accounted_once_across_restart(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from prompt2play.adapters.django.forge import workflow
    from prompt2play.adapters.django.forge.drafts import load_draft
    from prompt2play.legacy.worker.core import ProviderError

    _, transport, claim = prepared

    class RejectOnce(ScriptedProvider):
        def generate(self, *args: Any, **kwargs: Any) -> Any:
            if self.calls == 1:
                self.calls += 1
                error = cast(Any, ProviderError)("Invalid structured JSON", usage=dict(USAGE))
                error.structured_diagnostic = {
                    "category": "schema",
                    "keyword": "required",
                    "instance_path": ["operations"],
                }
                raise error
            return super().generate(*args, **kwargs)

    provider = RejectOnce(replies())
    prompts = []

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        result = ProviderGateway(*args, **kwargs)

        class Recording:
            preflight = provider.preflight

            def generate(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
                prompts.append(prompt)
                return provider.generate(prompt, *args, **kwargs)

        result.provider = Recording()
        return result

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    original = transport.post

    def fail_checkpoint(path: str, values: dict[str, Any]) -> dict[str, Any]:
        if path.endswith("/draft/") and values["draft"]["turn"] == 1:
            raise httpx.ReadTimeout("Crash after rejection receipt, before checkpoint")
        return original(path, values)

    monkeypatch.setattr(transport, "post", fail_checkpoint)
    with pytest.raises(httpx.ReadTimeout):
        worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    before = Job.objects.get(pk=claim["job"]["id"])
    assert provider.calls == 2 and before.usage["calls"] == 2
    assert cast(Any, load_draft)(before)["turn"] == 0
    receipt = ModelInvocation.objects.get(operation="author")
    assert (
        cast(Any, workflow.invocation_data)(receipt)["response"]["rejection"] == "structured_output"
    )
    monkeypatch.setattr(transport, "post", original)
    Job.objects.filter(pk=before.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    resumed = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
    worker.generate_stage(worker.StageLease(transport, resumed, threading.Event()), arguments())
    after = Job.objects.get(pk=before.pk)
    assert provider.calls == 4 and after.usage["calls"] == 4
    assert "Response rejected; no operations applied" in prompts[2]
    assert Candidate.objects.get().committed
    transport.close()


def test_draft_is_fenced_and_old_workers_cannot_reclaim_it(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, transport, claim = prepared
    provider = ScriptedProvider(replies())

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        result = ProviderGateway(*args, **kwargs)
        result.provider = provider
        return result

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    original = transport.post
    captured: list[dict[str, Any]] = []

    def interrupt(path: str, values: dict[str, Any]) -> dict[str, Any]:
        result = original(path, values)
        if path.endswith("/draft/"):
            captured.append(values)
            raise httpx.ReadTimeout("Crash after draft save")
        return result

    monkeypatch.setattr(transport, "post", interrupt)
    with pytest.raises(httpx.ReadTimeout):
        worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    job = Job.objects.get(pk=claim["job"]["id"])
    monkeypatch.setattr(transport, "post", original)
    Job.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    assert (
        transport.post("api/worker/claim/", {"capabilities": {"providers": ["codex"]}})["job"]
        is None
    )
    resumed = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
    assert resumed["draft"]["phase"] == "author"
    with pytest.raises(worker.LeaseRejected):
        transport.post(f"api/worker/jobs/{job.pk}/draft/", captured[-1])
    services.cancel_job(job.pk)
    payload = {
        **captured[-1],
        "lease_token": resumed["lease_token"],
        "stage_fence": resumed["job"]["stage_fence"],
    }
    with pytest.raises(worker.LeaseRejected):
        transport.post(f"api/worker/jobs/{job.pk}/draft/", payload)
    assert not Candidate.objects.exists()
    transport.close()


def test_legacy_operation_limit_recovers_completed_draft_without_replaying_author(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from prompt2play.adapters.django.forge.authoring_recovery import resume_authoring
    from prompt2play.legacy.worker.core import ProviderError

    _, transport, claim = prepared
    outputs = replies()
    # Save a real authored draft before a second author response hits the old limit.
    outputs[1]["operations"] = outputs[1]["operations"][:-1]

    class LegacyProvider(ScriptedProvider):
        def generate(self, *args: Any, **kwargs: Any) -> Any:
            if self.calls == 2:
                self.calls += 1
                raise cast(Any, ProviderError)(
                    "Provider returned invalid structured JSON; maxItems at /operations",
                    usage=dict(USAGE),
                )
            return super().generate(*args, **kwargs)

    provider = LegacyProvider(outputs)

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        result = ProviderGateway(*args, **kwargs)
        result.provider = provider
        return result

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    lease = worker.StageLease(transport, claim, threading.Event())
    with pytest.raises(ProviderError):
        worker.generate_stage(lease, arguments())
    lease.write(
        "fail",
        error="ProviderError: Provider returned invalid structured JSON; maxItems at /operations",
    )
    # Old versions had receipts but no source checkpoint.
    Job.objects.filter(pk=claim["job"]["id"]).update(checkpoint={})
    before = Job.objects.get(pk=claim["job"]["id"])
    recovered = cast(Any, resume_authoring)(before.pk)
    assert recovered.usage == before.usage and recovered.resume_count == before.resume_count + 1
    assert recovered.cost_upper_nano == before.cost_upper_nano
    with pytest.raises(Exception, match="Only a failed"):
        cast(Any, resume_authoring)(before.pk)
    resumed = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
    assert resumed["draft"]["files"]["game.js"]
    provider.outputs.insert(
        0,
        {
            "operations": [{"op": "submit", "path": "", "content": "", "old": "", "new": ""}],
            "summary": "Continue draft",
        },
    )
    worker.generate_stage(worker.StageLease(transport, resumed, threading.Event()), arguments())
    assert provider.calls == 5 and ModelInvocation.objects.filter(operation="plan").count() == 1
    assert Candidate.objects.get().committed
    transport.close()


def test_claim_failure_loading_snapshot_does_not_orphan_a_lease(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, transport, claim = prepared
    Job.objects.filter(pk=claim["job"]["id"]).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    before = Job.objects.get(pk=claim["job"]["id"])

    def unreadable(_job: Any) -> dict[str, Any]:
        raise ValueError("Authored unreadable checkpoint")

    monkeypatch.setattr("prompt2play.adapters.django.forge.drafts.load_draft", unreadable)
    with pytest.raises(ValueError, match="unreadable"):
        transport.post(
            "api/worker/claim/",
            {
                "capabilities": {
                    "providers": ["codex"],
                    "continuable_authoring_v1": True,
                    "continuable_planning_v1": True,
                }
            },
        )
    after = Job.objects.get(pk=before.pk)
    assert after.stage_fence == before.stage_fence and after.lease_hash == before.lease_hash
    assert after.lease_expires_at == before.lease_expires_at
    transport.close()


@pytest.mark.parametrize("failed_role", ["plan", "author"])
def test_explicit_continuation_finishes_saved_work_without_replaying_successful_calls(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    failed_role: str,
) -> None:
    from prompt2play.adapters.django.forge.recovery import resume_job
    from prompt2play.legacy.worker.core import ProviderError

    _, transport, claim = prepared
    saved = replies()

    class InterruptedProvider(ScriptedProvider):
        def generate(self, *_args: Any, **kwargs: Any) -> Any:
            if (failed_role == "plan") or self.calls == 1:
                self.calls += 1
                raise cast(Any, ProviderError)("Fixture transport interruption")
            return super().generate(*_args, **kwargs)

    broken = InterruptedProvider(saved[:1])
    current: list[ScriptedProvider] = [broken]

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        configured = ProviderGateway(*args, **kwargs)
        configured.provider = current[0]
        return configured

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    lease = worker.StageLease(transport, claim, threading.Event())
    with pytest.raises(ProviderError):
        worker.generate_stage(lease, arguments())
    lease.write("fail", error="ProviderError: Fixture transport interruption")
    job = Job.objects.get(pk=claim["job"]["id"])
    before_calls = job.usage["calls"]
    unknown = job.invocations.get(state="ambiguous")
    assert unknown.actual_usage is None
    cast(Any, resume_job)(job.pk, {"stage_fence": job.stage_fence})
    fresh = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
    assert fresh["job"]["id"] == str(job.pk)
    assert bool(fresh.get("draft")) == (failed_role == "author")
    current[0] = ScriptedProvider(replies()[1:] if failed_role == "author" else replies())
    worker.generate_stage(worker.StageLease(transport, fresh, threading.Event()), arguments())
    job.refresh_from_db()
    unknown.refresh_from_db()
    assert job.stage == "validate" and job.status == "queued"
    assert current[0].calls == (2 if failed_role == "author" else 3)
    assert job.usage["calls"] == before_calls + current[0].calls
    assert unknown.actual_usage is None and unknown.state == "ambiguous"
    assert job.project.latest_version_id is None


@pytest.mark.parametrize("pause_at", [1, 2, 3])
def test_pause_during_model_call_keeps_reply_and_continuation_does_not_pay_twice(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    pause_at: int,
) -> None:
    from prompt2play.adapters.django.forge.pauses import pause_job, resume_paused
    from prompt2play.generation.workspace import GenerationPaused

    _, transport, claim = prepared
    job_id = claim["job"]["id"]

    class PausingProvider(ScriptedProvider):
        def generate(self, *args: Any, **kwargs: Any) -> Any:
            reply = super().generate(*args, **kwargs)
            if self.calls == pause_at:
                job = Job.objects.get(pk=job_id)
                cast(Any, pause_job)(job.pk, {"stage_fence": job.stage_fence})
            return reply

    provider = PausingProvider(replies())

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        configured = ProviderGateway(*args, **kwargs)
        configured.provider = provider
        return configured

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    with pytest.raises(GenerationPaused):
        worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    job = Job.objects.get(pk=job_id)
    assert job.status == "paused" and job.usage["calls"] == pause_at
    assert job.invocations.filter(state="completed").count() == pause_at
    cast(Any, resume_paused)(job.pk, {"stage_fence": job.stage_fence})
    new_claim = transport.post(
        "api/worker/claim/",
        {
            "capabilities": {
                "providers": ["codex"],
                "continuable_authoring_v1": True,
                "continuable_planning_v1": True,
            }
        },
    )
    worker.generate_stage(worker.StageLease(transport, new_claim, threading.Event()), arguments())
    job.refresh_from_db()
    assert provider.calls == 3
    assert job.usage["calls"] == 3 and job.stage == "validate"
    assert job.invocations.count() == 3
    assert job.candidates.count() == 1


def test_planner_rejections_are_saved_and_can_self_correct_after_restart(
    prepared: tuple[Any, worker.Coordinator, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, transport, claim = prepared
    sequence = replies()
    invalid = json.loads(json.dumps(sequence[0]))
    invalid["build_plan"]["mechanics"][0]["desktop"]["steps"][0]["ms"] = 200
    provider = ScriptedProvider([invalid, *sequence])

    def gateway(*args: Any, **kwargs: Any) -> ProviderGateway:
        configured = ProviderGateway(*args, **kwargs)
        configured.provider = provider
        return configured

    monkeypatch.setattr(worker, "ProviderGateway", gateway)
    worker.generate_stage(worker.StageLease(transport, claim, threading.Event()), arguments())
    job = Job.objects.get(pk=claim["job"]["id"])
    assert job.stage == "validate" and provider.calls == 4
    event = job.events.filter(level="warning", data__correction=1).get()
    assert "ms must be 0" in event.message
