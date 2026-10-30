"""Interrupted replies are immutable; completion is metered and never accepts a game itself."""

import json
from copy import deepcopy
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

from generation.artifacts import materialize
from generation.errors import ContractError
from generation.helpers import catalog
from generation.prompts import build_messages
from generation.providers.fake import fixture_response
from generation.relay_api.protocol import digest
from generation.response_completion import assemble, permission, reply_schema
from generation.service import generate
from studio.services import create_run
from studio.tasks import process_run
from tests import test_codex_api

api = test_codex_api.api
run = test_codex_api.run


def interrupted(response=None, retained_count=2):
    response = response or fixture_response(with_assets=True)
    fields = {k: response[k] for k in ("assets", "base_revision", "checks", "design")}
    prefix = json.dumps(fields, ensure_ascii=False)[:-1] + ',"files":['
    completed = ",".join(json.dumps(f, ensure_ascii=False) for f in response["files"][:retained_count])
    return prefix + completed + ("," if completed else "") + '{"content":"window.game'


def scenario():
    response = fixture_response(with_assets=True)
    request = {
        "operation": "create",
        "generation_profile": "full",
        "helper_catalog": catalog(),
        "generation_contract": {"pipeline_version": 9},
        "provider": "fake",
    }
    raw = interrupted(response)
    request["response_completion"] = permission(raw, request, "original-call")
    return response, raw, request


def completion(response, request):
    policy = request["response_completion"]
    fields = {k: deepcopy(response[k]) for k in policy["missing_fields"]}
    fields["files"] = fields["files"][len(policy["retained_files"]) :]
    return {"source_sha256": policy["source_sha256"], "completion": fields}


def test_complete_only_missing_files_preserves_actual_game_and_full_contract():
    response, raw, request = scenario()
    before = deepcopy(request)
    reply = completion(response, request)
    assert Draft202012Validator(reply_schema(request)).is_valid(reply)
    result = assemble(reply, request)
    assert result == response
    assert materialize(result, operation="create", helper_catalog=catalog()) == materialize(
        response, operation="create", helper_catalog=catalog()
    )
    assert request == before and raw == interrupted(response)
    messages = build_messages(request)
    context = json.loads(messages[1]["content"])
    assert context["response_completion"] == request["response_completion"]
    assert "not a JSON suffix" in messages[0]["content"]
    with patch("generation.providers.fake.generate", return_value={"response": reply, "usage": {}}):
        received = generate(request, on_event=lambda *a: None, is_cancelled=lambda: False)
    assert received["response"] == response and received["raw_response"] == reply
    assert received["provider_metadata"]["response_completion"]["source_invocation"] == "original-call"


@pytest.mark.parametrize(
    "fault", ["changed_hash", "retained_assets", "overwrite_file", "missing_file", "extra", "incomplete_file"]
)
def test_changed_identity_or_saved_parts_are_rejected(fault):
    response, _, request = scenario()
    reply = completion(response, request)
    if fault == "changed_hash":
        reply["source_sha256"] = "0" * 64
    elif fault == "retained_assets":
        reply["completion"]["assets"] = response["assets"]
    elif fault == "overwrite_file":
        reply["completion"]["files"].append(response["files"][0])
    elif fault == "missing_file":
        del reply["completion"]["files"]
    elif fault == "extra":
        reply["unknown"] = True
    else:
        reply["completion"]["files"][0]["content"] = ""
    with pytest.raises(ContractError):
        materialize(assemble(reply, request), operation="create", helper_catalog=catalog())


@pytest.mark.parametrize(
    "fault",
    [
        "complete",
        "duplicate",
        "invalid_assets",
        "early_cut",
        "oversize",
        "compact",
        "edit",
        "recursive",
        "invalid_file",
    ],
)
def test_only_bounded_valid_completed_prefix_can_be_retained(fault):
    response, raw, request = scenario()
    request.pop("response_completion")
    if fault == "complete":
        raw = json.dumps(response)
    elif fault == "duplicate":
        raw = raw.replace('"base_revision": null', '"base_revision": null,"base_revision": null')
    elif fault == "invalid_assets":
        response["assets"] = {"bad": True}
        raw = interrupted(response)
    elif fault == "early_cut":
        raw = raw[:100]
    elif fault == "oversize":
        raw += "x" * 100_000
    elif fault == "compact":
        request["generation_profile"] = "compact"
    elif fault == "edit":
        request["operation"] = "edit"
    elif fault == "recursive":
        request["response_completion"] = {"source_sha256": "x"}
    else:
        response["files"][0]["bad"] = True
        raw = interrupted(response)
    assert permission(raw, request, "original") is None


def limited(api, invocation, *, unknown=False):
    api.finish(str(invocation.id), state="unknown" if unknown else "failed")
    row = api.jobs[str(invocation.id)]
    row["receipt"]["error"] = {"code": "codex_turn_failed", "outcome_unknown": unknown}
    row["receipt"]["metadata"].update(
        turn_status="failed", provider_error={"category": "other", "incomplete_reason": "max_output_tokens"}
    )
    row["receipt"]["partial_response"] = interrupted()
    row["receipt_hash"] = digest(row["receipt"])


