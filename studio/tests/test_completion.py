from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import Client

from generation.providers.fake import fixture_response
from generation.providers.fake import generate as fake_generate
from studio.models import Chat, Invocation, Run, User
from studio.serialization import run_data
from studio.services import budget_snapshot, create_run, reserve_invocation, settle_invocation
from studio.tasks import process_run


@pytest.fixture
def maker(settings):
    settings.GAMEFORGE_RUN_INLINE = False
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    settings.GAMEFORGE_LEASE_SECONDS = 100
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3
    with patch("studio.services.schedule"), patch("studio.tasks.dispatch_outbox"), patch("studio.tasks.dispatch_run"), \
            patch("validation.service.environment_identity", return_value="completion-test"):
        user = User.objects.create_user(username="completion-maker")
        chat = Chat.objects.create(owner=user)
        client = Client()
        client.force_login(user)
        yield chat, client


def start(chat, key="create"):
    return create_run(chat, {"prompt": "Небольшая игра", "idempotency_key": key})


def uncertain(gates=True):
    return {"status": "unverified", "environment": "completion-test", "findings": [{"code": "invalid_check", "check_id": "outcome",
                                                   "message": "Неверный selector наблюдения"}],
            "gates": {"syntax": gates, "runtime": gates, "surface": gates},
            "stages": [{"stage": "syntax", "status": "passed"}],
            "facts": [{**{k: c[k] for k in ("id", "category", "requirement", "viewport")},
                       "status": "unverified" if c["id"] == "outcome" else "passed",
                       "surface": {"canvases": [{"visible": True, "width": 300, "height": 300}], "overflow": False}}
                      for c in fixture_response()["checks"]]}


PASS = {"status": "passed", "environment": "completion-test", "findings": [], "facts": [], "gates": {"syntax": True, "runtime": True, "surface": True}}


@pytest.mark.django_db
@pytest.mark.parametrize("last_status", ["unverified", "needs_attention", "failed"])
def test_uncertainty_finishes_after_scenario_review_without_source_repair(maker, last_status):
    chat, client = maker
    run = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", return_value=uncertain()):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unverified" and run.finished_at and run.attempts == model.call_count == 2
    assert [c.args[0]["operation"] for c in model.call_args_list] == ["create", "check_repair"]
    assert chat.current_revision_id is None
    # A later transport/format status cannot hide otherwise valid manual evidence.
    run.status = last_status
    run.save(update_fields=["status"])
    data = run_data(run)
    assert data["can_confirm"] is True
    assert data["confirmation"]["requirements"] == ["Три попадания приводят к победе"]
    url = f"/api/runs/{run.id}/confirm/"
    assert client.post(url, {"confirmed": True}, content_type="application/json").status_code == 409
    assert client.post(url, {"confirmed": True, **data["confirmation"], "artifact_hash": "wrong"},
                       content_type="application/json").status_code == 409
    assert client.post(url, {"confirmed": True, **data["confirmation"]}, content_type="application/json").status_code == 200
    chat.refresh_from_db()
    assert chat.current_revision.verification == "manual"


@pytest.mark.django_db
def test_missing_gates_and_real_defects_cannot_be_manually_accepted(maker):
    chat, client = maker
    run = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", return_value=uncertain(False)):
        process_run(str(run.id))
    run.refresh_from_db()
    assert model.call_count == 1 and not run_data(run)["can_confirm"]
    assert client.post(f"/api/runs/{run.id}/confirm/", {"confirmed": True}, content_type="application/json").status_code == 409
    report = run.candidate_revision.reports.get()
    report.status = "failed"
    report.assessment.update(action="repair", gates_passed=False)
    report.save()
    assert not run_data(run)["can_confirm"]


@pytest.mark.django_db
def test_claimed_gate_flags_without_browser_facts_do_not_enable_confirmation(maker):
    chat, _ = maker
    run = start(chat)
    result = uncertain()
    result["facts"] = []
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", return_value=result):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.error["code"] == "check_review_required"
    assert model.call_count == 1 and not run_data(run)["can_confirm"]


