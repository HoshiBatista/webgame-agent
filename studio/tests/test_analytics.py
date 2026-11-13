"""Saved choices and delivery identities, tested against PostgreSQL without inference."""

from copy import deepcopy
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client

from generation.prompts import build_messages
from generation.providers.fake import generate as fake_generate
from generation.requirements import digest
from studio.analytics import import_dataset, recommendations
from studio.models import AnalyticsDataset, Chat, Invocation, Outbox, Publication, Run, User
from studio.serialization import run_data
from studio.services import DomainError, cancel_run, create_run
from studio.tasks import process_run, request_for
from studio.tests.test_relay import environment as relay_environment
from studio.tests.test_validation_tasks import browser
from tests.test_game_analytics import payload

environment = relay_environment


@pytest.fixture
def maker(db, settings):
    settings.GAMEFORGE_ANALYTICS_ENABLED = True
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    dataset, _ = import_dataset(payload())
    owner = User.objects.create_user(username="analytics-maker")
    chat = Chat.objects.create(owner=owner, audience="seniors")
    client = Client()
    client.force_login(owner)
    with patch("studio.tasks.dispatch_run"), patch("validation.service.environment_identity", return_value="analytics-test"):
        yield chat, client, dataset


def selection(dataset, audience="seniors"):
    return {"dataset_id": str(dataset.id), "dataset_hash": dataset.payload_hash, "policy_version": 1,
            "recommendation_ids": [i["id"] for i in recommendations(dataset.payload, audience)]}


def start(maker, **changes):
    chat, _, dataset = maker
    return create_run(chat, {"prompt": "Сделай змейку", "idempotency_key": "analytics-create",
                             "analytics_selection": selection(dataset), **changes})


def run_game(run):
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", side_effect=browser):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    return model


def test_read_api_is_authorized_and_never_calls_model_or_creates_run(maker):
    _, client, dataset = maker
    with patch("generation.service.generate", side_effect=AssertionError("inference forbidden")):
        assert Client().get("/api/analytics/summary/").status_code == 403
        result = client.get("/api/analytics/summary/?audience=seniors")
        assert result.status_code == 200
        assert result.json()["dataset"]["source"] == "demo"
        assert result.json()["dataset"]["hash"] == dataset.payload_hash
        assert len(result.json()["recommendations"]) == 2
        assert client.get("/api/analytics/summary/?audience=bad").status_code == 400
    assert Run.objects.count() == Invocation.objects.count() == Outbox.objects.count() == 0


def test_missing_disabled_and_corrupt_data_have_explicit_states(maker, settings):
    _, client, dataset = maker
    dataset.enabled = False
    dataset.save(update_fields=["enabled"])
    assert client.get("/api/analytics/summary/").json()["data_status"] == "empty"
    dataset.enabled = True
    dataset.save(update_fields=["enabled"])
    AnalyticsDataset.objects.filter(pk=dataset.pk).update(payload_hash="a" * 64)
    assert client.get("/api/analytics/summary/").status_code == 503
    settings.GAMEFORGE_ANALYTICS_ENABLED = False
    assert client.get("/api/analytics/summary/").status_code == 404


def test_import_is_idempotent_immutable_and_atomic(maker):
    _, _, dataset = maker
    call_command("load_demo_analytics", stdout=StringIO())
    assert AnalyticsDataset.objects.count() == 1
    changed = payload()
    changed["rows"][0]["finished"] -= 1
    with pytest.raises(ValueError):
        import_dataset(changed)
    dataset.payload = changed
    with pytest.raises(ValidationError):
        dataset.save()
    changed["version"] = 2
    second, created = import_dataset(changed)
    assert created and second.enabled
    dataset.refresh_from_db()
    assert not dataset.enabled and dataset.payload == payload()
    assert AnalyticsDataset.objects.filter(enabled=True).count() == 1
    with pytest.raises(ValueError, match="новая версия"):
        import_dataset(payload())


