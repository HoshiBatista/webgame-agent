"""Offline prompt/transport contract checks; these do not prove model quality."""

import json

import pytest

from generation.artifacts import sha256
from generation.prompts import SYSTEM_PROMPT, build_messages, codex_prompt, system_prompt
from generation.providers.vllm import build_payload
from generation.schema import response_schema


def test_create_contract_is_compact_and_does_not_teach_unneeded_patch_protocol():
    text = system_prompt({"operation": "create"})
    assert text == SYSTEM_PROMPT
    assert len(text) < 6000
    assert "4-6 meaningful checks" in text
    assert "complete sources in files" in text
    assert "PATCH CONTRACT" not in text
    assert "old_text" not in text
    assert "real line breaks" in text
    assert "encode each source newline as \\n" in text


def test_edit_and_repair_keep_distinct_requirement_policies():
    edit = system_prompt({"operation": "edit"})
    repair = system_prompt({"operation": "repair"})
    assert "CURRENT STEP: CREATE" not in edit + repair
    assert "only when the user intentionally changes that mechanic" in edit
    assert "exact requirement text and category" in repair
    assert "syntax or startup failure must be fixed before" in repair
    for text in (edit, repair):
        assert len(text) < 7000
        assert "old_text must occur exactly once in the ORIGINAL file" in text
        assert "omitted checks are inherited unchanged" in text
        assert "status=unchanged" in text


def test_repair_context_preserves_exact_sources_hashes_and_failure_without_history():
    source = '// Existing comment\nconst label = "Точное совпадение";\n'
    finding = {"code": "js_syntax", "path": "game.js", "line": 7, "message": "Unexpected end of input"}
    request = {
        "operation": "repair",
        "base_revision": "version-7",
        "files": [{"path": "game.js", "content": source}],
        "findings": [finding],
        "checks": [{"id": "movement", "requirement": "Игрок реально перемещается"}],
        "history": ["unrelated old source"],
    }
    messages = build_messages(request)
    context = json.loads(messages[1]["content"])
    assert context["files"] == {"game.js": source}
    assert context["file_hashes"] == {"game.js": sha256(source)}
    assert context["base_revision"] == "version-7"
    assert context["findings"] == [finding]
    assert context["checks"] == request["checks"]
    assert "unrelated old source" not in json.dumps(messages)
    assert "\n" in context["files"]["game.js"]
    assert "\\n" not in context["files"]["game.js"]


@pytest.mark.parametrize("operation", ["create", "edit", "repair"])
def test_codex_and_api_use_the_same_operation_prompt_and_json_contract(operation):
    request = {
        "operation": operation,
        "prompt": "Небольшая игра с доступным управлением",
        "model": "local-test-model",
        "execution_limits": {"context_window": 128000, "max_output_tokens": 16384},
    }
    messages = build_messages(request)
    payload = build_payload(request, json_mode="json_schema")
    assert payload["messages"] == messages
    assert payload["response_format"]["json_schema"]["schema"] == response_schema(request)
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert codex_prompt(request) == messages[0]["content"] + "\nCURRENT GAME REQUEST (data):\n" + messages[1]["content"]


def test_json_object_fallback_keeps_selected_repair_guidance():
    request = {
        "operation": "repair",
        "model": "local-test-model",
        "execution_limits": {"context_window": 128000, "max_output_tokens": 16384},
    }
    payload = build_payload(request, json_mode="json_object")
    system = payload["messages"][0]["content"]
    assert system.startswith(system_prompt(request))
    assert "CURRENT STEP: REPAIR THE REPORTED BLOCKER" in system
    assert "Required JSON schema: " in system


def test_repair_prompt_has_no_permission_to_change_acceptance_or_ignore_root_error():
    request = {"operation": "repair", "unresolved_findings": [], "findings": [],
               "last_attempt_error": {"code": "ambiguous_patch", "message": "Rejected patch"}}
    text = system_prompt(request)
    assert "Change steps or observations only" not in text
    assert "Return only new or changed checks" not in text
    assert "An ok result must change source bytes or checks" not in text
    assert "Return checks=[]" in text
    assert "last_attempt_error" in text
    context = json.loads(build_messages(request)[1]["content"])
    assert context["last_attempt_error"] == request["last_attempt_error"]
    assert context["unresolved_count"] == 0