@pytest.mark.django_db
def test_confirmation_rejects_a_changed_validator_even_with_the_same_candidate(maker):
    chat, client = maker
    run = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate), \
            patch("validation.service.validate", return_value=uncertain()):
        process_run(str(run.id))
    run.refresh_from_db()
    confirmation = run_data(run)["confirmation"]
    with patch("validation.service.environment_identity", return_value="a-different-browser"):
        response = client.post(f"/api/runs/{run.id}/confirm/", {"confirmed": True, **confirmation},
                               content_type="application/json")
    assert response.status_code == 409 and response.json()["error"]["code"] == "stale_verification"
    chat.refresh_from_db()
    assert chat.current_revision_id is None


@pytest.mark.django_db
def test_recheck_uses_same_candidate_without_any_model_calls_and_is_owner_only(maker):
    chat, client = maker
    run = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate), \
            patch("validation.service.validate", return_value=uncertain()):
        process_run(str(run.id))
    run.refresh_from_db()
    before = run.candidate_revision
    response = client.post(f"/api/revisions/{before.id}/validations/", {"idempotency_key": "recheck", "artifact_hash": before.artifact_hash}, content_type="application/json")
    assert response.status_code == 202, response.content
    again = client.post(f"/api/revisions/{before.id}/validations/", {"idempotency_key": "recheck", "artifact_hash": before.artifact_hash}, content_type="application/json")
    assert again.status_code == 202 and again.json()["id"] == response.json()["id"]
    with patch("generation.service.generate") as model, patch("validation.service.validate", return_value=PASS) as validator:
        from studio.validation_tasks import process_validation
        process_validation(response.json()["id"])
    model.assert_not_called()
    validator.assert_called_once()
    before.refresh_from_db()
    assert not before.accepted and before.verification == "none"
    assert before.reports.count() == 2 and chat.revisions.count() == 1
    assert run.invocations.count() == 2
    stranger = User.objects.create_user(username="stranger")
    client.force_login(stranger)
    assert client.post(f"/api/revisions/{before.id}/validations/", {}, content_type="application/json").status_code == 404


@pytest.mark.django_db
def test_recheck_does_not_materialize_a_pending_reply_from_the_previous_run(maker):
    from studio.models import Invocation

    chat, client = maker
    run = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate), \
            patch("validation.service.validate", return_value=uncertain()):
        process_run(str(run.id))
    run.refresh_from_db()
    candidate = run.candidate_revision
    request = {"operation": "repair", "base_revision": str(candidate.id), "files": candidate.files}
    pending = fake_generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    invocation = Invocation.objects.create(run=run, attempt=run.attempts + 1, state="returned", request=request,
                                           response=pending["response"])
    reply = client.post(f"/api/revisions/{candidate.id}/validations/",
                        {"idempotency_key": "pending", "artifact_hash": candidate.artifact_hash}, content_type="application/json")
    assert reply.status_code == 202
    with patch("generation.service.generate") as model, patch("validation.service.validate", return_value=PASS):
        from studio.validation_tasks import process_validation
        process_validation(reply.json()["id"])
    model.assert_not_called()
    invocation.refresh_from_db()
    assert invocation.state == "returned" and invocation.revision_id is None
    chat.refresh_from_db()
    assert chat.current_revision_id is None and chat.revisions.count() == 1


@pytest.mark.django_db
def test_application_numeric_review_preserves_sources_original_suite_and_model_receipt(maker):
    chat, _ = maker
    run = start(chat)

    def model(*args, **kwargs):
        result = fake_generate(*args, **kwargs)
        result["response"]["checks"][1]["observation"] = {"source": "text", "selector": "#counter"}
        result["response"]["checks"][1]["expect"] = {"operator": "increased", "value": None}
        return result

    with patch("generation.service.generate", side_effect=model), \
            patch("validation.service.validate", return_value=PASS) as validator:
        process_run(str(run.id))
    run.refresh_from_db()
    revision = run.result_revision
    report = revision.reports.get()
    assert revision.checks[1]["observation"]["source"] == "text"
    assert report.checks[1]["observation"]["source"] == "text_number"
    assert report.assessment["corrections"][0]["check_id"] == "tap"
    assert revision.checks == run.invocations.get().response["checks"]
    assert validator.call_args.args[1] == report.checks
    assert validator.call_args.args[0] == revision.html


