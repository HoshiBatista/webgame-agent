import base64
import json
from copy import deepcopy

import pytest

from generation.errors import ContractError
from generation.feedback_image import MAX_IMAGE_BYTES, image_input
from generation.planning import should_plan, strategy
from generation.prompts import build_messages, system_prompt
from generation.providers.fake import generate as fake_generate
from generation.schema import response_schema, validate_response
from generation.service import generate


def plan_response():
    return fake_generate({"operation": "plan"}, on_event=lambda _: None, is_cancelled=lambda: False)["response"]


@pytest.mark.parametrize("profile", ["full", "compact"])
@pytest.mark.parametrize("strategy_name", ["lite", "pro"])
def test_planning_is_separate_from_artifact_and_compact_source_contract(profile, strategy_name):
    request = {"provider": "fake", "operation": "plan", "generation_profile": profile,
               "generation_strategy": strategy_name, "source_format": "lines"}
    result = generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result["response"] == plan_response()
    assert "files" not in result["response"] and "source_lines" not in result["response"]
    assert response_schema(request)["properties"]["plan"]["anyOf"][0]["properties"]["mechanics"]["maxItems"] == (
        4 if strategy_name == "pro" else 2
    )
    assert "game concept" in system_prompt(request)


@pytest.mark.parametrize("bad_field", ["plan", "operation", "unexpected"])
def test_malformed_plan_cannot_enter_durable_game_brief(bad_field):
    response = plan_response()
    response[bad_field] = {} if bad_field == "plan" else "create"
    with pytest.raises(ContractError):
        validate_response(response, operation="plan", schema=response_schema({"operation": "plan"}))


@pytest.mark.parametrize("profile", ["full", "compact"])
def test_saved_plan_and_user_edit_priority_survive_all_implementation_operations(profile):
    for operation in ("create", "edit", "repair"):
        request = {"operation": operation, "generation_profile": profile, "generation_strategy": "pro",
                   "game_plan": plan_response()["plan"], "prompt": "Убери врагов"}
        system, user = build_messages(request)
        assert "later explicit user edit takes priority" in system["content"]
        assert "Pro workflow" in system["content"]
        assert json.loads(user["content"])["game_plan"] == request["game_plan"]
        assert "Синий круг" in user["content"]


def test_lite_and_pro_scope_are_distinct_without_enabling_tools():
    lite = system_prompt({"operation": "create", "generation_strategy": "lite"})
    pro = system_prompt({"operation": "create", "generation_strategy": "pro"})
    assert "Avoid optional features" in lite and "Avoid optional features" not in pro
    assert "COMPLETE GAME CONCEPT" in pro
    assert "You have no tools" in lite and "You have no tools" in pro


def test_planning_policy_is_explicit_and_never_replans_edits():
    assert should_plan("pro", "create", "x" * 1000)
    assert should_plan("lite", "create", "Сделай бродилку")
    assert not should_plan("lite", "create", "x" * 321)
    assert not should_plan("pro", "edit", "Сделай бродилку")
    assert not should_plan("lite", "repair", "Сделай бродилку")
    assert should_plan("", "create", "game", provider="relay")
    assert should_plan("", "create", "x" * 1000, provider="codex", model="gpt-6-sol")
    assert strategy("codex", "gpt-6-sol") == "pro"
    assert strategy("relay", "gpt-6-sol") == "lite"


def screenshot_request():
    from tests.test_visual_review import encoded_image

    return {"generation_strategy": "pro", "base_revision": "revision", "artifact_hash": "a" * 64,
            "validation_evidence": {"artifact_hash": "a" * 64, "report_id": 42},
            "preview_image": {"artifact_hash": "a" * 64, "report_id": 42, "mime": "image/png",
                              "data": encoded_image((8, 8), fmt="PNG")}}


def test_only_bounded_same_candidate_frames_are_model_input():
    request = screenshot_request()
    assert image_input(request)["url"].startswith("data:image/png;base64,")
    for changes in ({"report_id": 43}, {"artifact_hash": "b" * 64}, {"mime": "text/html"},
                    {"data": "https://private.example"}, {"data": "file:///private/image"},
                    {"data": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"a" * MAX_IMAGE_BYTES).decode()}):
        altered = deepcopy(request)
        altered["preview_image"].update(changes)
        assert image_input(altered) is None
    assert image_input({**request, "generation_strategy": "lite"}) is None
    assert image_input({**request, "base_revision": None}) is None
    assert image_input({**request, "artifact_hash": "different"}) is None
