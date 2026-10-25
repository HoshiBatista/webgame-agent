import hashlib
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from generation.artifacts import materialize, sha256
from generation.errors import ContractError
from generation.prompts import build_messages, system_prompt
from generation.providers.fake import fixture_response
from generation.schema import response_schema
from generation.source_policy import MAX_MODULE_BYTES, module_policy
from studio.services import fingerprint


def base_game():
    return materialize(fixture_response(), operation="create")


def replacement(base):
    response = fixture_response()
    response.update(operation="repair", base_revision="base", files=[], checks=[], patches=[{
        "action": "replace_module", "path": "game.js", "file_hash": base["file_hashes"]["game.js"],
        "content": base["files"]["game.js"].replace("hits>=3", "hits>=4"),
    }])
    return response


def repair(response, base, **kwargs):
    return materialize(response, operation="repair", base_revision="base", files=base["files"],
                       previous_checks=base["checks"], **kwargs)


@pytest.mark.parametrize("files", [
    {"index.html": "<!DOCTYPE html> <!-- line -->", "game.js": "", "styles.css": ""},
    {"index.html": "<!DOCTYPE html><html></html>"},
    {"index.html": '<canvas></canvas><script src="game.js"></script>'},
    {"index.html": '<canvas></canvas><script src="game.js"></script>', "game.js": "// TODO\n/* later */"},
    {"index.html": '<canvas></canvas><script type="application/json">{"ready":true}</script>'},
    {"index.html": '<button onclick="/* todo */">Играть</button>'},
    {"index.html": '<canvas onclick></canvas>'},
])
def test_incomplete_creates_never_become_candidates(files):
    response = fixture_response()
    response["files"] = [{"path": p, "content": c} for p, c in files.items()]
    with pytest.raises(ContractError) as caught:
        materialize(response, operation="create")
    assert caught.value.code == "incomplete_sources"
    assert response["files"] == [{"path": p, "content": c} for p, c in files.items()]


@pytest.mark.parametrize("document", [
    '<script>document.body.appendChild(document.createElement("canvas"));</script>',
    '<canvas onclick="this.getContext(\'2d\').fillRect(0,0,20,20)"></canvas>',
    '<script>/* description */\n// setup\nconst label="http://example";</script>',
    '<script>/* unfinished comment</script>',  # Syntax validation owns this defect.
    '<script>// comment\rwindow.x=1;</script>',
    '<script><!-- comment\u2028window.x=1;</script>',
])
def test_structural_admission_does_not_require_static_canvas_or_specific_file_layout(document):
    response = fixture_response()
    response["files"] = [{"path": "index.html", "content": document}]
    assert materialize(response, operation="create")["html"] == document


def test_saved_v4_stub_is_not_reinterpreted_by_new_admission():
    response = fixture_response()
    response["files"] = [{"path": "index.html", "content": "<!DOCTYPE html> <!-- line -->"}]
    assert materialize(response, operation="create", generation_contract={"pipeline_version": 4})["html"]
    request = {"operation": "create", "generation_contract": {"pipeline_version": 4}}
    assert hashlib.sha256(system_prompt(request).encode()).hexdigest() == "2342bcb4783db2682b01736a210162e45bc94003bb262c4b1bfb6219758f4c6c"
    assert fingerprint(response_schema(request)) == "9dfc3800f4b0d7af33c6d8483344a37813f871f3b877107ce49d702e92375efe"


def test_unknown_materialization_contract_is_not_interpreted_as_the_latest():
    with pytest.raises(ContractError) as caught:
        materialize(fixture_response(), operation="create", generation_contract={"pipeline_version": 99})
    assert caught.value.code == "unknown_contract"


def test_complete_module_replacement_keeps_neighbouring_bytes_and_all_requirements():
    base = base_game()
    original = deepcopy(base)
    policy = module_policy(base["files"], [{"code": "effect_mismatch"}])
    result = repair(replacement(base), base, module_repair=policy)
    assert result["checks"] == original["checks"]
    assert result["files"]["index.html"] == original["files"]["index.html"]
    assert result["files"]["styles.css"] == original["files"]["styles.css"]
    assert result["files"]["game.js"] != original["files"]["game.js"]
    assert base == original