@pytest.mark.django_db
def test_repeated_runtime_failure_stops_without_spending_all_repair_slots(maker):
    chat, _ = maker
    run = start(chat)
    failed = {"status": "failed", "findings": [{"code": "runtime_or_network", "check_id": "tap",
                                                  "errors": ["TypeError: game cannot start"]}], "facts": []}
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", return_value=failed):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.error["code"] == "no_progress"
    assert model.call_count == 2 and not run.candidate_revision.accepted


@pytest.mark.django_db
def test_a_different_root_error_is_not_mistaken_for_no_progress(maker):
    chat, _ = maker
    run = start(chat)
    first = {"status": "failed", "findings": [{"code": "javascript_syntax", "message": "SyntaxError: Unexpected end of input"}], "facts": []}
    second = {"status": "failed", "findings": [{"code": "javascript_syntax", "message": "SyntaxError: Unexpected token ')'"}], "facts": []}
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", side_effect=[first, second, PASS]):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded" and model.call_count == 3


@pytest.mark.django_db
@pytest.mark.parametrize("next_place", ["same", "file", "line", "same_exported", "exported_script"])
def test_identical_syntax_errors_only_stop_at_the_same_proven_source(maker, next_place):
    chat, _ = maker
    run = start(chat)
    first = {"status": "failed", "facts": [], "findings": [{
        "code": "javascript_syntax", "message": "SyntaxError: Unexpected token ';'",
        "location": "source", "path": "helper.js", "line": 1, "column": 5,
    }]}
    if next_place in {"same_exported", "exported_script"}:
        first["findings"][0].update(location="bundled_html", script_index=1, script_line=1, script_column=5)
    second = deepcopy(first)
    if next_place == "file":
        second["findings"][0]["path"] = "game.js"
    elif next_place == "line":
        second["findings"][0]["line"] = 10
    elif next_place == "exported_script":
        second["findings"][0]["script_index"] = 2
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", side_effect=[first, second, PASS]):
        process_run(str(run.id))
    run.refresh_from_db()
    same = next_place in {"same", "same_exported"}
    assert model.call_count == (2 if same else 3)
    if same:
        assert run.error["code"] == "no_progress"
    else:
        assert run.status == "succeeded"


def unknown_candidate(chat):
    run = start(chat)
    run.max_repair_attempts = 0
    run.save(update_fields=["max_repair_attempts"])
    failed = {"status": "failed", "findings": [{"code": "runtime_or_network", "check_id": "tap",
                                               "errors": ["TypeError: fixture runtime failure"]}], "facts": []}
    with patch("generation.service.generate", side_effect=fake_generate), \
            patch("validation.service.validate", return_value=failed):
        process_run(str(run.id))
    run.refresh_from_db()
    call = Invocation.objects.create(run=run, attempt=2, state="unknown", reservation_usd=Decimal("0.314"),
                                     request={"operation": "repair", "base_revision": str(run.candidate_revision_id)})
    run.status = "unknown"
    run.save(update_fields=["status"])
    return run, call, failed


def recheck(client, run, result, key):
    from studio.validation_tasks import process_validation

    revision = run.candidate_revision
    response = client.post(f"/api/revisions/{revision.id}/validations/",
                           {"idempotency_key": key, "artifact_hash": revision.artifact_hash},
                           content_type="application/json")
    assert response.status_code == 202, response.content
    with patch("generation.service.generate") as model, patch("validation.service.validate", return_value=result):
        process_validation(response.json()["id"])
    model.assert_not_called()
    run.refresh_from_db()
    return run


