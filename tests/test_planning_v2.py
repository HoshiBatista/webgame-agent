from copy import deepcopy

import pytest

from generation.errors import ContractError
from generation.planning import validate_plan
from generation.providers.fake import generate
from generation.requirements import coverage, manifest
from generation.schema import response_schema, validate_response


def proposed():
    request = {"operation": "plan", "prompt": "Простая статичная игра: три попадания."}
    return request, generate(request, on_event=lambda _: None, is_cancelled=lambda: False)["response"]


@pytest.mark.parametrize(
    "fault",
    [
        "null_success",
        "refusal_object",
        "no_choices",
        "duplicate_id",
        "no_outcome",
        "false_quote",
        "false_origin",
        "no_mobile",
        "foreign_request",
    ],
)
def test_structural_refusal_and_provenance_corpus(fault):
    request, response = proposed()
    plan = response["plan"]
    if fault == "null_success":
        response["plan"] = None
    elif fault == "refusal_object":
        response["status"] = "scope_refusal"
    elif fault == "no_choices":
        del plan["decision"]
    elif fault == "duplicate_id":
        plan["requirements"][1]["id"] = plan["requirements"][0]["id"]
    elif fault == "no_outcome":
        plan["requirements"][-1]["category"] = "control"
    elif fault == "false_quote":
        plan["requirements"][0].update(origin="user", quote="Добавь четырёх врагов")
    elif fault == "false_origin":
        plan["requirements"][0]["quote"] = "Простая"
    elif fault == "no_mobile":
        plan["requirements"][0]["viewport"] = "desktop"
    else:
        plan["request_reference"] = "Совсем другой запрос"
    with pytest.raises(ContractError):
        validate_response(response, operation="plan", schema=response_schema(request))
        validate_plan(response, request)


def test_simple_single_mechanic_and_honest_refusal_are_valid_distinct_shapes():
    request, response = proposed()
    validate_response(response, operation="plan", schema=response_schema(request))
    validate_plan(response, request)
    assert len(response["plan"]["mechanics"]) == 1
    response.update(
        status="scope_refusal", message="Нельзя вместить; предлагаю одну короткую партию.", plan=None
    )
    validate_response(response, operation="plan", schema=response_schema(request))
    validate_plan(response, request)


def test_manifest_is_a_copy_and_is_not_an_independent_semantic_oracle():
    request, response = proposed()
    frozen = manifest(request["prompt"], response["plan"])
    checks = [
        {k: r[k] for k in ("id", "category", "requirement", "viewport")} for r in frozen["requirements"]
    ]
    response["plan"]["requirements"][0]["requirement"] = "changed after save"
    assert not coverage(checks, frozen)["uncovered"]
    changed = deepcopy(checks)
    changed[0]["requirement"] = "Игра с другими правилами"
    assert coverage(changed, frozen)["uncovered"] == [checks[0]["id"]]
    assert coverage(checks, frozen)["independent_semantic_verification"] is False
    edit = manifest(request["prompt"], previous=frozen, amendment="Только два попадания")
    next_edit = manifest(request["prompt"], previous=edit, amendment="Цвет зелёный")
    assert next_edit["amendments"] == ["Только два попадания", "Цвет зелёный"]
    assert next_edit["requirements"] == frozen['requirements'] and next_edit["request"] == request["prompt"]


def test_well_formed_semantic_lie_is_not_claimed_to_be_detected_by_schema():
    request, response = proposed()
    # Explicit residual risk for a later real-model corpus: structural fields cannot prove meaning.
    response["plan"]["summary"] = "Я не могу сделать эту игру, но заполняю все обязательные поля."
    validate_response(response, operation="plan", schema=response_schema(request))
    validate_plan(response, request)
    assert (
        coverage([], manifest(request["prompt"], response["plan"]))["independent_semantic_verification"]
        is False
    )
