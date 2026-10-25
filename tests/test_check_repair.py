from copy import deepcopy

import pytest

from generation.artifacts import materialize
from generation.check_repair import permission
from generation.errors import ContractError
from generation.prompts import build_messages
from generation.providers.fake import fixture_response
from generation.schema import response_schema, validate_response


def proposal(base, checks=None):
    policy = permission(base["artifact_hash"], base["checks"], base.get("design", {}))
    originals = {c["id"]: c for c in fixture_response()["checks"]}
    suite = []
    for entry in policy["requirements"]:
        check = deepcopy(originals.get(entry["id"], originals.get(entry["category"], originals["tap"])))
        check.update(entry)
        suite.append(check)
    return {
        "status": "ok",
        "operation": "check_repair",
        "base_revision": "base",
        "artifact_hash": policy["artifact_hash"],
        "checks_hash": policy["checks_hash"],
        "message": "Исправлены сценарии без изменения игры.",
        "checks": suite if checks is None else checks,
    }, policy


def apply(response, policy, base):
    return materialize(
        response,
        operation="check_repair",
        base_revision="base",
        files=base["files"],
        previous_checks=base["checks"],
        generation_contract={"pipeline_version": 8},
        check_repair=policy,
    )


def test_complete_source_is_retained_when_create_checks_are_incomplete():
    response = fixture_response()
    response["checks"] = response["checks"][:2]
    base = materialize(response, operation="create")
    assert base["files"] == {f["path"]: f["content"] for f in response["files"]}
    assert base["checks"] == response["checks"]
    fixed, policy = proposal(base)
    result = apply(fixed, policy, base)
    assert result["html"] == base["html"] and result["file_hashes"] == base["file_hashes"]
    assert result["checks_review_required"] and len(result["checks"]) == 3
    assert base["checks"] == response["checks"]  # Original suite is immutable.


@pytest.mark.parametrize(
    "field,value", [("artifact_hash", "0" * 64), ("checks_hash", "0" * 64), ("base_revision", "another")]
)
def test_proposal_cannot_target_another_artifact_or_suite(field, value):
    response = fixture_response()
    response["checks"] = response["checks"][:2]
    base = materialize(response, operation="create")
    fixed, policy = proposal(base)
    fixed[field] = value
    with pytest.raises(ContractError):
        apply(fixed, policy, base)


@pytest.mark.parametrize(
    "mutation", ["source", "patch", "removed", "requirement", "category", "viewport", "id"]
)
def test_proposal_cannot_change_source_or_weaken_locked_requirement_identity(mutation):
    response = fixture_response()
    response["checks"] = response["checks"][:2]
    base = materialize(response, operation="create")
    fixed, policy = proposal(base)
    if mutation == "source":
        fixed["files"] = response["files"]
    elif mutation == "patch":
        fixed["patches"] = []
    elif mutation == "removed":
        fixed["checks"].pop(0)
    else:
        fixed["checks"][0][mutation] = {
            "requirement": "Совсем другое условие",
            "category": "regression",
            "viewport": "desktop",
            "id": "another",
        }[mutation]
    with pytest.raises(ContractError):
        apply(fixed, policy, base)


def test_schema_and_prompt_are_source_free_for_both_provider_paths():
    base = materialize(fixture_response(), operation="create")
    fixed, policy = proposal(base)
    req = {
        "operation": "check_repair",
        "check_repair": policy,
        "files": base["files"],
        "base_revision": "base",
        "generation_contract": {"pipeline_version": 8},
    }
    validate_response(fixed, operation="check_repair", schema=response_schema(req))
    messages = build_messages(req)
    assert "Do not return or modify game source" in messages[0]["content"]
    assert "check_repair" in messages[1]["content"]
    assert not {"files", "patches", "design", "title"} & response_schema(req)["properties"].keys()
    with pytest.raises(ContractError):
        response_schema({**req, "generation_contract": {"pipeline_version": 5}})