@pytest.mark.django_db
def test_repeated_rechecks_preserve_unknown_consent_in_api_and_actions(maker):
    chat, client = maker
    original, call, failed = unknown_candidate(chat)
    following = recheck(client, original, failed, "recheck-1")
    following = recheck(client, following, failed, "recheck-2")
    data = client.get(f"/api/runs/{following.id}/").json()
    assert not data["can_continue"] and data["can_retry_unknown"]
    path = f"/api/runs/{following.id}/continue/"
    for consent in (None, False, "true"):
        response = client.post(path, {"accept_unknown_cost": consent}, content_type="application/json")
        assert response.status_code == 409 and response.json()["error"]["code"] == "outcome_unknown"
    body = {"idempotency_key": "consented", "accept_unknown_cost": True}
    accepted = client.post(path, body, content_type="application/json")
    repeated = client.post(path, body, content_type="application/json")
    assert accepted.status_code == repeated.status_code == 202
    assert accepted.json()["id"] == repeated.json()["id"]
    retry = Run.objects.get(pk=accepted.json()["id"])
    assert retry.events.get(kind="explicit_retry").details["unknown_invocation_ids"] == [str(call.id)]
    assert budget_snapshot()["unknown_usd"] == 0.314
    call.refresh_from_db()
    assert call.state == "unknown" and call.cost_usd is None


@pytest.mark.django_db
@pytest.mark.parametrize("another_unknown", [False, True])
@pytest.mark.parametrize("legacy_consent", [False, True])
def test_consent_survives_rechecks_but_does_not_cover_another_unknown_call(maker, another_unknown, legacy_consent):
    from studio.tasks import request_for

    chat, client = maker
    original, old_call, failed = unknown_candidate(chat)
    first_check = original if legacy_consent else recheck(client, original, failed, "check")
    retry = create_run(chat, {"idempotency_key": "retry", "accept_unknown_cost": True}, continued_from=first_check)
    if legacy_consent:
        # Before lineage-aware consent, this event named only the immediate unknown run.
        retry.events.filter(kind="explicit_retry").update(details={"previous_run_id": str(retry.continued_from_id)})
    call = reserve_invocation(retry, request_for(retry, retry.candidate_revision, failed["findings"]))
    settle_invocation(call.id, error={"code": "lost"} if another_unknown else {"code": "not_sent"},
                      unknown=another_unknown)
    retry.status = "unknown" if another_unknown else "needs_attention"
    retry.save(update_fields=["status"])
    following = recheck(client, retry, failed, "check-after-consent")
    data = run_data(following)
    assert data["can_continue"] is not another_unknown
    assert data["can_retry_unknown"] is another_unknown
    response = client.post(f"/api/runs/{following.id}/continue/", {"idempotency_key": "next"},
                           content_type="application/json")
    assert response.status_code == (409 if another_unknown else 202)
    old_call.refresh_from_db()
    assert old_call.state == "unknown"


@pytest.mark.django_db
def test_unknown_receipt_appearing_while_queued_blocks_model_reservation(maker):
    from studio.tasks import request_for

    chat, _ = maker
    original, call, failed = unknown_candidate(chat)
    call.state = "failed"
    call.save(update_fields=["state"])
    original.status = "needs_attention"
    original.save(update_fields=["status"])
    following = create_run(chat, {"idempotency_key": "queued"}, continued_from=original)
    call.state = "unknown"
    call.save(update_fields=["state"])
    with patch("generation.service.generate") as model:
        process_run(str(following.id))
    model.assert_not_called()
    following.refresh_from_db()
    assert following.status == "needs_attention" and following.error["code"] == "outcome_unknown"
    assert not following.invocations.exists()
    assert request_for(following, following.candidate_revision, failed["findings"])["operation"] == "repair"


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["reserved", "sent"])
def test_rechecks_do_not_duplicate_an_ancestor_still_in_flight(maker, settings, state):
    chat, client = maker
    original, call, failed = unknown_candidate(chat)
    call.state = state
    call.save(update_fields=["state"])
    # Exercise admission independently of the usual single-provider capacity guard.
    settings.GAMEFORGE_PROVIDER_CONCURRENCY = 2
    following = recheck(client, original, failed, "check-in-flight")
    from studio.services import DomainError

    # A read-only check leaves the original unknown Run intact. Admission now
    # rejects continuation before it could reserve or duplicate an in-flight call.
    with pytest.raises(DomainError) as error:
        create_run(chat, {"idempotency_key": "in-flight-retry"}, continued_from=following)
    assert error.value.code == 'cannot_continue'
    assert Run.objects.filter(chat=chat).count() == 1


