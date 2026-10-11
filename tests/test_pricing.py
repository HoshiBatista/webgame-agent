"""USD budgets use separate cache rates and durable, idempotent receipts."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from prompt2play.adapters.django.forge import services as _services
from prompt2play.adapters.django.forge import workflow as _workflow
from prompt2play.adapters.django.forge.errors import Conflict
from prompt2play.adapters.django.forge.models import Job, Project, Runner, User
from prompt2play.adapters.django.forge.serializers import JobCreateSerializer
from prompt2play.generation.workspace import GenerationControl, GenerationStopped
from prompt2play.pricing import catalog, cost_bounds, nano_usd, snapshot

services: Any = _services
workflow: Any = _workflow


def receipt(incoming: int, cached: int = 0, output: int = 0) -> dict[str, int]:
    return {
        "input_tokens": incoming,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "total_tokens": incoming + output,
        "calls": 1,
    }


def test_cache_is_a_subset_and_reasoning_output_is_not_double_counted() -> None:
    rate = snapshot("gpt-6-astra", "openai")
    # Within the short-context tier: 10k fresh + 90k cached + 1k output.
    lower, upper = cost_bounds(receipt(100000, 90000, 1000), rate)
    assert lower == nano_usd("0.24")
    assert upper == nano_usd("0.265")
    assert cost_bounds(receipt(100000, 100000), rate) == (nano_usd("0.1"),) * 2
    assert cost_bounds(receipt(0, 0, 0), rate) == (0, 0)
    assert cost_bounds(receipt(1), snapshot("gpt-6-luna", "openai")) == (100, 125)
    with pytest.raises(ValueError, match="Cached"):
        cost_bounds(receipt(1, 2), rate)
    with pytest.raises(ValueError, match="Incomplete"):
        cost_bounds({"input_tokens": 1, "output_tokens": 0}, rate)


def test_long_context_is_per_invocation_and_codex_aggregate_is_a_bound() -> None:
    rate = snapshot("gpt-6-astra", "openai")
    assert cost_bounds(receipt(272000, 0, 1000), rate)[0] == nano_usd("2.77")
    assert cost_bounds(receipt(272001, 0, 1000), rate)[0] == nano_usd("5.51502")
    assert sum(cost_bounds(receipt(200000), rate)[0] for _ in range(2)) == nano_usd("4")
    codex = snapshot("gpt-6-astra", "codex")
    assert cost_bounds(receipt(400000), codex) == (nano_usd("4"), nano_usd("10"))


def test_model_prices_and_snapshot_do_not_guess_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    assert len(catalog()["models"]) == 7
    assert snapshot("gpt-5.6-luna", "codex")["usd_per_million"]["output"] == "1.20"
    with pytest.raises(ValueError, match="тарифа"):
        snapshot("gpt-unknown", "codex")
    frozen = snapshot("gpt-6-astra", "codex")
    changed = copy.deepcopy(catalog())
    changed["models"]["gpt-6-astra"]["input"] = "11"
    monkeypatch.setattr("prompt2play.pricing.catalog", lambda: changed)
    assert frozen["usd_per_million"]["input"] == "10"


def test_usd_control_ignores_total_tokens_but_holds_unknown_and_parallel_calls() -> None:
    control = GenerationControl.bounded(
        token_limit=1, cost_limit_nano=nano_usd("3"), pricing=snapshot("gpt-6-astra", "codex")
    )
    control.reserve("one", nano_usd("1"))
    control.reserve("two", nano_usd("2"))
    with pytest.raises(GenerationStopped):
        control.reserve("three", 1)
    control.settle("one", receipt(100000, 100000))
    control.settle("two", None)
    control.guard()
    assert control.usage["total_tokens"] == 100000
    assert control.available_budget() == nano_usd("0.9")
    assert control.snapshot()["uncertain_cost_nano"] == nano_usd("2")
    assert control.estimate("prompt", 1000) > nano_usd("0.05")
    with pytest.raises(ValueError, match="Dollar"):
        control.available_tokens()
    control.reserve("overrun", 1)
    control.settle("overrun", receipt(0, 0, 100000))
    with pytest.raises(GenerationStopped, match="бюджет"):
        control.guard()


@pytest.fixture
def money_job(db: Any) -> tuple[Any, Any, str]:
    user = User.objects.create_user("budget-fixture")
    project = Project.objects.create(
        title="Authored budget test", prompt="fixture", created_by=user
    )
    runner = Runner.objects.create(
        name="generator",
        role="generator",
        token_hash="fixture",
        last_seen=timezone.now(),
        capabilities={"providers": ["codex"], "model": "gpt-6-astra"},
    )
    job = services.create_job(
        project,
        user,
        {
            "kind": "generate",
            "provider": "codex",
            "model": "",
            "prompt": "fixture",
            "budget_usd": Decimal("3.00"),
            "budget_tokens": 1000,
        },
    )
    claimed, lease = services.claim_job(runner, runner.capabilities)
    assert job.pk == claimed.pk and claimed.model == "gpt-6-astra"
    return claimed, runner, lease


def reserve(job: Any, runner: Any, lease: str, key: str, output: int = 10000) -> Any:
    return workflow.reserve_invocation(
        job.pk,
        runner,
        {
            "lease_token": lease,
            "stage_fence": job.stage_fence,
            "invocation_key": key,
            "operation": "fixture",
            "prompt_sha256": "a" * 64,
            "reserved_tokens": 1000000,
            "reservation_input_tokens": 1000,
            "reservation_output_tokens": output,
        },
    )


def test_durable_cost_idempotency_unknown_holds_and_late_cancel_receipt(
    money_job: tuple[Any, Any, str],
) -> None:
    job, runner, lease = money_job
    first = reserve(job, runner, lease, "one")
    assert reserve(job, runner, lease, "one").pk == first.pk
    held = reserve(job, runner, lease, "unknown", output=40000)
    job.refresh_from_db()
    assert workflow.cost_summary(job)["reserved_usd"] == "2.525000000"
    with pytest.raises(Conflict):
        reserve(job, runner, lease, "cannot-fit")
    usage = receipt(1000000, 1000000)  # a million cached tokens, 0 fresh
    values = {"invocation_id": first.pk, "invocation_usage": usage}
    services.cancel_job(job.pk)
    workflow.account_invocation(job.pk, runner, values)
    workflow.account_invocation(job.pk, runner, values)
    job.refresh_from_db()
    assert job.cost_nano == nano_usd("1") and job.cost_upper_nano == nano_usd("2")
    assert job.usage["total_tokens"] == 1000000
    assert workflow.cost_summary(job)["reserved_usd"] == "2.012500000"
    workflow.account_invocation(
        job.pk, runner, {"invocation_id": held.pk, "invocation_usage": receipt(0)}
    )
    job.refresh_from_db()
    assert workflow.cost_summary(job)["reserved_usd"] == "0.000000000"
    with pytest.raises(Conflict):
        workflow.account_invocation(job.pk, runner, {**values, "invocation_usage": receipt(2)})


def test_completed_without_receipt_keeps_reservation_and_old_worker_cannot_dispatch(
    money_job: tuple[Any, Any, str], settings: Any, tmp_path: Any
) -> None:
    settings.ARTIFACT_ROOT = tmp_path
    job, runner, lease = money_job
    invocation = reserve(job, runner, lease, "one")
    workflow.settle_invocation(
        job.pk,
        runner,
        {
            "lease_token": lease,
            "stage_fence": job.stage_fence,
            "invocation_id": invocation.pk,
            "state": "completed",
            "response": {},
        },
    )
    assert workflow.cost_summary(job)["reserved_usd"] == "0.512500000"
    with pytest.raises(Conflict, match="Обновите"):
        workflow.reserve_invocation(
            job.pk,
            runner,
            {
                "lease_token": lease,
                "stage_fence": job.stage_fence,
                "invocation_key": "old-worker",
                "operation": "fixture",
                "prompt_sha256": "b" * 64,
                "reserved_tokens": 1000,
            },
        )


def test_job_rejects_unpriced_model_and_api_validates_dollars(
    money_job: tuple[Any, Any, str],
) -> None:
    job, _, _ = money_job
    with pytest.raises(ValidationError, match="тарифа"):
        services.create_job(
            job.project,
            job.created_by,
            {
                "kind": "generate",
                "provider": "codex",
                "model": "missing",
                "prompt": "fixture",
                "budget_usd": Decimal("1"),
            },
        )
    base = {"kind": "generate", "provider": "codex", "model": "gpt-6-astra", "prompt": "fixture"}
    for amount in ["0", "-1", "NaN", "Infinity", "1.001", "1000.01"]:
        validator: Any = JobCreateSerializer(data={**base, "budget_usd": amount})
        assert not validator.is_valid()
    validator = JobCreateSerializer(data={**base, "budget_usd": "12.34"})
    assert validator.is_valid(), validator.errors
    validator = JobCreateSerializer(data={**base, "budget_usd": "12.34", "budget_tokens": 400000})
    assert not validator.is_valid()
    client = Client()
    assert client.get("/api/pricing/").status_code == 401
    client.force_login(job.created_by)
    assert len(client.get("/api/pricing/").json()["models"]) == 7
    assert client.get(f"/api/jobs/{job.pk}/").json()["budget_usd"] == "3.00"
    assert Job.objects.get(pk=job.pk).pricing["model"] == "gpt-6-astra"


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_usd_reservations_cannot_spend_same_remainder(
    money_job: tuple[Any, Any, str],
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, connection

    if connection.vendor != "postgresql":
        pytest.skip("Requires real PostgreSQL row-write serialization")
    job, runner, lease = money_job
    Job.objects.filter(pk=job.pk).update(budget_usd=Decimal("1.00"))
    barrier = threading.Barrier(2)

    def contender(key: str) -> bool:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            reserve(job, runner, lease, key)
            return True
        except Conflict:
            return False
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        admitted = list(executor.map(contender, ["first", "second"]))
    assert sorted(admitted) == [False, True]
    assert job.invocations.count() == 1