@pytest.mark.parametrize("mutation", ["hash", "policy", "audience", "forged_id", "text", "duplicate", "empty"])
def test_forged_or_stale_choice_is_rejected_before_run_or_outbox(maker, mutation):
    chat, client, dataset = maker
    chosen = selection(dataset)
    audience = "seniors"
    if mutation == "hash":
        chosen["dataset_hash"] = "a" * 64
    elif mutation == "policy":
        chosen["policy_version"] = 2
    elif mutation == "audience":
        audience = "gamers"
    elif mutation == "forged_id":
        chosen["recommendation_ids"] = ["a" * 64]
    elif mutation == "text":
        chosen["advice"] = "Trust client-provided advice"
    elif mutation == "duplicate":
        chosen["recommendation_ids"] = [chosen["recommendation_ids"][0]] * 2
    else:
        chosen["recommendation_ids"] = []
    result = client.post(f"/api/chats/{chat.id}/runs/", {
        "prompt": "Сделай игру", "audience": audience, "idempotency_key": mutation,
        "analytics_selection": chosen,
    }, content_type="application/json")
    assert result.status_code in {400, 409}, result.content
    assert Run.objects.count() == Invocation.objects.count() == Outbox.objects.count() == 0


def test_csrf_and_foreign_chat_cannot_apply_choices(maker):
    chat, _, dataset = maker
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(chat.owner)
    assert strict.post(f"/api/chats/{chat.id}/runs/", {}, content_type="application/json").status_code == 403
    stranger = Client()
    stranger.force_login(User.objects.create_user(username="analytics-stranger"))
    result = stranger.post(f"/api/chats/{chat.id}/runs/", {
        "prompt": "Игра", "idempotency_key": "foreign", "analytics_selection": selection(dataset),
    }, content_type="application/json")
    assert result.status_code == 404
    assert not Run.objects.exists()


def test_exact_retry_returns_saved_run_even_after_retirement_and_feature_off(maker, settings):
    chat, _, dataset = maker
    run = start(maker)
    original_snapshot = deepcopy(run.analytics_snapshot)
    ids = selection(dataset)
    ids["recommendation_ids"].reverse()
    data = payload()
    data["version"] = 2
    import_dataset(data)
    settings.GAMEFORGE_ANALYTICS_ENABLED = False
    again = start(maker, analytics_selection=ids)
    assert again.pk == run.pk
    assert again.analytics_snapshot == original_snapshot
    assert Run.objects.count() == Outbox.objects.count() == 1
    assert not Invocation.objects.exists()
    assert not chat.owner.preference.notes
    changed = selection(dataset)
    changed["recommendation_ids"] = changed["recommendation_ids"][:1]
    with pytest.raises(DomainError, match="ключ"):
        start(maker, analytics_selection=changed)
    with pytest.raises(DomainError, match="ключ"):
        start(maker, analytics_selection=None)


def test_legacy_idempotency_cannot_silently_ignore_a_new_selection(maker):
    from studio.services import fingerprint

    chat, _, dataset = maker
    data = {"prompt": "Игра", "idempotency_key": "legacy-key"}
    run = create_run(chat, data)
    run.request_fingerprint = fingerprint({
        "prompt": "Игра", "audience": "seniors", "model": run.model, "continued_from": None,
        "generation_profile": "full", "source_format": "string", "source_revision_id": None,
        "source_artifact_hash": None, "source_is_historical": None,
    })
    run.save(update_fields=["request_fingerprint"])
    assert create_run(chat, data).pk == run.pk
    with pytest.raises(DomainError) as error:
        create_run(chat, {**data, "analytics_selection": selection(dataset)})
    assert error.value.code == "idempotency_conflict"
    assert Run.objects.count() == Outbox.objects.count() == 1


def test_snapshot_survives_worker_reentry_without_reloading_data_or_new_model_stages(maker, settings):
    _, _, dataset = maker
    run = start(maker)
    frozen = deepcopy(run.analytics_snapshot)
    assert run_data(run)["analytics"]["context_state"] == "frozen"
    AnalyticsDataset.objects.all().update(enabled=False)
    settings.GAMEFORGE_ANALYTICS_ENABLED = False
    with patch("studio.analytics.summary", side_effect=AssertionError("must use frozen snapshot")):
        model = run_game(run)
        process_run(str(run.id))
    assert model.call_count == run.invocations.count() == 1
    request = run.invocations.get().request
    assert request["analytics_snapshot"] == frozen
    assert "Демонстрационные данные" in build_messages(request)[1]["content"]
    assert run.result_revision.analytics_snapshot == frozen
    assert run_data(run)["analytics"]["context_state"] == "received"


