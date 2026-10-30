from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from generation.errors import ContractError, GenerationError
from generation.providers.fake import fixture_response
from generation.schema import validate_checks
from studio.models import Invocation
from studio.serialization import run_data
from studio.services import create_run
from studio.tasks import process_run, recover_expired
from studio.tests import test_draft_editing as drafts
from studio.tests.test_check_repair import browser, model
from studio.tests.test_draft_editing import edit_data, saved
from tests.test_edit_recovery import corrected, edit_case
from validation.evidence import receipt

workspace = drafts.workspace


def checked_browser(html, checks, **kwargs):
    result = browser(html, checks, **kwargs)
    try:
        validate_checks(checks)
    except ContractError:
        result.update(status="unverified", findings=[{"code": "invalid_check"}])
    result.update(artifact_hash=kwargs["artifact_hash"], environment="draft-tests")
    result["artifact_evidence"] = receipt(kwargs["artifact_hash"], "draft-tests", {"status": "passed", "scripts": 1}, [
        {"viewport": view, "loaded": True, "errors": [], "requests": [],
         "surface": {"canvases": [{"visible": True, "width": 300, "height": 300}], "overflow": False}}
        for view in ("mobile", "landscape", "desktop")
    ])
    return result


def edit_model(request, **kwargs):
    if request["operation"] == "check_repair":
        return model(request, **kwargs)
    if request.get("patch_repair"):
        response = corrected(request["patch_repair"], {"files": request["files"]})
    else:
        _, response = edit_case()
        response["base_revision"] = request["base_revision"]
        response['assets'] = None
    return {"response": response, "usage": {"input_tokens": 7, "output_tokens": 9}}


@pytest.mark.django_db
@pytest.mark.parametrize("defect", ["duplicate", "no_real_input", "oversized_inherited_duplicates"])
def test_edit_saves_code_then_repairs_only_checks_and_requires_confirmation(workspace, defect):
    chat, client = workspace
    source = saved(chat)
    if defect == "oversized_inherited_duplicates":
        # Same shape as the incident: distinct scenarios repeat a requirement ID;
        # adding new checks crosses the browser envelope, but not unique promises.
        source.checks += [deepcopy(source.checks[1]) for _ in range(9)]
        source.save(update_fields=["checks"])
    run = create_run(chat, edit_data(source))

    def faulty_checks(request, **kwargs):
        result = edit_model(request, **kwargs)
        if request["operation"] == "edit":
            response = result["response"]
            response["patches"] = response["patches"][:1]
            control = deepcopy(source.checks[1])
            if defect == "no_real_input":
                control["steps"] = [{"action": "checkpoint"}, {"action": "wait_for", "ms": 100}]
                control["expect"] = {"operator": "changed", "value": None}
                response["checks"] = [control]
            elif defect == "duplicate":
                response["checks"] = [control, deepcopy(control)]
            else:
                response["checks"] = [{**control, "id": "sound", "requirement": "Касание переключает звук игры"},
                                      {**control, "id": "random", "requirement": "Касание меняет состояние сцены"}]
        return result

    with patch("generation.providers.fake.generate", side_effect=faulty_checks) as inference, \
         patch("validation.service.validate", side_effect=checked_browser) as validator:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unverified", (run.error, list(run.invocations.values("error")))
    assert [c.args[0]["operation"] for c in inference.call_args_list] == ["edit", "check_repair"]
    assert all(len(c.args[1]) <= 12 for c in validator.call_args_list)
    first, fixed = run.revisions.order_by("number")
    assert first.files == fixed.files and first.artifact_hash == fixed.artifact_hash != source.artifact_hash
    assert first.checks != fixed.checks and fixed.checks_review_required
    assert not fixed.accepted and run_data(run)["can_confirm"]
    assert all(i.usage and i.raw_response for i in run.invocations.all())
    assert client.post(f"/api/runs/{run.id}/confirm/", {"confirmed": True}, content_type="application/json").status_code == 409


@pytest.mark.django_db
@pytest.mark.parametrize("intermediate", ["none", "bad_json", "still_bad"])
def test_rejected_patch_retries_reuse_good_fragments_within_shared_budget(workspace, intermediate):
    chat, _ = workspace
    source = saved(chat)
    run = create_run(chat, edit_data(source))
    calls = []

    def inference(request, **kwargs):
        calls.append(deepcopy(request))
        if len(calls) == 2 and intermediate == "bad_json":
            raise ContractError("invalid_json", "Неполный ответ", usage={"input_tokens": 3, "output_tokens": 2})
        result = edit_model(request, **kwargs)
        if len(calls) == 2 and intermediate == "still_bad":
            result["response"]["corrections"][0]["patches"][0]["old_text"] = "missing anchor"
        return result

    with patch("generation.providers.fake.generate", side_effect=inference), \
         patch("validation.service.validate", side_effect=checked_browser):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", (run.error, list(run.invocations.values("error")))
    assert run.attempts == len(calls) == (2 if intermediate == "none" else 3)
    assert run.revisions.count() == 1
    assert all(c.get("patch_repair", {}).get("indices") == [1] for c in calls[1:])
    assert all(c["patch_repair"]["response"]["patches"][0] == calls[1]["patch_repair"]["response"]["patches"][0] for c in calls[1:])
    assert "#fff4ee" in run.result_revision.files["styles.css"]
    assert "#ee88bb" in run.result_revision.files["game.js"]


@pytest.mark.django_db
def test_unfixable_fragments_stop_at_four_calls_without_partial_candidate(workspace):
    chat, _ = workspace
    source = saved(chat)
    run = create_run(chat, edit_data(source))

    def bad(request, **kwargs):
        result = edit_model(request, **kwargs)
        if request.get("patch_repair"):
            result["response"]["corrections"][0]["patches"][0]["old_text"] = "still missing"
        return result

    with patch("generation.providers.fake.generate", side_effect=bad) as inference:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.attempts == inference.call_count == 4
    assert not run.revisions.exists() and not run.candidate_revision_id