@pytest.mark.django_db
def test_sent_to_unknown_transition_during_reservation_cannot_admit_another_call(maker):
    from studio.continuations import delivery_state
    from studio.services import DomainError
    from studio.tasks import request_for

    chat, _ = maker
    original, call, failed = unknown_candidate(chat)
    call.state = "sent"
    call.save(update_fields=["state"])
    original.status = "cancelled"
    original.save(update_fields=["status"])
    following = create_run(chat, {"idempotency_key": "waiting"}, continued_from=original)

    def settle_during_admission(run):
        snapshot = delivery_state(run)
        Invocation.objects.filter(pk=call.id).update(state="unknown")
        return snapshot

    with patch("studio.services.delivery_state", side_effect=settle_during_admission):
        with pytest.raises(DomainError) as error:
            reserve_invocation(following, request_for(following, following.candidate_revision, failed["findings"]))
    assert error.value.code == "outcome_pending" and not following.invocations.exists()


@pytest.mark.django_db
def test_continuing_an_uncertain_result_rechecks_instead_of_regenerating(maker):
    chat, _ = maker
    run = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate), \
            patch("validation.service.validate", return_value=uncertain()):
        process_run(str(run.id))
    run.refresh_from_db()
    following = create_run(chat, {"idempotency_key": "continue"}, continued_from=run)
    with patch("generation.service.generate") as model, patch("validation.service.validate", return_value=uncertain()) as validator:
        process_run(str(following.id))
    model.assert_not_called()
    validator.assert_called_once()
    following.refresh_from_db()
    assert following.status == "unverified" and following.attempts == 0


@pytest.mark.django_db
def test_old_completion_policy_keeps_its_frozen_call_policy(maker):
    chat, _ = maker
    run = start(chat)
    run.completion_policy = 1
    run.save(update_fields=["completion_policy"])
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", side_effect=[deepcopy(uncertain()), PASS]):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded" and model.call_count == 2


@pytest.mark.django_db
def test_cancelled_validation_cannot_replace_confirmation_evidence(maker):
    from studio.services import cancel_run

    chat, _ = maker
    run = start(chat)

    def validate(*args, **kwargs):
        cancel_run(run)
        return uncertain()

    with patch("generation.service.generate", side_effect=fake_generate), \
            patch("validation.service.validate", side_effect=validate):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "cancelled" and run.check_reports.count() == 0
    assert not run_data(run)["can_confirm"]


@pytest.mark.django_db
def test_restart_after_saved_uncertain_report_does_not_repeat_inference_or_validation(maker):
    from datetime import timedelta

    from django.utils import timezone

    from studio.tasks import recover_expired

    chat, _ = maker
    run = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate), \
            patch("validation.service.validate", return_value=uncertain()), \
            patch("studio.tasks.finish_run", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            process_run(str(run.id))
    run.refresh_from_db()
    assert run.invocations.count() == 2 and run.check_reports.count() == 1
    run.lease_until = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["lease_until"])
    recover_expired()
    with patch("generation.service.generate") as model, patch("validation.service.validate") as validator:
        process_run(str(run.id))
    model.assert_not_called()
    validator.assert_not_called()
    run.refresh_from_db()
    assert run.status == "unverified" and run_data(run)["can_confirm"]


@pytest.mark.django_db
def test_regression_keeps_the_candidate_with_more_verified_behavior(maker):
    chat, _ = maker
    run = start(chat)
    first = {"status": "failed", "findings": [{"code": "runtime_or_network", "check_id": "outcome"}],
             "facts": [{"id": "start", "status": "passed"}, {"id": "tap", "status": "passed"}]}
    worse = {"status": "failed", "findings": [{"code": "javascript_syntax", "message": "New syntax failure"}],
             "facts": []}
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", side_effect=[first, worse]):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.error["code"] == "repair_regression" and model.call_count == 2
    assert run.candidate_revision_id == run.check_reports.order_by("id").first().revision_id
    assert chat.revisions.count() == 2


