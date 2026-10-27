import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
from django.test import Client as WebClient
from django.utils import timezone

from generation.errors import GenerationError, GenerationPending
from generation.providers import codex_api
from generation.providers.fake import fixture_response
from generation.relay_api.protocol import digest
from generation.schema import response_schema
from studio.models import Chat, Invocation, Revision, User
from studio.services import cancel_run, create_run
from studio.tasks import process_run, reconcile_relay_cancellations, recover_expired
from tests.codex_api_double import CodexDouble
from tests.test_generation_planning import screenshot_request


@pytest.fixture
def api(monkeypatch, tmp_path):
    peer = CodexDouble()
    monkeypatch.setenv("GAMEFORGE_CODEX_API_URL", "https://codex.test")
    monkeypatch.setenv("GAMEFORGE_CODEX_API_KEY", "x" * 32)
    monkeypatch.delenv("GAMEFORGE_CODEX_API_KEY_FILE", raising=False)
    monkeypatch.setenv("GAMEFORGE_CODEX_API_CATALOG", str(tmp_path / "catalog.json"))
    client_type = codex_api.Client
    monkeypatch.setattr(codex_api, "Client", lambda url, token: client_type(
        url, token, transport=httpx.MockTransport(peer)))
    codex_api.refresh_catalog()
    return peer


def request_for_api(**extra):
    request = {"provider": "codex_api", "operation": "create", "model": "gpt-6-sol",
               "generation_strategy": "pro", "reasoning_effort": "high", **extra}
    if request["operation"] == "check_repair":
        from generation.check_repair import permission

        response = fixture_response()
        request["check_repair"] = permission("a" * 64, response["checks"], response["design"])
    request["codex_api"] = codex_api.prepare(request, str(uuid.uuid4()))
    return request


@pytest.mark.parametrize("operation", ["plan", "create", "edit", "repair", "check_repair"])
@pytest.mark.parametrize("profile", ["full", "compact"])
def test_api_freezes_exact_schema_effort_and_bounded_candidate_image(api, operation, profile):
    request = request_for_api(operation=operation, generation_profile=profile, **screenshot_request())
    payload = request["codex_api"]["payload"]
    assert payload["output_schema"] == response_schema(request)
    assert payload["effort"] == "high" and payload["model"] == "gpt-6-sol"
    assert payload["images"] == [{k: request["preview_image"][k] for k in ("mime", "data")}]
    assert "x" * 32 not in json.dumps(request)
    assert not api.jobs


@pytest.mark.parametrize("profile", ["full", "compact"])
def test_api_fragment_correction_receipt_keeps_bound_scope_and_usage(api, profile):
    from generation.patch_repair import permission
    from generation.service import generate
    from tests.test_edit_recovery import corrected, edit_case

    base, response = edit_case(profile)
    policy = permission(response, files=base["files"], base_revision="base", profile=profile)
    request = request_for_api(operation="edit", generation_profile=profile, files=base["files"], patch_repair=policy)
    assert request["codex_api"]["payload"]["output_schema"] == response_schema(request)
    assert "rejected_patches" in request["codex_api"]["payload"]["input"]
    codex_api.fetch(request)
    reply = corrected(policy, base)
    api.finish(request["codex_api"]["id"], reply)
    result = generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result["response"] == reply and result["usage"]
    assert api.inferences == 1


def test_lost_submission_reply_retrieves_same_uuid_without_second_put(api, monkeypatch):
    request = request_for_api()
    original = api.__class__.__call__

    def lost(self, req):
        response = original(self, req)
        if req.method == "PUT":
            raise httpx.ReadTimeout("lost reply")
        return response

    monkeypatch.setattr(api.__class__, "__call__", lost)
    with pytest.raises(GenerationPending):
        codex_api.fetch(request)
    assert codex_api.fetch(request)["state"] == "queued"
    assert len(api.jobs) == 1
    assert sum(method == "PUT" for method, _ in api.calls) == 1


@pytest.mark.parametrize("variable,value", [("GAMEFORGE_CODEX_API_URL", "https://changed.test"),
                                             ("GAMEFORGE_CODEX_API_KEY", "y" * 32)])
def test_changed_origin_or_principal_never_reposts(api, monkeypatch, variable, value):
    request = request_for_api()
    api.calls.clear()
    monkeypatch.setenv(variable, value)
    with pytest.raises(GenerationPending) as error:
        codex_api.fetch(request)
    assert error.value.operator_required and not api.calls