@pytest.mark.django_db(transaction=True)
def test_known_limit_finishes_only_missing_source_in_shared_budget(run, api):
    run.model_call_limit = 2
    run.save(update_fields=["model_call_limit"])
    process_run(str(run.id))
    first = run.invocations.get()
    limited(api, first)
    receipt = deepcopy(api.jobs[str(first.id)])
    process_run(str(run.id))
    second = run.invocations.latest("attempt")
    assert first.id != second.id and second.request["response_completion"]
    reply = completion(fixture_response(with_assets=True), second.request)
    api.finish(str(second.id), reply)
    process_run(str(run.id))
    run.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert run.invocations.count() == api.inferences == 2
    assert first.state == "failed" and first.raw_response == interrupted()
    assert second.raw_response == json.dumps(reply)
    assert first.usage and second.usage and first.cost_usd is not None
    assert api.jobs[str(first.id)] == receipt
    assert run.result_revision.checks == fixture_response(with_assets=True)["checks"]


@pytest.mark.django_db(transaction=True)
def test_budget_limit_and_explicit_continuation_adopt_new_policy_without_replanning(run, api):
    from generation.requirements import policy_snapshot

    process_run(str(run.id))
    first = run.invocations.get()
    limited(api, first)
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.invocations.count() == 1 and run.error["code"] == "response_output_limit"
    assert "слишком длинным" in run.chat_messages.get(role="assistant").content
    run.policy_snapshot = {"old": True}
    run.save(update_fields=["policy_snapshot"])
    with patch("studio.services.schedule"):
        child = create_run(
            run.chat,
            {"idempotency_key": "finish", "model_profile": "pro", "model_call_limit": 1},
            continued_from=run,
        )
    assert child.policy_snapshot == policy_snapshot()
    run.refresh_from_db()
    assert run.policy_snapshot == {"old": True}
    assert child.events.filter(kind="response_completion_policy").count() == 1
    process_run(str(child.id))
    second = child.invocations.get()
    assert second.request["operation"] == "create" and second.request["response_completion"][
        "source_invocation"
    ] == str(first.id)
    api.finish(str(second.id), completion(fixture_response(with_assets=True), second.request))
    process_run(str(child.id))
    child.refresh_from_db()
    assert child.status == "succeeded", child.error
    assert api.inferences == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fault", ["unknown", "completion_failed", "completion_invalid"])
def test_no_retry_loop_or_unknown_replay(run, api, fault):
    run.model_call_limit = 4
    run.save(update_fields=["model_call_limit"])
    process_run(str(run.id))
    first = run.invocations.get()
    limited(api, first, unknown=fault == "unknown")
    process_run(str(run.id))
    if fault == "unknown":
        run.refresh_from_db()
        assert run.status == "unknown" and run.invocations.count() == 1
    else:
        second = run.invocations.latest("attempt")
        if fault == "completion_failed":
            limited(api, second)
        else:
            api.finish(str(second.id), {"source_sha256": "0" * 64, "completion": {}})
        process_run(str(run.id))
        run.refresh_from_db()
        assert run.status == "failed" and run.invocations.count() == 2
    process_run(str(run.id))
    assert run.invocations.count() == (1 if fault == "unknown" else 2)


@pytest.mark.django_db(transaction=True)
def test_bad_completed_sources_do_not_trigger_full_regeneration(run, api):
    run.model_call_limit = 4
    run.save(update_fields=["model_call_limit"])
    process_run(str(run.id))
    limited(api, run.invocations.get())
    process_run(str(run.id))
    second = run.invocations.latest("attempt")
    response = fixture_response(with_assets=True)
    response["files"][2]["content"] = "// unfinished"
    api.finish(str(second.id), completion(response, second.request))
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.error["code"] == "invalid_response_completion"
    assert run.invocations.count() == 2 and run.candidate_revision_id is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("changed", ["prompt", "helpers", "unknown", "newer_receipt"])
def test_policy_adoption_is_not_general_permission_to_reuse_old_partial(run, api, changed):
    from studio.models import Invocation

    process_run(str(run.id))
    first = run.invocations.get()
    limited(api, first)
    process_run(str(run.id))
    run.refresh_from_db()
    run.policy_snapshot = {"old": True}
    if changed == "helpers":
        run.helper_catalog = {}
    if changed == "unknown":
        first.refresh_from_db()
        first.state = "unknown"
        first.save(update_fields=["state"])
    if changed == "newer_receipt":
        Invocation.objects.create(
            run=run, attempt=2, state="failed", request=first.request, error={"code": "invalid_json"}
        )
    run.save()
    data = {"idempotency_key": "changed", "model_profile": "pro", "model_call_limit": 1}
    if changed == "prompt":
        data["prompt"] = "Совсем другая игра"
    with patch("studio.services.schedule"):
        if changed == "unknown":
            from studio.services import DomainError

            with pytest.raises(DomainError):
                create_run(run.chat, data, continued_from=run)
            return
        child = create_run(run.chat, data, continued_from=run)
    assert child.policy_snapshot == {"old": True}
    assert not child.events.filter(kind="response_completion_policy").exists()


@pytest.mark.browser
def test_assembled_source_still_runs_original_scenarios_in_real_browser():
    from validation.service import validate

    response, _, request = scenario()
    artifact = materialize(
        assemble(completion(response, request), request), operation="create", helper_catalog=catalog()
    )
    result = validate(artifact["html"], artifact["checks"], artifact_hash=artifact["artifact_hash"])
    assert result["status"] == "passed", result["findings"]
    assert len(result["facts"]) == len(response["checks"])


def test_non_finite_completed_values_are_not_retained():
    response, raw, request = scenario()
    request.pop("response_completion")
    raw = raw.replace('"value": 1', '"value": 1e999')
    assert permission(raw, request, "source") is None