@pytest.mark.browser
@pytest.mark.django_db
@pytest.mark.parametrize("bad_selector", [False, True])
def test_complete_candidate_flow_with_real_isolated_validation(maker, monkeypatch, bad_selector):
    from validation import native

    monkeypatch.setenv("VALIDATOR_BACKEND", "native")
    chat, client = maker
    run = start(chat)

    def model(request, **kwargs):
        receipt = fake_generate(request, **kwargs)
        if request["operation"] == "check_repair":
            return receipt
        response = receipt["response"]
        for entry in response["files"]:
            if entry["path"] == "game.js":
                entry["content"] += "\nboard.setAttribute('data-count','0');\n" \
                    "board.addEventListener('pointerdown',()=>board.setAttribute('data-count',String(gameState.hits)));\n"
        response["checks"][1]["observation"] = {
            "source": "attribute", "selector": "#wrong-selector" if bad_selector else "#arena", "attribute": "data-count",
        }
        return receipt

    with patch("generation.service.generate", side_effect=model) as generation, \
            patch("validation.service.environment_identity", side_effect=native.environment_identity):
        process_run(str(run.id))
        run.refresh_from_db()
        assert generation.call_count == run.invocations.count() == (2 if bad_selector else 1)
        if bad_selector:
            data = run_data(run)
            assert run.status == "unverified" and data["can_confirm"]
            reply = client.post(f"/api/runs/{run.id}/confirm/", {"confirmed": True, **data["confirmation"]},
                                content_type="application/json")
            assert reply.status_code == 200, reply.content
            chat.refresh_from_db()
            assert chat.current_revision.verification == "manual"
        else:
            assert run.status == "succeeded", run.error
            report = run.result_revision.reports.get()
            assert report.facts[1]["after"] == 1
            assert report.assessment["corrections"][0]["to"] == "attribute_number"
            assert run.result_revision.verification == "automatic"


@pytest.mark.django_db
def test_model_authored_mismatch_cannot_authorize_source_repair(maker):
    chat, _ = maker
    run = start(chat)
    result = uncertain()
    result.update(status='failed', findings=[{'code': 'effect_mismatch', 'check_id': 'tap', 'before': 0, 'after': 0}])
    with patch('generation.service.generate', side_effect=fake_generate) as model, \
            patch('validation.service.validate', return_value=result):
        process_run(str(run.id))
    run.refresh_from_db()
    assert [c.args[0]['operation'] for c in model.call_args_list] == ['create', 'check_repair']
    assert run.status == 'unverified' and run_data(run)['can_confirm']
    assert all(r.files == run.candidate_revision.files for r in chat.revisions.all())
    assert not chat.revisions.filter(accepted=True).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('blocker', ['foreign', 'active', 'base', 'report', 'cancelled', 'unknown'])
def test_confirmation_is_bound_to_owner_base_and_exact_report_without_inference(maker, blocker):
    chat, client = maker
    run = start(chat)
    with patch('generation.service.generate', side_effect=fake_generate), \
            patch('validation.service.validate', return_value=uncertain()):
        process_run(str(run.id))
    run.refresh_from_db()
    payload = {'confirmed': True, **run_data(run)['confirmation']}
    original = (run.candidate_revision.html, run.candidate_revision.files, run.candidate_revision.checks)
    if blocker == 'foreign':
        other = User.objects.create_user(username='other-maker')
        client.force_login(other)
    elif blocker == 'active':
        create_run(chat, {'prompt': 'Исправь игру', 'idempotency_key': 'next-generation',
                          'source_revision_id': str(run.candidate_revision_id),
                          'source_artifact_hash': run.candidate_revision.artifact_hash})
    elif blocker == 'base':
        chat.current_revision = run.candidate_revision
        chat.save(update_fields=['current_revision'])
    elif blocker == 'report':
        payload['report_id'] -= 1
    else:
        run.status = blocker
        run.save(update_fields=['status'])
    if blocker in {'active', 'base', 'cancelled', 'unknown'}:
        assert not run_data(run)['can_confirm']
    count, revisions = Invocation.objects.count(), chat.revisions.count()
    with patch('generation.service.generate') as model:
        response = client.post(f'/api/runs/{run.id}/confirm/', payload, content_type='application/json')
    assert response.status_code == (404 if blocker == 'foreign' else 409)
    model.assert_not_called()
    run.refresh_from_db()
    candidate = run.candidate_revision
    assert not candidate.accepted
    assert (candidate.html, candidate.files, candidate.checks) == original
    assert Invocation.objects.count() == count and chat.revisions.count() == revisions
