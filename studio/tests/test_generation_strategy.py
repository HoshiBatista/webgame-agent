"""Saved design stages and provider boundaries; every model/validator is a local double."""

from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from generation.errors import GenerationError
from generation.providers.fake import generate as fake_generate
from studio.models import Chat, Run, User
from studio.serialization import chat_data, run_data
from studio.services import create_run, reserve_invocation
from studio.tasks import process_run, recover_expired, request_for
from studio.tests.test_staged_generation import PASS, SYNTAX


@pytest.fixture
def chat(settings, request):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3
    identity = nullcontext() if request.node.get_closest_marker("browser") else patch(
        "validation.service.environment_identity", return_value="strategy-test",
    )
    with (patch("studio.services.schedule"), patch("studio.tasks.dispatch_outbox"),
          patch("studio.tasks.dispatch_run"),
          identity):
        yield Chat.objects.create(owner=User.objects.create_user(username="strategy-maker"))


def planned_run(chat, **kwargs):
    run = create_run(chat, {"prompt": "Сделай бродилку", "idempotency_key": "plan", **kwargs})
    # Exercise the real queue using its zero-cost provider, never a live Sol session.
    run.generation_strategy = "pro"
    run.planning_required = True
    run.save(update_fields=["generation_strategy", "planning_required"])
    return run


@pytest.mark.django_db(transaction=True)
def test_plan_is_stored_before_code_and_never_replanned_during_repair(chat):
    run = planned_run(chat)
    requests = []

    def model(request, **kwargs):
        requests.append(request)
        if request["operation"] != "plan":
            assert Run.objects.get(pk=run.id).game_plan == request["game_plan"]
            assert request["game_plan"]
        return fake_generate(request, **kwargs)

    with (patch("generation.service.generate", side_effect=model),
          patch("validation.service.validate", side_effect=[SYNTAX, PASS]) as browser):
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert [r["operation"] for r in requests] == ["plan", "create", "repair"]
    assert all(r["reasoning_effort"] == "high" for r in requests)
    assert all(r["presentation_policy"] == 1 for r in requests)
    assert set(run.game_plan["presentation"]) == {"art_direction", "motion"}
    assert requests[1]["game_plan"] == requests[2]["game_plan"] == run.game_plan
    assert run.attempts == run.invocations.count() == 3 and run.max_model_calls == 5
    assert browser.call_count == 2 and chat.revisions.count() == 2
    assert run.invocations.get(request__operation="plan").revision_id is None
    assert run.chat_messages.filter(role="assistant").count() == 1
    assert "Тестовый замысел" not in run.chat_messages.get(role="assistant").content


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("crash_after_save", [False, True])
def test_returned_plan_survives_crash_without_second_planning_call(chat, crash_after_save):
    from studio.tasks import event

    run = planned_run(chat)

    def interrupted_event(current, kind, *args, **kwargs):
        if kind == "planned" and not crash_after_save:
            raise KeyboardInterrupt
        return event(current, kind, *args, **kwargs)

    def interrupted_reservation(current, request):
        if request["operation"] == "create" and crash_after_save:
            raise KeyboardInterrupt
        return reserve_invocation(current, request)

    with (patch("generation.service.generate", side_effect=fake_generate) as model,
          patch("studio.tasks.event", side_effect=interrupted_event),
          patch("studio.tasks.reserve_invocation", side_effect=interrupted_reservation)):
        with pytest.raises(KeyboardInterrupt):
            process_run(str(run.id))
    assert model.call_count == 1
    run.refresh_from_db()
    receipt = run.invocations.get()
    assert receipt.state == ("settled" if crash_after_save else "returned")
    assert bool(run.game_plan) == crash_after_save
    run.lease_until = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["lease_until"])
    recover_expired()
    with (patch("generation.service.generate", side_effect=fake_generate) as model,
          patch("validation.service.validate", return_value=PASS)):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert model.call_count == 1 and model.call_args.args[0]["operation"] == "create"
    assert run.invocations.count() == 2 and run.game_plan


