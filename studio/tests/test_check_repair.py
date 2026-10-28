from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from generation.providers.fake import fixture_response
from generation.providers.fake import generate as fake_generate
from studio.models import Chat, User
from studio.serialization import run_data
from studio.services import create_run
from studio.tasks import process_run, recover_expired


@pytest.fixture
def maker(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    settings.GAMEFORGE_LEASE_SECONDS = 100
    with (
        patch("studio.services.schedule"),
        patch("studio.tasks.dispatch_outbox"),
        patch("studio.tasks.dispatch_run"),
        patch("validation.service.environment_identity", return_value="checks-test"),
    ):
        chat = Chat.objects.create(owner=User.objects.create_user(username="checks-maker"))
        client = Client()
        client.force_login(chat.owner)
        yield chat, client


def start(chat, **kwargs):
    return create_run(
        chat, {"prompt": "Три попадания в круг дают победу", "idempotency_key": "create", **kwargs}
    )


def model(request, **kwargs):
    if request["operation"] != "check_repair":
        result = fake_generate(request, **kwargs)
        result["response"]["checks"] = result["response"]["checks"][:2]
        return result
    policy = request["check_repair"]
    originals = fixture_response(with_assets=True)["checks"]
    checks = []
    for entry in policy["requirements"]:
        choices = [c for c in originals if c['category'] == entry['category']]
        original = next((c for c in choices if c['viewport'] == entry['viewport']), choices[0])
        checks.append({**deepcopy(original), **entry})
        if entry['viewport'] == 'desktop':
            for step in checks[-1]['steps']:
                step['action'] = {'tap':'click', 'tap_fraction':'click_fraction'}.get(step['action'], step['action'])
    return {
        "response": {
            "status": "ok",
            "operation": "check_repair",
            "base_revision": request["base_revision"],
            "artifact_hash": policy["artifact_hash"],
            "checks_hash": policy["checks_hash"],
            "message": "Сценарии исправлены, исходники сохранены.",
            "checks": checks,
        },
        "usage": {"input_tokens": 15, "cached_input_tokens": 0, "output_tokens": 20},
    }


def browser(html, checks, **kwargs):
    return {
        "status": "unverified" if len(checks) < 3 else "passed",
        "environment": "checks-test",
        "findings": [{"code": "incomplete_checks"}] if len(checks) < 3 else [],
        "gates": {"syntax": True, "runtime": True, "surface": True},
        "stages": [{"stage": "syntax", "status": "passed"}],
        "facts": [
            {
                **{k: c[k] for k in ("id", "category", "requirement", "viewport")},
                "status": "passed",
                "actions": c["steps"],
                "surface": {"canvases": [{"visible": True, "width": 300, "height": 300}], "overflow": False},
            }
            for c in checks
        ],
    }


@pytest.mark.django_db
@pytest.mark.browser
@pytest.mark.parametrize("missing", ["mobile", "touch"])
def test_mobile_coverage_repair_preserves_game_through_real_browser(maker, missing):
    chat, _ = maker
    run = start(chat)

    def mobile_model(request, **kwargs):
        if request["operation"] == "check_repair":
            return model(request, **kwargs)
        result = fake_generate(request, **kwargs)
        if missing == "mobile":
            for check in result["response"]["checks"]:
                check["viewport"] = "desktop"
        else:
            result["response"]["checks"][1]["steps"] = [{"action": "press", "key": "Space"}]
        return result

    with patch("generation.providers.fake.generate", side_effect=mobile_model) as inference:
        process_run(str(run.id))
    run.refresh_from_db()
    assert [c.args[0]["operation"] for c in inference.call_args_list] == ["create", "check_repair"]
    original, revised = run.revisions.order_by("number")
    assert original.files == revised.files and original.artifact_hash == revised.artifact_hash
    assert run.status == "unverified" and revised.checks_review_required and not revised.accepted
    report = revised.reports.get()
    assert report.assessment["gates_passed"] is True
    assert all(fact["status"] == "passed" for fact in report.facts)


@pytest.mark.django_db
def test_incomplete_checks_keep_sources_and_repaired_suite_requires_bound_human_confirmation(maker):
    chat, client = maker
    run = start(chat)
    with (
        patch("generation.providers.fake.generate", side_effect=model) as inference,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    chat.refresh_from_db()
    assert run.status == "unverified" and run.attempts == inference.call_count == 2
    assert [c.args[0]["operation"] for c in inference.call_args_list] == ["create", "check_repair"]
    original, revised = run.revisions.all()
    assert (
        original.files == revised.files
        and original.html == revised.html
        and original.artifact_hash == revised.artifact_hash
    )
    assert original.design == revised.design and original.title == revised.title
    assert len(original.checks) == 2 and len(revised.checks) == 4
    assert revised.checks_review_required and not original.checks_review_required
    assert not chat.current_revision_id and not revised.accepted
    assert revised.reports.get().assessment["action"] == "review"
    data = run_data(run)
    assert data["can_confirm"]
    assert len(data["confirmation"]["requirements"]) == 4
    assert (
        client.post(
            f"/api/runs/{run.id}/confirm/", {"confirmed": True}, content_type="application/json"
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/runs/{run.id}/confirm/",
            {"confirmed": True, **data["confirmation"]},
            content_type="application/json",
        ).status_code
        == 200
    )
    revised.refresh_from_db()
    assert revised.accepted and revised.verification == "manual" and not revised.checks_review_required


@pytest.mark.django_db
@pytest.mark.parametrize("fault", ["source", "requirement", "unchanged", "bad_json"])
def test_failed_scenario_repair_stops_once_and_keeps_original_candidate(maker, fault):
    from generation.errors import ContractError

    chat, _ = maker
    run = start(chat)

    def faulty(request, **kwargs):
        result = model(request, **kwargs)
        if request["operation"] == "check_repair":
            if fault == "source":
                result["response"]["files"] = [{"path": "game.js", "content": "override"}]
            elif fault == "requirement":
                result["response"]["checks"][0]["requirement"] = "Другое условие"
            elif fault == "unchanged":
                result["response"].update(status="unchanged", checks=[])
            else:
                raise ContractError(
                    "invalid_json",
                    "Неполный JSON",
                    usage={"input_tokens": 5, "cached_input_tokens": 0, "output_tokens": 6},
                )
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=faulty) as inference,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.attempts == inference.call_count == 2, (
        run.error,
        list(run.invocations.values("error")),
    )
    assert run.revisions.count() == 1 and run.candidate_revision_id == run.revisions.get().id
    continued = create_run(chat, {"idempotency_key": "continue"}, continued_from=run)
    with (
        patch("generation.providers.fake.generate") as inference,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(continued.id))
    continued.refresh_from_db()
    assert continued.status == "needs_attention" and not continued.attempts
    inference.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_crash_after_scenario_receipt_reuses_exact_reply_and_no_extra_inference(maker):
    chat, _ = maker
    run = start(chat)
    from studio.tasks import store_candidate

    def crash(current, artifact, base):
        if artifact.get("checks_review_required"):
            raise KeyboardInterrupt
        return store_candidate(current, artifact, base)

    with (
        patch("generation.providers.fake.generate", side_effect=model) as inference,
        patch("validation.service.validate", side_effect=browser),
        patch("studio.tasks.store_candidate", side_effect=crash),
    ):
        with pytest.raises(KeyboardInterrupt):
            process_run(str(run.id))
    run.refresh_from_db()
    assert run.attempts == inference.call_count == 2
    run.lease_until = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["lease_until"])
    recover_expired()
    with (
        patch("generation.providers.fake.generate") as inference,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    inference.assert_not_called()
    run.refresh_from_db()
    assert run.status == "unverified" and run.revisions.count() == 2


@pytest.mark.django_db
def test_check_only_recheck_cannot_auto_accept_revised_suite_or_call_model(maker):
    chat, _ = maker
    run = start(chat)
    with (
        patch("generation.providers.fake.generate", side_effect=model),
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    recheck = create_run(chat, {"idempotency_key": "recheck"}, continued_from=run, check_only=True)
    with (
        patch("generation.providers.fake.generate") as inference,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(recheck.id))
    recheck.refresh_from_db()
    inference.assert_not_called()
    assert recheck.status == "unverified" and recheck.attempts == 0 and run_data(recheck)["can_confirm"]
    chat.refresh_from_db()
    assert not chat.current_revision_id


@pytest.mark.django_db
def test_cancel_after_scenario_reply_retains_receipt_without_applying_it(maker):
    chat, _ = maker
    run = start(chat)

    def cancel(request, **kwargs):
        result = model(request, **kwargs)
        if request["operation"] == "check_repair":
            type(run).objects.filter(pk=run.id).update(status="cancelled", cancel_requested=True)
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=cancel),
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "cancelled" and run.revisions.count() == 1
    receipt = run.invocations.get(attempt=2)
    assert receipt.state == "returned" and receipt.usage and not receipt.revision_id


@pytest.mark.django_db
def test_shared_call_cap_stops_before_scenario_repair_without_losing_code(maker):
    chat, _ = maker
    run = start(chat, model_call_limit=1)
    with (
        patch("generation.providers.fake.generate", side_effect=model) as inference,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.attempts == inference.call_count == 1
    assert run.candidate_revision_id and run.revisions.count() == 1


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("defect", ["missing_category", "wrong_sequence"])
def test_real_browser_check_repair_preserves_game_and_exposes_manual_evidence(maker, defect):
    chat, _ = maker
    run = start(chat)

    def inference(request, **kwargs):
        result = model(request, **kwargs)
        if request["operation"] == "create" and defect == "wrong_sequence":
            result["response"]["checks"] = fixture_response(with_assets=True)["checks"]
            result["response"]["checks"][2]["steps"].pop()
        return result

    with patch("generation.providers.fake.generate", side_effect=inference) as provider:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unverified", run.error
    assert run.attempts == provider.call_count == 2
    first, second = run.revisions.all()
    assert first.files == second.files and first.html == second.html
    assert first.artifact_hash == second.artifact_hash
    assert second.checks_review_required and run_data(run)["can_confirm"]
    assert not second.accepted
    if defect == "wrong_sequence":
        # Checks policy 4 keeps a scenario mismatch unverified; it is not proof
        # that the game is broken and must not authorize a source rewrite.
        assert first.reports.get().status == "unverified"
        assert first.reports.get().assessment['action'] == 'review'
        assert first.reports.get().findings[0]["code"] == "effect_mismatch"
    final = second.reports.get()
    assert all(
        f["status"] == "passed" and f["actions"] == c["steps"] for f, c in zip(final.facts, final.checks)
    )
    assert final.assessment["gates_passed"] and final.assessment["action"] == "review"




@pytest.mark.django_db
def test_unknown_usage_in_rejected_check_reply_still_requires_explicit_consent(maker):
    from studio.services import DomainError

    chat, _ = maker
    run = start(chat)

    def incomplete_usage(request, **kwargs):
        result = model(request, **kwargs)
        if request["operation"] == "check_repair":
            result["response"]["files"] = []
            result["usage"] = None
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=incomplete_usage),
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unknown" and run.revisions.count() == 1
    receipt = run.invocations.get(attempt=2)
    assert receipt.state == "unknown" and receipt.raw_response and receipt.cost_usd is None
    with pytest.raises(DomainError) as rejected:
        create_run(chat, {"idempotency_key": "no-consent"}, continued_from=run)
    assert rejected.value.code == "outcome_unknown"


@pytest.mark.django_db
def test_automatic_acceptance_cannot_bypass_revised_scenario_review(maker):
    from studio.services import DomainError, finish_run

    chat, _ = maker
    run = start(chat)
    with (
        patch("generation.providers.fake.generate", side_effect=model),
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    with pytest.raises(DomainError) as blocked:
        finish_run(run.id, run.fence, "succeeded", "ready", revision=run.candidate_revision)
    assert blocked.value.code == "check_review_required"
    run.refresh_from_db()
    chat.refresh_from_db()
    assert run.status == "unverified" and not chat.current_revision_id
