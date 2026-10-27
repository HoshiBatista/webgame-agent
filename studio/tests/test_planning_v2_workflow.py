from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from generation.errors import GenerationError
from generation.providers.fake import generate as fake_generate
from studio.acceptance import confirmation_report
from studio.models import Chat, User
from studio.services import DomainError, cancel_run, create_run, preference_for
from studio.tasks import process_run, recover_expired, request_for
from tests.test_compact_generation import compact_response
from tests.test_validation import fixture_report


@pytest.fixture
def maker(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3
    settings.GAMEFORGE_LITE_CODE_THEN_CHECKS_ENABLED = True
    with (
        patch("studio.services.schedule"),
        patch("studio.tasks.dispatch_outbox"),
        patch("studio.tasks.dispatch_run"),
        patch("validation.service.environment_identity", return_value="p45-test"),
    ):
        yield Chat.objects.create(owner=User.objects.create_user(username="p45-maker"))


def start(chat, **overrides):
    return create_run(
        chat,
        {
            "prompt": "Три попадания дают победу",
            "idempotency_key": "p45",
            "generation_profile": "compact",
            **overrides,
        },
    )


def response_for(request, **kwargs):
    compact = compact_response()
    if request["operation"] == "plan":
        result = fake_generate(request, **kwargs)
        result["response"]["plan"]["requirements"] = [
            {
                **{k: p[k] for k in ("id", "category", "requirement", "viewport")},
                "origin": "design",
                "quote": "",
                "example": {"action": "Коснуться игрового элемента", "effect": p["requirement"]},
            }
            for p in compact["probes"]
        ]
        return result
    if request["operation"] == "create":
        compact.pop("probes")
        response = compact
    elif request["operation"] == "repair":
        response = {
            "status": "ok",
            "message": "Исправлена синтаксическая ошибка",
            "source": compact["source"],
        }
    else:
        assert request["operation"] == "checks_create"
        policy = request["checks_create"]
        response = {
            "status": "ok",
            "message": "Сценарии для сохранённой версии",
            **{k: policy[k] for k in ("base_revision", "artifact_hash", "manifest_hash")},
            "observations": compact["observations"],
            "probes": [
                {**next(p for p in compact["probes"] if p["category"] == r["category"]), **r}
                for r in policy["requirements"]
            ],
        }
    return {
        "response": response,
        "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 20},
    }


def browser(html, checks, **kwargs):
    result = fixture_report(html, checks)
    if not checks:
        result.update(status="unverified", findings=[{"code": "incomplete_checks"}])
    return result


@pytest.mark.django_db
@pytest.mark.parametrize("plan", [False, True])
def test_experiment_budget_provenance_source_preservation_and_confirmation(maker, plan):
    run = start(maker)
    run.planning_required = plan
    run.save(update_fields=["planning_required"])
    with (
        patch("generation.providers.fake.generate", side_effect=response_for) as model,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unverified", run.error
    assert [c.args[0]["operation"] for c in model.call_args_list] == (["plan"] if plan else []) + [
        "create",
        "checks_create",
    ]
    assert run.attempts == 2 + int(plan) and run.max_model_calls == 4 + int(plan)
    first, second = run.revisions.order_by("number")
    assert not first.checks and second.checks and second.checks_review_required
    assert (
        first.files == second.files
        and first.html == second.html
        and first.artifact_hash == second.artifact_hash
    )
    assert first.requirement_manifest == second.requirement_manifest == run.requirement_manifest
    assert not first.accepted and not second.accepted and confirmation_report(run)
    assert all(i.state == "settled" and i.cost_usd is not None for i in run.invocations.all())
    assert run.requirement_manifest["scope"] == ("planned_proposals" if plan else "user_request_unmapped")


@pytest.mark.django_db
@pytest.mark.parametrize("fault", ["refusal", "unchanged", "source", "requirement", "unknown"])
def test_checks_create_failure_is_bounded_and_keeps_source(maker, fault):
    run = start(maker)

    def model(request, **kwargs):
        if request["operation"] == "checks_create" and fault == "unknown":
            raise GenerationError("transport_lost", "Результат неизвестен.", outcome_unknown=True)
        result = response_for(request, **kwargs)
        if request["operation"] == "checks_create":
            if fault in {"refusal", "unchanged"}:
                result["response"].update(
                    status="scope_refusal" if fault == "refusal" else "unchanged",
                    message="Нельзя измерить этот эффект.",
                    observations=[],
                    probes=[],
                )
            elif fault == "source":
                result["response"]["source"] = "replace game"
            else:
                result["response"]["probes"][0]["requirement"] = "Подменённое требование игры"
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=model) as calls,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == ("unknown" if fault == "unknown" else "needs_attention"), run.error
    assert calls.call_count == 2 and run.revisions.count() == 1 and not confirmation_report(run)
    assert run.candidate_revision.files["game.js"] == compact_response()["source"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("crash", ["code_saved", "code_checked", "checks_returned", "checks_saved"])
def test_restart_between_every_stage_reuses_receipts_and_never_duplicates_code(maker, crash):
    from studio import tasks

    run = start(maker)
    store, request = tasks.store_candidate, tasks.request_for

    def store_then_interrupt(current, materialized, base):
        if crash == "checks_returned" and base is not None:
            raise KeyboardInterrupt
        return store(current, materialized, base)

    def request_then_interrupt(*args):
        value = request(*args)
        if crash == "code_checked" and value["operation"] == "checks_create":
            raise KeyboardInterrupt
        return value

    def browser_then_interrupt(html, checks, **kwargs):
        if (crash == "code_saved" and not checks) or (crash == "checks_saved" and checks):
            raise KeyboardInterrupt
        return browser(html, checks, **kwargs)

    with (
        patch("generation.providers.fake.generate", side_effect=response_for),
        patch("studio.tasks.store_candidate", side_effect=store_then_interrupt),
        patch("studio.tasks.request_for", side_effect=request_then_interrupt),
        patch("validation.service.validate", side_effect=browser_then_interrupt),
    ):
        with pytest.raises(KeyboardInterrupt):
            process_run(str(run.id))
    run.refresh_from_db()
    sent = list(run.invocations.values_list("id", flat=True))
    run.lease_until = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["lease_until"])
    recover_expired()
    with (
        patch("generation.providers.fake.generate", side_effect=response_for) as calls,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unverified", run.error
    assert run.invocations.count() == 2 and run.revisions.count() == 2
    assert run.invocations.filter(id__in=sent).count() == len(sent)
    assert calls.call_count == (1 if crash in {"code_saved", "code_checked"} else 0)


@pytest.mark.django_db
@pytest.mark.parametrize("stop", ["budget", "cancel", "deadline"])
def test_code_survives_exhaustion_and_cancel_without_scenarios_call(maker, stop):
    run = start(maker, **({"model_call_limit": 1} if stop == "budget" else {}))

    def stop_after_gates(html, checks, **kwargs):
        if stop == "cancel":
            cancel_run(run)
        if stop == "deadline":
            type(run).objects.filter(pk=run.id).update(
                model_call_deadline=timezone.now() - timedelta(seconds=1)
            )
        return browser(html, checks, **kwargs)

    with (
        patch("generation.providers.fake.generate", side_effect=response_for) as calls,
        patch("validation.service.validate", side_effect=stop_after_gates),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert calls.call_count == 1 and run.revisions.count() == 1
    assert run.status == ("cancelled" if stop == "cancel" else "needs_attention")
    assert run.candidate_revision and not confirmation_report(run)


@pytest.mark.django_db
@pytest.mark.parametrize("fault", ["schema", "policy"])
def test_policy_and_preferences_frozen_before_first_call(maker, fault):
    prefs = preference_for(maker.owner)
    prefs.notes = ["Крупные кнопки"]
    prefs.save()
    run = start(maker)
    prefs.notes = ["Мелкие кнопки"]
    prefs.save()
    assert request_for(run, None, [])["preferences"] == ["Крупные кнопки"]
    with patch("generation.requirements.policy_snapshot", return_value={fault: "updated"}):
        with pytest.raises(DomainError, match="Правила генерации обновились"):
            request_for(run, None, [])


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["syntax", "manifest"])
def test_real_code_defect_and_missing_promises_have_different_repair_authority(maker, kind):
    run = start(maker)
    run.planning_required = True
    run.save(update_fields=["planning_required"])

    def model(request, **kwargs):
        result = response_for(request, **kwargs)
        if request["operation"] == "create" and kind == "syntax":
            result["response"]["source"] += "\nreturn 1;"
        return result

    def check(html, checks, **kwargs):
        report = browser(html, checks, **kwargs)
        if "\nreturn 1;" in html:
            from validation.evidence import gates

            report["artifact_evidence"]["syntax"]["status"] = "failed"
            report.update(
                status="failed",
                findings=[{"code": "javascript_syntax", "path": "game.js", "line": 23}],
                gates=gates(report["artifact_evidence"]),
            )
        return report

    with (
        patch("generation.providers.fake.generate", side_effect=model) as calls,
        patch("validation.service.validate", side_effect=check),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    operations = [c.args[0]["operation"] for c in calls.call_args_list]
    assert operations == ["plan", "create"] + (["repair"] if kind == "syntax" else []) + ["checks_create"], (
        operations,
        run.error,
    )
    assert run.status == "unverified", run.error
    if kind == "syntax":
        repair = calls.call_args_list[2].args[0]
        assert repair["code_repair_basis"]["defects"] == ["javascript_syntax"]
        assert not repair["checks"]


@pytest.mark.django_db
def test_flag_is_frozen_and_new_request_uses_new_preferences(maker, settings):
    run = start(maker)
    settings.GAMEFORGE_LITE_CODE_THEN_CHECKS_ENABLED = False
    assert request_for(run, None, [])["generation_strategy"] == "lite_code_then_checks"
    run.status = "needs_attention"
    run.save(update_fields=["status"])
    prefs = preference_for(maker.owner)
    prefs.notes = ["Новое пожелание"]
    prefs.save()
    continuation = create_run(
        maker, {"idempotency_key": "continue", "prompt": run.prompt}, continued_from=run
    )
    assert continuation.preferences_snapshot == run.preferences_snapshot
    continuation.status = "needs_attention"
    continuation.save(update_fields=["status"])
    new = start(maker, idempotency_key="new")
    assert new.generation_strategy == "lite" and new.preferences_snapshot == ["Новое пожелание"]


@pytest.mark.django_db
def test_budget_stop_can_continue_from_code_without_regeneration(maker):
    from studio.serialization import run_data

    run = start(maker, model_call_limit=1)
    with (
        patch("generation.providers.fake.generate", side_effect=response_for),
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    original = run.candidate_revision
    assert run_data(run)["can_continue"]
    continuation = create_run(
        maker, {"idempotency_key": "finish-scenarios", "model_call_limit": 1}, continued_from=run
    )
    with (
        patch("generation.providers.fake.generate", side_effect=response_for) as calls,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(continuation.id))
    continuation.refresh_from_db()
    assert continuation.status == "unverified", continuation.error
    assert calls.call_count == 1 and calls.call_args.args[0]["operation"] == "checks_create"
    assert continuation.candidate_revision.files == original.files


@pytest.mark.django_db
def test_full_plan_promise_mismatch_cannot_be_accepted_or_manually_confirmed(maker, settings):
    settings.GAMEFORGE_LITE_CODE_THEN_CHECKS_ENABLED = False
    run = create_run(maker, {"prompt": "Сделай игру", "idempotency_key": "full", "model_call_limit": 2})
    run.planning_required = True
    run.save(update_fields=["planning_required"])

    def model(request, **kwargs):
        result = fake_generate(request, **kwargs)
        if request["operation"] == "create":
            result["response"]["checks"][0]["requirement"] = "Другое требование, которого нет в плане"
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=model),
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and not confirmation_report(run)
    report = run.candidate_revision.reports.get()
    assert report.assessment["requirement_coverage"]["uncovered"]
    assert "requirement_manifest_mismatch" in {f["code"] for f in report.findings}
    assert not run.candidate_revision.accepted


@pytest.mark.django_db
def test_reserved_unsent_call_is_not_dispatched_after_policy_drift(maker):
    from studio.services import reserve_invocation

    run = start(maker)
    reserve_invocation(run, request_for(run, None, []))
    run.policy_snapshot = {"outdated": True}
    run.save(update_fields=["policy_snapshot"])
    with patch("generation.service.generate") as calls:
        process_run(str(run.id))
    run.refresh_from_db()
    calls.assert_not_called()
    call = run.invocations.get()
    assert run.error["code"] == "generation_policy_changed"
    assert call.state == "failed" and call.cost_usd == 0 and call.sent_at is None


@pytest.mark.django_db
def test_retired_candidate_is_not_executed_by_new_contract(maker):
    from studio.models import Revision
    from tests.test_compact_generation import artifact

    run = start(maker)
    game = artifact()
    revision = Revision.objects.create(
        chat=maker,
        run=run,
        number=1,
        pipeline_version=8,
        **{
            k: game[k]
            for k in ("files", "html", "artifact_hash", "file_hashes", "checks", "compact_manifest")
        },
    )
    run.candidate_revision = revision
    run.save(update_fields=["candidate_revision"])
    with patch("generation.service.generate") as calls, patch("validation.service.validate") as browser_call:
        process_run(str(run.id))
    run.refresh_from_db()
    calls.assert_not_called()
    browser_call.assert_not_called()
    assert run.error["code"] == "unsupported_game" and not run.result_revision


@pytest.mark.django_db
@pytest.mark.browser
@pytest.mark.parametrize("syntax_fault", [False, True])
def test_code_then_checks_through_isolated_browser_without_model(maker, syntax_fault):
    run = start(maker)

    def model(request, **kwargs):
        result = response_for(request, **kwargs)
        if request["operation"] == "create" and syntax_fault:
            result["response"]["source"] += "\nreturn 1;"
        return result

    with patch("generation.providers.fake.generate", side_effect=model) as calls:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unverified", run.error
    assert [c.args[0]["operation"] for c in calls.call_args_list] == ["create"] + (
        ["repair"] if syntax_fault else []
    ) + ["checks_create"]
    last = run.candidate_revision
    assert last.reports.get().assessment["gates_passed"] and confirmation_report(run)
    assert all(f["status"] == "passed" for f in last.reports.get().facts)
    assert last.files == last.parent.files and last.checks_review_required


@pytest.mark.django_db
def test_model_free_recheck_of_code_does_not_create_scenarios(maker):
    run = start(maker, model_call_limit=1)
    with (
        patch("generation.providers.fake.generate", side_effect=response_for),
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    recheck = create_run(maker, {"idempotency_key": "recheck"}, continued_from=run, check_only=True)
    with (
        patch("generation.service.generate") as calls,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(recheck.id))
    recheck.refresh_from_db()
    calls.assert_not_called()
    assert not recheck.invocations.exists() and recheck.candidate_revision_id == run.candidate_revision_id


@pytest.mark.django_db
@pytest.mark.parametrize("provider", ["codex", "codex_api"])
def test_experiment_flag_does_not_change_other_codex_models(maker, settings, provider):
    settings.GAMEFORGE_PROVIDER = provider
    settings.GAMEFORGE_MODEL = "gpt-6-luna"
    run = start(maker, model_profile="")
    assert run.generation_strategy == "lite" and run.generation_profile == "compact"
    assert (
        "probes"
        in __import__("generation.schema", fromlist=["response_schema"]).response_schema(
            request_for(run, None, [])
        )["properties"]
    )