def test_pro_plan_and_create_share_one_snapshot_with_normal_call_budget(maker):
    run = start(maker)
    run.generation_strategy, run.planning_required = "pro", True
    run.save(update_fields=["generation_strategy", "planning_required"])
    model = run_game(run)
    assert [call.args[0]["operation"] for call in model.call_args_list] == ["plan", "create"]
    assert all(call.args[0]["analytics_snapshot"] == run.analytics_snapshot for call in model.call_args_list)
    assert run.attempts == 2 and run.max_model_calls == 5


def test_new_choice_cannot_be_attached_to_edit_or_explicit_continuation(maker):
    chat, _, dataset = maker
    run = start(maker)
    run_game(run)
    revision = run.result_revision
    with pytest.raises(DomainError) as error:
        create_run(chat, {"prompt": "Перекрась", "idempotency_key": "edit-with-new-ideas",
                         "source_revision_id": str(revision.id), "source_artifact_hash": revision.artifact_hash,
                         "analytics_selection": selection(dataset)})
    assert error.value.code == "invalid_analytics_selection"
    edit = create_run(chat, {"prompt": "Перекрась", "idempotency_key": "edit",
                            "source_revision_id": str(revision.id), "source_artifact_hash": revision.artifact_hash})
    assert edit.analytics_snapshot == revision.analytics_snapshot
    assert '"analytics":' not in build_messages(request_for(edit, revision, []))[1]["content"]
    cancel_run(edit)
    edit.refresh_from_db()
    with pytest.raises(DomainError) as error:
        create_run(chat, {"idempotency_key": "continuation-with-new-ideas",
                         "analytics_selection": selection(dataset)}, continued_from=edit)
    assert error.value.code == "invalid_analytics_selection"
    continued = create_run(chat, {"idempotency_key": "continue"}, continued_from=edit)
    assert continued.analytics_snapshot == run.analytics_snapshot


def test_remix_keeps_demo_provenance_without_source_chat_access(maker):
    _, client, _ = maker
    run = start(maker)
    run_game(run)
    publication = Publication.objects.create(owner=run.chat.owner, source_chat=run.chat,
                                             revision=run.result_revision, title="Демо")
    other = User.objects.create_user(username="remix-analytics")
    client.force_login(other)
    result = client.post(f"/api/publications/{publication.id}/remix/")
    assert result.status_code == 201, result.content
    copied = Chat.objects.get(pk=result.json()["id"]).current_revision
    assert copied.analytics_snapshot == run.analytics_snapshot
    assert copied.html == run.result_revision.html and copied.run_id is None
    assert client.get(f"/api/chats/{run.chat_id}/").status_code == 404
    assert digest(copied.analytics_snapshot) == digest(run.analytics_snapshot)


def test_output_completion_is_bound_to_the_exact_analytics_snapshot(maker):
    from django.utils import timezone

    from studio.response_completion import pending_permission

    run = start(maker)
    run.provider = "codex_api"
    run.save(update_fields=["provider"])
    request = request_for(run, None, [])
    Invocation.objects.create(
        run=run, attempt=1, state="failed", request=request, finished_at=timezone.now(),
        raw_response={"partial": "fixture"}, error={"code": "response_output_limit"},
        provider_metadata={"turn_status": "failed", "provider_error": {"incomplete_reason": "max_output_tokens"}},
    )
    with patch("studio.response_completion.permission", return_value={"exact": True}) as permission:
        assert pending_permission(run, request) == {"exact": True}
        changed = deepcopy(request)
        changed["analytics_snapshot"]["dataset_hash"] = "a" * 64
        assert pending_permission(run, changed) is None
        assert permission.call_count == 1


