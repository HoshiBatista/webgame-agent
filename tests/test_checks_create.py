from copy import deepcopy

import pytest

from generation.artifacts import materialize
from generation.check_repair import permission
from generation.errors import ContractError
from generation.prompts import build_messages
from generation.requirements import digest, manifest
from generation.schema import response_schema
from tests.test_compact_generation import compact_response


def specimen():
    response = compact_response()
    probes = response.pop("probes")
    frozen = manifest(
        "Три попадания",
        {"requirements": [{k: p[k] for k in ("id", "category", "requirement", "viewport")} for p in probes]},
    )
    game = materialize(
        response,
        operation="create",
        generation_profile="compact",
        generation_strategy="lite_code_then_checks",
    )
    policy = {
        **permission(game["artifact_hash"], [], game["design"], frozen),
        "base_revision": "candidate",
        "manifest_hash": digest(frozen),
    }
    reply = {
        "status": "ok",
        "message": "Составлены сценарии",
        "base_revision": "candidate",
        "artifact_hash": game["artifact_hash"],
        "manifest_hash": digest(frozen),
        "observations": response["observations"],
        "probes": probes,
    }
    options = dict(
        operation="checks_create",
        base_revision="candidate",
        files=game["files"],
        previous_checks=[],
        generation_profile="compact",
        compact_manifest=game["compact_manifest"],
        checks_create=policy,
        requirement_manifest=frozen,
    )
    return game, reply, options


@pytest.mark.parametrize("fault", ["source", "edits", "base", "artifact", "manifest", "promise", "missing"])
def test_checks_create_cannot_change_source_or_frozen_promise(fault):
    _, reply, options = specimen()
    if fault == "source":
        reply["source"] = "changed"
    elif fault == "edits":
        reply["edits"] = []
    elif fault in {"base", "artifact", "manifest"}:
        reply[{"base": "base_revision", "artifact": "artifact_hash", "manifest": "manifest_hash"}[fault]] = (
            "stale"
        )
    elif fault == "promise":
        reply["probes"][0]["requirement"] = "Другое условие начала"
    else:
        reply["probes"] = reply["probes"][:2]
    with pytest.raises(ContractError):
        materialize(reply, **options)


def test_checks_create_preserves_all_source_bytes_and_needs_review():
    game, reply, options = specimen()
    revised = materialize(reply, **options)
    assert not game["checks"]
    for key in ("files", "html", "artifact_hash", "file_hashes"):
        assert revised[key] == game[key]
    assert len(revised["checks"]) == 3 and revised["checks_review_required"]
    refused = deepcopy(reply)
    refused.update(status="unchanged", message="Нельзя наблюдать этот исход.", probes=[], observations=[])
    assert materialize(refused, **options)["status"] == "unchanged"


def test_experiment_only_changes_compact_create_wire_and_preserves_shared_contract():
    normal = {"operation": "create", "generation_profile": "compact"}
    split = {**normal, "generation_strategy": "lite_code_then_checks"}
    assert "probes" in response_schema(normal)["properties"]
    assert "probes" not in response_schema(split)["properties"]
    assert "Do not return probes" in build_messages(split)[0]["content"]
    with pytest.raises(ContractError):
        materialize(
            compact_response(),
            operation="create",
            generation_profile="compact",
            generation_strategy="lite_code_then_checks",
        )


def test_selected_module_context_is_bounded_without_losing_original_defect():
    import json

    request = {
        "operation": "repair",
        "base_revision": "saved",
        "files": {"game.js": "broken();", "styles.css": "secret unused styling"},
        "module_repair": {"files": {"game.js": "hash"}},
        "findings": [
            {"code": "runtime_or_network", "path": "game.js", "line": 1, "message": "primary fault"}
        ],
        "last_attempt_error": {"code": "patch_not_found", "message": "rejected patch"},
    }
    context = json.loads(build_messages(request)[1]["content"])
    assert context["files"] == {"game.js": "broken();"}
    assert context["module_interface"]["other_files"] == ["styles.css"]
    assert context["findings"][0]["message"] == "primary fault"
    assert context["last_attempt_error"]["code"] == "patch_not_found"


def test_selected_small_module_repair_rejects_patching_other_files():
    from generation.artifacts import apply_patches, sha256
    from generation.source_policy import module_policy

    files = {"game.js": "const a=1;", "styles.css": "body{color:red}"}
    policy = module_policy(files, [{"code": "javascript_syntax", "path": "game.js"}])
    patch = {
        "path": "styles.css",
        "file_hash": sha256(files["styles.css"]),
        "old_text": "red",
        "new_text": "blue",
    }
    with pytest.raises(ContractError, match="одним выбранным модулем"):
        apply_patches(files, [patch], module_repair=policy)
    patch = {"path": "game.js", "file_hash": sha256(files["game.js"]), "old_text": "1", "new_text": "2"}
    fixed = apply_patches(files, [patch], module_repair=policy)
    assert fixed["styles.css"] == files["styles.css"] and fixed["game.js"] == "const a=2;"
