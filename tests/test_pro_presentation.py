"""Pro presentation admission/routing, without drawing conclusions about model art quality."""

import json
from copy import deepcopy

import pytest

from generation.errors import ContractError
from generation.presentation import IMPLEMENTATION_GUIDANCE, PLAN_GUIDANCE, PRESERVATION_GUIDANCE, VERSION
from generation.prompts import build_messages, system_prompt
from generation.providers.fake import generate as fixture
from generation.schema import response_schema, validate_response
from generation.service import generate


def request_for(operation="plan", profile="full"):
    return {"operation": operation, "provider": "fake", "generation_strategy": "pro",
            "presentation_policy": VERSION, "generation_profile": profile}


@pytest.mark.parametrize("profile", ["full", "compact"])
def test_new_pro_plan_requires_both_art_direction_and_motion(profile):
    request = request_for(profile=profile)
    result = generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    plan = result["response"]["plan"]
    assert set(plan["presentation"]) == {"art_direction", "motion"}
    assert result["provider_metadata"]["request_profile"]["presentation_policy"] == VERSION
    for key in ["art_direction", "motion"]:
        invalid = deepcopy(result["response"])
        del invalid["plan"]["presentation"][key]
        with pytest.raises(ContractError):
            validate_response(invalid, operation="plan", schema=response_schema(request))
    assert PLAN_GUIDANCE in system_prompt(request)


def test_explicit_static_request_can_have_a_valid_accessible_presentation_brief():
    request = {**request_for(), "prompt": "Статичная настольная игра, без анимаций"}
    response = fixture(request, on_event=lambda _: None, is_cancelled=lambda: False)["response"]
    response["plan"]["presentation"]["motion"] = "По просьбе игрока изменения отображаются сразу, без декоративного движения."
    validate_response(response, operation="plan", schema=response_schema(request))
    assert json.loads(build_messages(request)[1]["content"])["prompt"] == request["prompt"]


@pytest.mark.parametrize("value", ["", "...", None, ["fade"]])
def test_placeholder_or_malformed_motion_cannot_be_saved_as_a_pro_brief(value):
    request = request_for()
    response = fixture(request, on_event=lambda _: None, is_cancelled=lambda: False)["response"]
    response["plan"]["presentation"]["motion"] = value
    with pytest.raises(ContractError):
        validate_response(response, operation="plan", schema=response_schema(request))


@pytest.mark.parametrize("profile", ["full", "compact"])
@pytest.mark.parametrize("operation", ["create", "edit", "repair"])
def test_presentation_reaches_implementation_and_preserves_scoped_changes(profile, operation):
    request = request_for(operation, profile)
    plan = fixture(request_for(), on_event=lambda _: None, is_cancelled=lambda: False)["response"]["plan"]
    request["game_plan"] = plan
    system, user = build_messages(request)
    assert json.loads(user["content"])["game_plan"]["presentation"] == plan["presentation"]
    assert IMPLEMENTATION_GUIDANCE in system["content"]
    assert (PRESERVATION_GUIDANCE in system["content"]) == (operation != "create")
    # The compact scheduler cannot be replaced by a second generated RAF loop.
    if profile == "compact":
        assert "supplied update(dt) in seconds" in system["content"]
        assert "requestAnimationFrame" not in system["content"]
    else:
        assert "requestAnimationFrame timestamps/elapsed seconds" in system["content"]


@pytest.mark.parametrize("profile", ["full", "compact"])
def test_scenario_repair_cannot_become_an_art_or_animation_rewrite(profile):
    request = request_for("check_repair", profile)
    request["game_plan"] = fixture(request_for(), on_event=lambda _: None, is_cancelled=lambda: False)["response"]["plan"]
    system, user = build_messages(request)
    assert json.loads(user["content"])["game_plan"] == request["game_plan"]
    assert IMPLEMENTATION_GUIDANCE not in system["content"]
    assert PRESERVATION_GUIDANCE not in system["content"]
    assert "do not expand them from the plan or implement source changes" in system["content"]


def test_old_planning_contract_is_rejected_and_current_pro_requires_presentation():
    request = {"operation": "plan", "generation_strategy": "pro"}
    with pytest.raises(ContractError, match="Неизвестная версия"):
        response_schema({**request, "generation_contract":{"pipeline_version":8}})
    response = fixture({"operation": "plan"}, on_event=lambda _: None, is_cancelled=lambda: False)["response"]
    validate_response(response, operation="plan", schema=response_schema(request))
    with pytest.raises(ContractError):
        validate_response(response, operation="plan", schema=response_schema(request_for()))


@pytest.mark.parametrize("operation", ["plan", "create", "edit", "repair", "check_repair"])
def test_presentation_policy_does_not_expand_lite(operation):
    request = {**request_for(operation), "generation_strategy": "lite"}
    assert system_prompt(request) == system_prompt({**request, "presentation_policy": 0})
    if operation == "plan":
        assert "presentation" not in response_schema(request)["properties"]["plan"]["anyOf"][0]["properties"]


def test_unknown_presentation_version_cannot_silently_change_a_sent_contract():
    with pytest.raises(ContractError) as caught:
        response_schema({**request_for(), "presentation_policy": VERSION + 1})
    assert caught.value.code == "unknown_presentation_policy"