@pytest.mark.django_db(transaction=True)
def test_budget_one_saves_only_plan_then_explicit_continuation_reuses_it(chat):
    run = planned_run(chat, model_call_limit=1)
    with (patch("generation.service.generate", side_effect=fake_generate) as model,
          patch("validation.service.validate") as browser):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.error["code"] == "plan_without_game"
    assert run.game_plan and not run.candidate_revision_id
    assert model.call_count == 1
    browser.assert_not_called()
    assert "создание кода ещё не завершено" in run.chat_messages.get(role="assistant").content
    continued = create_run(chat, {"idempotency_key": "continue", "model_call_limit": 1}, continued_from=run)
    assert continued.game_plan == run.game_plan and not continued.planning_required
    with (patch("generation.service.generate", side_effect=fake_generate) as model,
          patch("validation.service.validate", return_value=PASS)):
        process_run(str(continued.id))
    continued.refresh_from_db()
    assert continued.status == "succeeded", continued.error
    assert model.call_count == 1 and model.call_args.args[0]["operation"] == "create"


@pytest.mark.django_db(transaction=True)
def test_unknown_planner_result_never_repeats_or_starts_code(chat):
    run = planned_run(chat)
    with patch("generation.service.generate", side_effect=GenerationError(
        "connection_lost", "Unknown receipt", outcome_unknown=True,
    )) as model:
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unknown" and not run.game_plan
    assert model.call_count == 1 and not chat.revisions.exists()
    assert run.invocations.get().state == "unknown"


@pytest.mark.django_db(transaction=True)
def test_deadline_after_plan_prevents_create(chat):
    run = planned_run(chat, model_call_deadline=(timezone.now() + timedelta(minutes=1)).isoformat())

    def planner(request, **kwargs):
        Run.objects.filter(pk=run.id).update(model_call_deadline=timezone.now() - timedelta(seconds=1))
        return fake_generate(request, **kwargs)

    with patch("generation.service.generate", side_effect=planner) as model:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.game_plan and run.status == "needs_attention" and run.error["code"] == "model_deadline"
    assert model.call_count == 1 and not chat.revisions.exists()


@pytest.mark.django_db(transaction=True)
def test_check_only_edit_keeps_draft_visible_and_recheck_uses_no_model(chat):
    first = create_run(chat, {"prompt": "Game", "idempotency_key": "first", "model_call_limit": 1})
    with (patch("generation.service.generate", side_effect=fake_generate),
          patch("validation.service.validate", return_value=SYNTAX)):
        process_run(str(first.id))
    first.refresh_from_db()
    source = first.candidate_revision
    run = create_run(chat, {"prompt": "Исправь управление", "idempotency_key": "edit",
                            "source_revision_id": str(source.id), "source_artifact_hash": source.artifact_hash})

    def checks_only(request, **kwargs):
        result = fake_generate(request, **kwargs)
        result["response"]["patches"] = []
        result["response"]["checks"][0]["expect"]["value"] = "unrelated"
        return result

    with (patch("generation.service.generate", side_effect=checks_only),
          patch("validation.service.validate") as browser):
        process_run(str(run.id))
    browser.assert_not_called()
    run.refresh_from_db()
    chat.refresh_from_db()
    assert run.error["code"] == "test_only_change" and not run.candidate_revision_id
    assert chat.current_revision_id is None
    serialized = chat_data(chat, detail=True)
    assert serialized["candidate_revision"]["id"] == str(source.id)
    assert run_data(run)["can_recheck"] and not run_data(run)["can_confirm"]
    assert "только проверки" in run.chat_messages.get(role="assistant").content
    recheck = create_run(chat, {"idempotency_key": "recheck"}, continued_from=run, check_only=True)
    with (patch("generation.service.generate") as model,
          patch("validation.service.validate", return_value=PASS)):
        process_run(str(recheck.id))
    recheck.refresh_from_db()
    model.assert_not_called()
    assert recheck.status == "succeeded" and recheck.result_revision_id == source.id
    source.refresh_from_db()
    assert source.checks == first.candidate_revision.checks
    assert not recheck.invocations.exists()