@pytest.mark.parametrize("tamper", ["id", "payload_hash", "receipt_hash", "model", "raw_response"])
def test_corrupt_or_cross_job_receipt_stays_pending(api, tamper):
    request = request_for_api()
    codex_api.fetch(request)
    ident = request["codex_api"]["id"]
    api.finish(ident, fixture_response())
    row = api.jobs[ident]
    if tamper in {"model", "raw_response"}:
        row["receipt"][tamper] = "wrong"
        row["receipt_hash"] = digest(row["receipt"])
    else:
        row[tamper] = "wrong"
    with pytest.raises(GenerationPending):
        codex_api.unpack(codex_api.fetch(request), ident)
    assert api.inferences == 1


def test_unknown_retains_partial_and_usage(api):
    request = request_for_api()
    codex_api.fetch(request)
    ident = request["codex_api"]["id"]
    api.finish(ident, state="unknown")
    with pytest.raises(GenerationError) as error:
        codex_api.unpack(codex_api.fetch(request), ident)
    assert error.value.outcome_unknown
    assert error.value.raw_response == "partial" and error.value.usage["output_tokens"] == 50


def test_unknown_cannot_claim_known_outcome(api):
    request = request_for_api()
    codex_api.fetch(request)
    ident = request["codex_api"]["id"]
    api.finish(ident, state="unknown")
    row = api.jobs[ident]
    row["receipt"]["error"]["outcome_unknown"] = False
    row["receipt_hash"] = digest(row["receipt"])
    with pytest.raises(GenerationPending):
        codex_api.unpack(codex_api.fetch(request), ident)


def test_early_cancel_is_tombstone_without_put_or_model(api):
    request = request_for_api()
    with pytest.raises(GenerationError) as error:
        codex_api.unpack(codex_api.fetch(request, cancel=True), request["codex_api"]["id"])
    assert error.value.code == "cancelled" and not error.value.outcome_unknown
    assert not api.inferences and all(method != "PUT" for method, _ in api.calls)


@pytest.mark.parametrize("status", [302, 401, 403, 409, 429, 503, 507])
def test_api_outage_preserves_identity(api, status):
    request = request_for_api()
    api.fail = status
    with pytest.raises(GenerationPending) as error:
        codex_api.fetch(request)
    assert error.value.operator_required == (status in {302, 401, 403, 409, 507})
    assert api.inferences == 0


def test_web_reads_only_non_secret_fresh_catalog(api, monkeypatch):
    monkeypatch.delenv("GAMEFORGE_CODEX_API_KEY")
    assert codex_api.available_models()[0]["id"] == "gpt-6-sol"
    import os
    from pathlib import Path

    path = Path(os.environ["GAMEFORGE_CODEX_API_CATALOG"])
    data = json.loads(path.read_text())
    data["checked_at"] -= 181
    path.write_text(json.dumps(data))
    assert codex_api.available_models() == []


@pytest.fixture
def run(api, settings, db):
    settings.GAMEFORGE_PROVIDER = "relay"
    settings.GAMEFORGE_MODEL = "qwen38"
    settings.GAMEFORGE_PRO_PROVIDER = "codex_api"
    settings.GAMEFORGE_PRO_ENABLED = True
    settings.GAMEFORGE_PRO_ACCESS = "local"
    settings.GAMEFORGE_LOCAL_ONLY = True
    settings.GAMEFORGE_APP_ORIGIN = "http://127.0.0.1:8000"
    user = User.objects.create_user(username="api_operator", is_staff=True)
    with patch("studio.services.schedule"), patch("studio.tasks.process_run.delay"):
        result = create_run(Chat.objects.create(owner=user), {
            "prompt": "Сделай игру", "idempotency_key": "one", "model_profile": "pro", "model_call_limit": 1,
        })
        assert result.generation_strategy == "pro" and result.planning_required
        result.planning_required = False  # Isolate receipt recovery from multi-stage game design.
        result.save(update_fields=["planning_required"])
        with patch("validation.service.validate", return_value={
            "status": "passed", "findings": [], "facts": [], "environment": {"version": "test"},
        }), patch("validation.service.environment_identity", return_value={"version": "test"}):
            yield result


