"""Django recovery/cancellation against the real relay store, without a GPU call."""

import json
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
from django.utils import timezone

from generation.providers.fake import fixture_response
from generation.relay_api.client import Client
from studio.models import Chat, Outbox, Revision, User
from studio.services import create_run
from studio.tasks import process_run, reconcile_relay_cancellations, recover_expired
from tests.relay_double import RelayDouble


@pytest.fixture
def environment(tmp_path, settings, monkeypatch):
    settings.GAMEFORGE_PROVIDER = "relay"
    settings.GAMEFORGE_MODEL = "qwen38"
    monkeypatch.setenv("GAMEFORGE_RELAY_URL", "https://relay.test")
    monkeypatch.setenv(
        "GAMEFORGE_PRICES_JSON",
        '{"qwen38":{"input":0,"cached":0,"output":0,"context_window":32768,"max_output_tokens":6144}}',
    )
    store = RelayDouble()
    token = "x" * 32
    app = store
    monkeypatch.setenv("GAMEFORGE_RELAY_API_KEY", token)
    monkeypatch.setattr(
        "generation.providers.relay.Client",
        lambda url, key: Client(url, key, transport=httpx.WSGITransport(app)),
    )
    calls = []

    class FakeExecutor:
        # Simulates the HTTP peer, never imports service code into the application.
        pending = None

        def step(self):
            if self.pending:
                ident, receipt = self.pending
                store.finish(ident, "gpu", receipt)
                self.pending = None
                return True
            job = store.claim("gpu")
            if not job:
                return False
            calls.append(1)
            store.worker_update(job["id"], "gpu", start=True)
            self.pending = (
                job["id"],
                {
                    "ok": True,
                    "result": {
                        "response": {
                            "model": "qwen38",
                            "choices": [
                                {
                                    "message": {"content": json.dumps(fixture_response())},
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                        }
                    },
                },
            )
            return True

    executor = FakeExecutor()
    with (
        patch("studio.tasks.process_run.delay"),
        patch(
            "validation.service.validate",
            return_value={
                "status": "passed",
                "findings": [],
                "facts": [],
                "environment": {"version": "test"},
            },
        ),
        patch("validation.service.environment_identity", return_value={"version": "test"}),
    ):
        owner = User.objects.create_user(username="owner")
        chat = Chat.objects.create(owner=owner)
        run = create_run(chat, {"prompt": "Create a mini game", "idempotency_key": "stable"})
        yield run, store, executor, calls


@pytest.mark.django_db(transaction=True)
def test_application_poll_restart_and_lost_receipt_commit_never_repeat_model(environment, monkeypatch):
    run, store, executor, calls = environment
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "queued" and run.attempts == 1
    inv = run.invocations.get()
    assert inv.state == "sent" and inv.request["relay"]["id"] == str(inv.id)
    original_request = inv.request
    for _ in range(2):
        process_run(str(run.id))
    assert run.invocations.count() == 1
    # Simulate application death with an expired lease after remote admission.
    run.refresh_from_db()
    run.status = "generating"
    run.lease_until = timezone.now() - timedelta(seconds=5)
    run.save()
    recover_expired()
    run.refresh_from_db()
    inv.refresh_from_db()
    assert run.status == "queued" and inv.state == "sent"
    assert Outbox.objects.filter(run=run).exists()
    executor.step()
    executor.step()
    # A database failure after receipt retrieval must only cause a receipt re-fetch.
    with patch("studio.tasks.settle_invocation", side_effect=RuntimeError("DB interrupted")):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "queued"
    process_run(str(run.id))
    run.refresh_from_db()
    inv.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert inv.request == original_request
    assert run.attempts == 1 and run.invocations.count() == 1 and calls == [1]
    assert Revision.objects.filter(run=run).count() == 1
    process_run(str(run.id))
    assert calls == [1]


@pytest.mark.django_db(transaction=True)
def test_cancel_survives_application_disconnect_and_never_applies_late_game(environment):
    run, store, executor, calls = environment
    process_run(str(run.id))
    executor.step()  # Completed locally, delivery not yet acknowledged.
    run.refresh_from_db()
    run.status, run.cancel_requested = "cancelled", True
    run.save()
    reconcile_relay_cancellations()
    assert store.get(str(run.invocations.get().id), "gameforge")["cancel_requested"]
    executor.step()
    reconcile_relay_cancellations()
    run.refresh_from_db()
    assert run.status == "cancelled"
    assert not Revision.objects.filter(run=run).exists()
    assert run.invocations.get().state == "returned"  # Receipt/accounting are preserved.
    assert calls == [1]


@pytest.mark.django_db(transaction=True)
def test_cancel_before_executor_claim_has_no_model_call(environment):
    run, store, executor, calls = environment
    process_run(str(run.id))
    run.refresh_from_db()
    run.status, run.cancel_requested = "cancelled", True
    run.save()
    reconcile_relay_cancellations()
    assert executor.step() is False
    assert run.invocations.get().state == "failed"
    assert run.invocations.get().cost_usd == 0
    assert calls == []


@pytest.mark.django_db(transaction=True)
def test_auth_failure_remains_visible_and_recovers_same_invocation(environment, monkeypatch):
    from generation.relay_api.client import RelayHTTPError
    run, store, executor, calls = environment
    original = Client.call
    def denied(*args, **kwargs):
        raise RelayHTTPError(401)
    monkeypatch.setattr(Client, "call", denied)
    process_run(str(run.id))
    run.refresh_from_db()
    inv = run.invocations.get()
    assert run.stage == "waiting_admin" and run.error["code"] == "relay_unauthorized"
    assert inv.state == "sent" and inv.provider_metadata["relay_wait"]["http_status"] == 401
    assert Outbox.objects.get(run=run).dispatched_at > timezone.now() + timedelta(seconds=200)
    monkeypatch.setattr(Client, "call", original)
    process_run(str(run.id))
    executor.step()
    executor.step()
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded" and not run.error
    assert run.invocations.get().id == inv.id and calls == [1]


@pytest.mark.django_db(transaction=True)
def test_late_pending_diagnostics_do_not_overwrite_committed_result(environment):
    from generation.errors import GenerationPending
    from studio.tasks import record_relay_pending
    run, _, executor, _ = environment
    process_run(str(run.id))
    stale = run.invocations.get()
    executor.step()
    executor.step()
    process_run(str(run.id))
    fresh = run.invocations.get()
    record_relay_pending(stale, GenerationPending("late", code="late"))
    fresh.refresh_from_db()
    assert fresh.state == "settled"
    assert fresh.provider_metadata.get("relay_wait", {}).get("code") != "late"