@pytest.mark.django_db
def test_profile_selection_sets_plan_policy_and_pro_effort_without_contacting_model(chat, settings):
    settings.GAMEFORGE_PROVIDER = "codex"
    settings.GAMEFORGE_MODEL = "gpt-6-sol"
    pro = create_run(chat, {"prompt": "Подробное описание " * 50, "idempotency_key": "pro"})
    assert pro.generation_strategy == "pro" and pro.planning_required
    req = request_for(pro, None, [])
    assert req["operation"] == "plan" and req["reasoning_effort"] == "high"
    assert pro.max_model_calls == 5 and not pro.invocations.exists()


@pytest.mark.django_db(transaction=True)
def test_cancelled_planner_receipt_is_accounted_but_not_applied(chat):
    from studio.services import cancel_run

    run = planned_run(chat)

    def planner(request, **kwargs):
        result = fake_generate(request, **kwargs)
        cancel_run(Run.objects.get(pk=run.id))
        return result

    with patch('generation.service.generate', side_effect=planner) as model:
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == 'cancelled' and not run.game_plan
    assert model.call_count == 1 and not chat.revisions.exists()
    assert run.invocations.get().state == 'returned'


@pytest.mark.django_db(transaction=True)
def test_invalid_plan_consumes_budget_without_creating_artifact(chat):
    run = planned_run(chat, model_call_limit=2)
    invalid = fake_generate({'operation': 'plan'}, on_event=lambda _: None, is_cancelled=lambda: False)
    invalid['response']['plan'] = {}
    with patch('generation.providers.fake.generate', return_value=invalid) as model:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == 'needs_attention' and not run.game_plan
    assert model.call_count == 2 and run.invocations.count() == 2
    assert not chat.revisions.exists()
    assert set(run.invocations.values_list('state', flat=True)) == {'failed'}


@pytest.mark.django_db(transaction=True)
def test_pro_feedback_frame_requires_current_report_identity(chat):
    from tests.test_generation_planning import screenshot_request

    run = create_run(chat, {'prompt': 'game', 'idempotency_key': 'image', 'model_call_limit': 1})
    run.generation_strategy = 'pro'
    run.save(update_fields=['generation_strategy'])
    with (patch('generation.service.generate', side_effect=fake_generate),
          patch('validation.service.validate', return_value=SYNTAX)):
        process_run(str(run.id))
    run.refresh_from_db()
    candidate = run.candidate_revision
    report = candidate.reports.get()
    report.screenshot_base64 = screenshot_request()['preview_image']['data']
    report.save(update_fields=['screenshot_base64'])
    request = request_for(run, candidate, report.findings)
    assert request['preview_image']['report_id'] == report.id
    assert request['preview_image']['artifact_hash'] == candidate.artifact_hash
    report.identity = 'obsolete-validator'
    report.save(update_fields=['identity'])
    assert 'preview_image' not in request_for(run, candidate, report.findings)


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("profile", ["full", "compact"])
def test_plan_to_sources_to_real_browser_finishes_without_live_model(chat, profile):
    from tests.test_compact_generation import compact_response

    run = planned_run(chat, generation_profile=profile,
                      source_format="lines" if profile == "compact" else "string", model_call_limit=2)

    def model(request, **kwargs):
        if profile == "compact" and request["operation"] == "create":
            response = compact_response()
            response["source_lines"] = response.pop("source").split("\n")
            return {"response": response, "usage": {"input_tokens": 0, "output_tokens": 0}}
        return fake_generate(request, **kwargs)

    with patch("generation.providers.fake.generate", side_effect=model) as provider:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert provider.call_count == 2
    assert run.game_plan and run.result_revision.generation_profile == profile
    report = run.result_revision.reports.get()
    assert report.status == "passed" and report.assessment["gates_passed"]
    assert report.facts and report.assessment["artifact_evidence"]