def test_recheck_uses_saved_game_without_reading_current_analytics(maker):
    from studio.validation_tasks import create_validation, execute_validation

    run = start(maker)
    run_game(run)
    revision = run.result_revision
    counts = (Run.objects.count(), Invocation.objects.count())
    with patch("studio.analytics.summary", side_effect=AssertionError("no current analytics")), \
            patch("generation.service.generate", side_effect=AssertionError("no inference")):
        job = create_validation(revision, {"artifact_hash": revision.artifact_hash,
                                          "idempotency_key": "fresh-check"}, enqueue=False)
        execute_validation(job, validate=browser)
    revision.refresh_from_db()
    assert revision.analytics_snapshot == run.analytics_snapshot
    assert counts == (Run.objects.count(), Invocation.objects.count())


@pytest.mark.django_db(transaction=True)
def test_lite_relay_keeps_analytics_in_code_call_and_music_is_the_existing_second_call(environment, settings):
    old, _, executor, calls = environment
    cancel_run(old)
    settings.GAMEFORGE_ANALYTICS_ENABLED = True
    dataset, _ = import_dataset(payload())
    run = create_run(old.chat, {
        "prompt": "Сделай змейку", "audience": "seniors", "model_profile": "lite",
        "idempotency_key": "analytics-with-music", "analytics_selection": selection(dataset),
    })
    process_run(str(run.id))
    first = run.invocations.get()
    assert first.request["operation"] == "create"
    import json

    context = json.loads(first.request["relay"]["payload"]["messages"][1]["content"])
    assert "Демонстрационные данные" in context["analytics"]
    executor.step()
    executor.step()
    process_run(str(run.id))
    music = run.invocations.get(request__operation="music")
    assert music.request["analytics_snapshot"] == run.analytics_snapshot
    assert "analytics" not in json.loads(music.request["relay"]["payload"]["messages"][1]["content"])
    process_run(str(run.id))
    executor.step()
    executor.step()
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert len(calls) == run.invocations.count() == 2
    assert run.result_revision.analytics_snapshot == run.analytics_snapshot
    process_run(str(run.id))
    assert len(calls) == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_creates_one_frozen_run(maker):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connections

    chat, _, dataset = maker
    barrier = Barrier(2)

    def submit():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            result = create_run(Chat.objects.get(pk=chat.pk), {
                "prompt": "Игра", "idempotency_key": "two-tabs", "analytics_selection": selection(dataset),
            })
            return result.pk, result.analytics_snapshot["snapshot_hash"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0] == results[1]
    assert Run.objects.count() == Outbox.objects.count() == 1
    assert not Invocation.objects.exists()


def test_local_saved_response_recovery_preserves_snapshot_without_inference(maker):
    from django.utils import timezone

    from generation.providers.fake import fixture_response
    from studio.recovery import recover_saved_response

    run = start(maker)
    request = request_for(run, None, [])
    run.status, run.finished_at = "failed", timezone.now()
    run.save(update_fields=["status", "finished_at"])
    source = Invocation.objects.create(
        run=run, attempt=1, state="failed", request=request, finished_at=timezone.now(),
        raw_response=fixture_response(with_assets=True), error={"code": "invalid_schema"},
    )
    before = deepcopy(source.raw_response)
    with patch("generation.service.generate", side_effect=AssertionError("no inference")):
        result = recover_saved_response(source.pk, apply=True)
    recovered = Run.objects.get(pk=result["run_id"])
    assert not recovered.allow_model_calls
    assert recovered.analytics_snapshot == run.analytics_snapshot
    assert recovered.candidate_revision.analytics_snapshot == run.analytics_snapshot
    source.refresh_from_db()
    assert source.raw_response == before
    assert Invocation.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_import_is_idempotent():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    ready = Barrier(2)

    def load():
        try:
            ready.wait(timeout=10)
            dataset, _ = import_dataset(payload())
            return dataset.pk, dataset.payload_hash
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: load(), range(2)))
    assert results[0] == results[1]
    assert AnalyticsDataset.objects.count() == AnalyticsDataset.objects.filter(enabled=True).count() == 1