@pytest.mark.parametrize("mutation,code", [
    (lambda r, b: r.update(base_revision="other"), "stale_revision"),
    (lambda r, b: r["patches"][0].update(file_hash="0" * 64), "stale_file"),
    (lambda r, b: r["patches"][0].update(path="../secret.js"), "unsafe_path"),
    (lambda r, b: r["patches"][0].update(path="index.html"), "module_scope"),
    (lambda r, b: r["patches"][0].update(path="new.js"), "module_scope"),
    (lambda r, b: r["patches"][0].update(content="я" * (MAX_MODULE_BYTES // 2 + 1)), "module_too_large"),
    (lambda r, b: r["patches"].append(deepcopy(r["patches"][0])), "module_scope"),
    (lambda r, b: r["patches"].append({"path": "styles.css", "file_hash": b["file_hashes"]["styles.css"],
                                     "old_text": "#eff4ff", "new_text": "red"}), "module_scope"),
    (lambda r, b: r.update(checks=[{**b["checks"][0], "requirement": "Другое требование"}]), "repair_checks_locked"),
])
def test_replacement_failures_are_atomic_and_preserve_the_original(mutation, code):
    base = base_game()
    original = deepcopy(base)
    response = replacement(base)
    mutation(response, base)
    with pytest.raises(ContractError) as caught:
        repair(response, base, module_repair=module_policy(base["files"], [{"code": "effect_mismatch"}]))
    assert caught.value.code == code
    assert base == original


@pytest.mark.parametrize("version", [2, 3, 4, 5])
def test_replacement_requires_explicit_v5_repair_permission(version):
    base = base_game()
    response = replacement(base)
    request = {"operation": "repair", "generation_contract": {"pipeline_version": version}}
    assert not Draft202012Validator(response_schema(request)).is_valid(response)
    if version < 5:
        with pytest.raises(ContractError) as caught:
            repair(response, base, generation_contract=request["generation_contract"],
                   module_repair=module_policy(base["files"], [{"code": "effect_mismatch"}]))
        assert caught.value.code == "module_scope"
    else:
        request["module_repair"] = module_policy(base["files"], [{"code": "effect_mismatch"}])
        assert Draft202012Validator(response_schema(request)).is_valid(response)
        request["operation"] = response["operation"] = "edit"
        assert not Draft202012Validator(response_schema(request)).is_valid(response)
        with pytest.raises(ContractError) as caught:
            materialize(response, operation="edit", base_revision="base", files=base["files"],
                        previous_checks=base["checks"], module_repair=request["module_repair"])
        assert caught.value.code == "module_scope"


def test_permission_is_not_inferred_from_a_small_helper_or_stale_file_location():
    files = {"small.js": "const x=1;", "game.js": "x" * (MAX_MODULE_BYTES + 1)}
    assert not module_policy(files, [{"code": "effect_mismatch"}])["files"]
    assert not module_policy(files, [{"code": "javascript_syntax", "path": "small.js", "file_hash": "wrong"}])["files"]
    policy = module_policy(files, [{"code": "javascript_syntax", "path": "small.js", "file_hash": sha256(files["small.js"])}])
    assert policy["files"] == {"small.js": sha256(files["small.js"])}


def test_generated_schemas_do_not_share_mutable_patch_definitions():
    request = {"operation": "repair", "module_repair": {"files": {"game.js": "hash"}}}
    first = response_schema(request)
    pristine = deepcopy(first)
    first["properties"]["patches"]["anyOf"][0]["items"]["required"].clear()
    assert response_schema(request) == pristine


def test_codex_and_api_context_keep_exact_source_and_application_permissions():
    import json

    from generation.prompts import codex_prompt
    from generation.providers.vllm import build_payload

    base = base_game()
    request = {"operation": "repair", "files": base["files"], "model": "test",
               "module_repair": module_policy(base["files"], [{"code": "effect_mismatch"}]),
               "execution_limits": {"context_window": 128000, "max_output_tokens": 16384}}
    messages = build_messages(request)
    assert json.loads(messages[1]["content"])["module_repair"] == request["module_repair"]
    assert "replace_module" in codex_prompt(request)
    payload = build_payload(request, json_mode="json_schema")
    assert payload["messages"] == messages
    assert payload["response_format"]["json_schema"]["schema"] == response_schema(request)