@pytest.mark.django_db
def test_new_overlap_cannot_unlock_a_previously_good_patch(workspace):
    from generation.artifacts import sha256

    chat, _ = workspace
    source = saved(chat)
    run = create_run(chat, edit_data(source))
    calls = []

    def overlapping(request, **kwargs):
        calls.append(deepcopy(request))
        result = edit_model(request, **kwargs)
        if not request.get("patch_repair"):
            result["response"]["patches"][0] = {
                "path": "game.js", "file_hash": sha256(source.files["game.js"]),
                "old_text": 'ctx.font="32px sans-serif"', "new_text": 'ctx.font="30px sans-serif"'}
        elif len(calls) == 2:
            result["response"]["corrections"][0]["patches"][0].update(
                old_text='ctx.font="32px sans-serif"', new_text='ctx.font="40px sans-serif"')
        return result

    with patch("generation.providers.fake.generate", side_effect=overlapping), \
         patch("validation.service.validate", side_effect=checked_browser):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded" and len(calls) == 3
    assert calls[1]["patch_repair"] == calls[2]["patch_repair"]
    assert calls[2]["patch_repair"]["indices"] == [1]
    assert 'ctx.font="30px sans-serif"' in run.result_revision.files["game.js"]


@pytest.mark.django_db
def test_continuation_keeps_saved_patch_scope(workspace):
    from studio.tasks import request_for

    chat, _ = workspace
    source = saved(chat)
    run = create_run(chat, edit_data(source))
    response = edit_model({"base_revision": str(source.id), "operation": "edit"})["response"]
    Invocation.objects.create(run=run, attempt=1, state="settled", response=response,
        error={"code": "ambiguous_patch"},
        request={"operation": "edit", "base_revision": str(source.id), "generation_profile": "full"})
    run.status = "needs_attention"
    run.save(update_fields=["status"])
    continued = create_run(chat, {"idempotency_key": "continue", "allow_model_calls": True}, continued_from=run)
    request = request_for(continued, source, [])
    assert request["operation"] == "edit" and request["patch_repair"]["indices"] == [1]
    continued.status = "needs_attention"
    continued.save(update_fields=["status"])
    another = create_run(chat, {"idempotency_key": "continue-again", "allow_model_calls": True}, continued_from=continued)
    assert request_for(another, source, [])["patch_repair"] == request["patch_repair"]


@pytest.mark.django_db
def test_crash_after_correction_receipt_reuses_exact_reply_without_new_inference(workspace):
    chat, _ = workspace
    run = create_run(chat, edit_data(saved(chat)))
    with patch("generation.providers.fake.generate", side_effect=edit_model) as inference, \
         patch("studio.tasks.store_candidate", side_effect=SystemExit("worker stopped")):
        with pytest.raises(SystemExit):
            process_run(str(run.id))
    assert inference.call_count == 2
    inv = run.invocations.order_by("-attempt").first()
    assert inv.state == "returned" and inv.response and inv.request["patch_repair"]
    run.refresh_from_db()
    run.lease_until = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["lease_until"])
    recover_expired()
    with patch("generation.providers.fake.generate") as inference, \
         patch("validation.service.validate", side_effect=checked_browser):
        process_run(str(run.id))
    inference.assert_not_called()
    run.refresh_from_db()
    assert run.status == "succeeded" and run.revisions.count() == 1


@pytest.mark.django_db
def test_unknown_correction_is_never_resent(workspace):
    chat, _ = workspace
    run = create_run(chat, edit_data(saved(chat)))

    def unknown(request, **kwargs):
        if request.get("patch_repair"):
            raise GenerationError("connection_lost", "Результат неизвестен", outcome_unknown=True)
        return edit_model(request, **kwargs)

    with patch("generation.providers.fake.generate", side_effect=unknown) as inference:
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unknown" and inference.call_count == 2
    assert Invocation.objects.get(run=run, attempt=2).state == "unknown"


@pytest.mark.django_db
@pytest.mark.browser
@pytest.mark.parametrize("duplicate_count", [1, 9])
def test_real_browser_edit_with_bad_scenario_keeps_source_and_recovers_checks(workspace, duplicate_count):
    chat, _ = workspace
    source = saved(chat)
    source.checks.extend(deepcopy(source.checks[1]) for _ in range(duplicate_count))
    source.save(update_fields=["checks"])
    run = create_run(chat, edit_data(source))

    def bad_checks(request, **kwargs):
        result = edit_model(request, **kwargs)
        if request["operation"] == "edit" and not request.get("patch_repair"):
            result["response"]["patches"] = result["response"]["patches"][:1]
            control = deepcopy(fixture_response()["checks"][1])
            control["id"] = "extra"
            control["steps"] = [{"action": "checkpoint"}, {"action": "wait_for", "ms": 100}]
            control["expect"] = {"operator": "changed", "value": None}
            result["response"]["checks"] = [control]
        return result

    with patch("generation.providers.fake.generate", side_effect=bad_checks) as inference:
        process_run(str(run.id))
    run.refresh_from_db()
    assert [c.args[0]["operation"] for c in inference.call_args_list] == ["edit", "check_repair"]
    assert run.status == "unverified", (run.error, list(run.check_reports.values("findings")))
    original, fixed = run.revisions.order_by("number")
    assert original.files == fixed.files and fixed.reports.get().assessment["gates_passed"]
    assert all(f["status"] == "passed" for f in fixed.reports.get().facts)
    assert fixed.checks_review_required and not fixed.accepted
