from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from generation.artifacts import materialize
from generation.errors import ContractError
from generation.providers.fake import fixture_response
from generation.schema import RESPONSE_SCHEMA, response_schema, validate_checks
from validation.runner import compare


@pytest.mark.parametrize("operation", ["create", "edit", "repair"])
def test_operation_schema_prevents_wrong_files_patches_and_base(operation):
    request = {"operation": operation}
    schema = response_schema(request)
    response = fixture_response()
    if operation != "create":
        response.update(operation=operation, base_revision="base", files=[], patches=[], checks=[])
    validator = Draft202012Validator(schema)
    assert validator.is_valid(response)
    wrong = deepcopy(response)
    if operation == "create":
        wrong["base_revision"] = "made-up"
    else:
        wrong["files"] = fixture_response()["files"]
    assert not validator.is_valid(wrong)
    assert RESPONSE_SCHEMA["properties"]["files"]["maxItems"] == 20


def test_saved_v2_schema_is_preserved_and_unknown_version_fails_closed():
    assert response_schema({"operation": "repair", "generation_contract": {"pipeline_version": 2}}) == RESPONSE_SCHEMA
    with pytest.raises(ContractError, match="Неизвестная версия"):
        response_schema({"generation_contract": {"pipeline_version": 99}})


@pytest.mark.parametrize("change", ["steps", "observation", "expect", "requirement", "viewport", "add"])
def test_legacy_repair_cannot_change_or_add_acceptance_checks(change):
    response = fixture_response()
    base = materialize(response, operation="create")
    repair = deepcopy(response)
    repair.update(operation="repair", base_revision="base", files=[], patches=[])
    check = repair["checks"][1]
    replacements = {
        "steps": [check["steps"][0], check["steps"][0]],
        "observation": {"source": "text", "selector": "h1"},
        "expect": {"operator": "not_eq", "value": -100},
        "requirement": "Другое требование без исходного эффекта",
        "viewport": "desktop",
    }
    if change == "add":
        extra = deepcopy(check)
        extra["id"] = "extra"
        repair["checks"].append(extra)
    else:
        check[change] = replacements[change]
    with pytest.raises(ContractError) as caught:
        materialize(repair, operation="repair", base_revision="base", files=base["files"],
                    previous_checks=base["checks"])
    assert caught.value.code == "repair_checks_locked"
    assert base["checks"] == response["checks"]


@pytest.mark.parametrize("value", ["", "  ", "\n"])
def test_empty_contains_is_rejected_by_contract_and_runtime(value):
    checks = fixture_response()["checks"]
    checks[0]["expect"] = {"operator": "contains", "value": value}
    with pytest.raises(ContractError) as caught:
        validate_checks(checks)
    assert caught.value.code == "trivial_expectation"
    assert not compare("unchanged", "unchanged", checks[0]["expect"])


def test_new_repair_wire_schema_requires_empty_checks_even_if_legacy_checks_match():
    response = fixture_response()
    response.update(operation="repair", base_revision="base", files=[], patches=[])
    validator = Draft202012Validator(response_schema({"operation": "repair"}))
    assert not validator.is_valid(response)
    response["checks"] = []
    assert validator.is_valid(response)


def test_invalid_inherited_tests_request_application_review_instead_of_silent_weakening():
    response = fixture_response()
    base = materialize(response, operation="create")
    base["checks"][0]["expect"] = {"operator": "contains", "value": ""}
    response.update(operation="repair", base_revision="base", files=[], patches=[], checks=[])
    with pytest.raises(ContractError) as caught:
        materialize(response, operation="repair", base_revision="base", files=base["files"],
                    previous_checks=base["checks"])
    assert caught.value.code == "invalid_baseline_checks"