@pytest.mark.django_db(transaction=True)
def test_crash_deadline_and_lost_commit_only_retrieve_existing_job(run, api):
    process_run(str(run.id))
    inv = run.invocations.get()
    assert inv.request["codex_api"]["id"] == str(inv.id) and inv.state == "sent"
    run.refresh_from_db()
    run.status = "generating"
    run.lease_until = timezone.now() - timedelta(seconds=5)
    run.model_call_deadline = timezone.now() - timedelta(seconds=1)
    run.save()
    recover_expired()
    process_run(str(run.id))
    assert run.invocations.count() == 1
    api.finish(str(inv.id), fixture_response())
    with patch("studio.tasks.settle_invocation", side_effect=RuntimeError("DB lost")):
        process_run(str(run.id))
    process_run(str(run.id))
    run.refresh_from_db()
    inv.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert inv.usage["output_tokens"] == 50 and inv.raw_response
    assert api.inferences == 1 and run.invocations.count() == 1


@pytest.mark.django_db(transaction=True)
def test_cancelled_run_preserves_late_receipt_without_applying_game(run, api):
    process_run(str(run.id))
    inv = run.invocations.get()
    cancel_run(run)
    api.finish(str(inv.id), fixture_response())
    reconcile_relay_cancellations()
    inv.refresh_from_db()
    assert inv.usage["output_tokens"] == 50 and inv.raw_response
    assert not Revision.objects.filter(run=run).exists()
    assert api.inferences == 1


@pytest.mark.django_db(transaction=True)
def test_remote_pro_obeys_same_user_boundary_and_keeps_local_codex_option(run, api, settings):
    client = WebClient()
    client.force_login(run.chat.owner)
    caps = client.get('/api/session/').json()['capabilities']
    assert caps['model_profiles'][0]['provider'] == 'codex_api'
    assert caps['model_profiles'][0]['available']
    settings.GAMEFORGE_LOCAL_ONLY = False
    response = client.post(f'/api/chats/{run.chat_id}/runs/', {
        'prompt': 'new', 'idempotency_key': 'new', 'model_profile': 'pro',
    }, content_type='application/json')
    assert response.status_code in {403, 409}
    assert Invocation.objects.count() == 0
    settings.GAMEFORGE_LOCAL_ONLY = True
    settings.GAMEFORGE_PRO_PROVIDER = 'codex'
    with patch('generation.providers.codex.available_models', return_value=[{'id':'gpt-6-sol'}]), \
         patch('generation.providers.codex.verify_cli_contract'):
        caps = client.get('/api/session/').json()['capabilities']
    assert caps['model_profiles'][0]['provider'] == 'codex' and caps['model_profiles'][0]['available']


@pytest.mark.django_db(transaction=True)
def test_cloud_api_pro_requires_https_and_explicit_user_allowlist(run, settings):
    settings.GAMEFORGE_LOCAL_ONLY = False
    settings.GAMEFORGE_APP_ORIGIN = 'https://cloud.test'
    settings.GAMEFORGE_PRO_ACCESS = 'restricted'
    settings.GAMEFORGE_PRO_USER_IDS = frozenset({run.chat.owner_id})
    settings.ALLOWED_HOSTS = ['cloud.test']
    client = WebClient()
    client.force_login(run.chat.owner)
    def pro(secure):
        return client.get('/api/session/', secure=secure, HTTP_HOST='cloud.test').json()[
            'capabilities']['model_profiles'][0]['available']
    assert pro(True) and not pro(False)
    settings.GAMEFORGE_PRO_USER_IDS = frozenset()
    assert not pro(True)


@pytest.mark.django_db(transaction=True)
def test_cancel_delivery_wait_survives_access_failure_and_expired_lease(run, api):
    process_run(str(run.id))
    inv = run.invocations.get()
    cancel_run(run)
    api.fail = 401
    reconcile_relay_cancellations()
    recover_expired()
    inv.refresh_from_db()
    assert inv.state == 'sent' and inv.provider_metadata['codex_api_cancel_wait']['operator_required']
    api.fail = None
    inv.provider_metadata['codex_api_cancel_wait']['retry_at'] = 0
    inv.save(update_fields=['provider_metadata'])
    reconcile_relay_cancellations()
    inv.refresh_from_db()
    assert inv.state == 'failed' and inv.cost_usd == 0
    assert not Revision.objects.exists() and api.inferences == 0


@pytest.mark.parametrize('operation', ['visual_review', 'visual_patch'])
@pytest.mark.parametrize('profile', ['full', 'compact'])
def test_remote_visual_payload_uses_same_bounded_schema_and_image(api, operation, profile):
    from tests.test_visual_review import visual_request

    request = request_for_api(**visual_request(operation), generation_profile=profile)
    payload = request['codex_api']['payload']
    assert payload['output_schema'] == response_schema(request)
    assert payload['effort'] == 'medium'
    assert payload['images'] == [{k: request['preview_image'][k] for k in ('mime', 'data')}]
    assert not api.jobs
