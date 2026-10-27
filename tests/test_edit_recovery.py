from copy import deepcopy
from unittest.mock import patch

import pytest

from generation.artifacts import apply_patches, materialize, sha256
from generation.check_repair import IDENTITY
from generation.check_repair import permission as checks_permission
from generation.errors import ContractError
from generation.patch_repair import permission
from generation.prompts import build_messages, codex_prompt, schema_prompt
from generation.providers.fake import fixture_response
from generation.schema import validate_checks
from generation.service import generate
from tests.test_compact_generation import artifact as compact_artifact
from tests.test_compact_generation import compact_response


def edit_case(profile="full"):
    if profile == "compact":
        base = compact_artifact()
        response = {"status": "ok", "message": "Новый цвет и скорость", "observations": [], "probes": [],
                    "edits": [{"old_text": "'#ffd84d'", "new_text": "'#77ff99'"},
                              {"old_text": "dt * 100", "new_text": "dt*120"}]}
    else:
        base = materialize(fixture_response(), operation="create")
        response = fixture_response()
        response.update(operation="edit", base_revision="base", files=[], checks=[], patches=[
            {"path": "styles.css", "file_hash": sha256(base["files"]["styles.css"]),
             "old_text": "#eff4ff", "new_text": "#fff4ee"},
            {"path": "game.js", "file_hash": sha256(base["files"]["game.js"]),
             "old_text": 'ctx.fillStyle = "#5879e8"', "new_text": 'ctx.fillStyle="#ee88bb"'},
        ])
    return base, response


def corrected(policy, base):
    patches = []
    for i in policy["indices"]:
        path = policy["paths"][str(i)]
        patches.append({"index": i, "patches": [{"path": path, "file_hash": sha256(base["files"][path]),
            "old_text": "dt*100" if policy["profile"] == "compact" else 'ctx.fillStyle="#5879e8"',
            "new_text": "dt*120" if policy["profile"] == "compact" else 'ctx.fillStyle="#ee88bb"'}]})
    return {"status": "ok", "operation": "edit", "base_revision": policy["base_revision"],
            "response_hash": policy["response_hash"], "message": "Изменены цвет и движение.", "corrections": patches}


def apply(base, response, profile="full", policy=None):
    return materialize(response, operation="edit", base_revision="base", files=base["files"],
                       previous_checks=base["checks"], generation_profile=profile,
                       compact_manifest=base.get("compact_manifest"), patch_repair=policy)


@pytest.mark.parametrize("profile", ["full", "compact"])
def test_focused_patch_repair_preserves_good_changes_and_original_source(profile):
    base, response = edit_case(profile)
    original = deepcopy(base)
    with pytest.raises(ContractError, match="ровно один раз"):
        apply(base, response, profile)
    policy = permission(response, files=base["files"], base_revision="base", profile=profile)
    assert policy["indices"] == [1]
    reply = corrected(policy, base)
    game = apply(base, reply, profile, policy)
    assert base == original
    assert game["checks"] == base["checks"]
    if profile == "full":
        assert "#fff4ee" in game["files"]["styles.css"] and "#ee88bb" in game["files"]["game.js"]
        assert game["design"] == response["design"]
    else:
        assert "#77ff99" in game["files"]["game.js"] and "dt*120" in game["files"]["game.js"]
        assert all(game["files"][p] == c for p, c in base["files"].items() if p != "game.js")


@pytest.mark.parametrize("mutation", ["good_slot", "missing", "duplicate", "path", "hash", "base", "receipt", "checks", "policy", "source"])
def test_focused_correction_rejects_scope_and_binding_changes(mutation):
    base, response = edit_case()
    policy = permission(response, files=base["files"], base_revision="base")
    reply = corrected(policy, base)
    if mutation == "good_slot":
        reply["corrections"][0]["index"] = 0
    elif mutation == "missing":
        reply["corrections"] = []
    elif mutation == "duplicate":
        reply["corrections"] *= 2
    elif mutation == "path":
        reply["corrections"][0]["patches"][0]["path"] = "styles.css"
    elif mutation == "hash":
        reply["corrections"][0]["patches"][0]["file_hash"] = "0" * 64
    elif mutation == "base":
        reply["base_revision"] = "another"
    elif mutation == "receipt":
        reply["response_hash"] = "0" * 64
    elif mutation == "checks":
        reply["checks"] = []
    elif mutation == "policy":
        policy["indices"] = [0, 1]
    else:
        base["files"]["styles.css"] += "body{color:red}"
    with pytest.raises(ContractError):
        apply(base, reply, policy=policy)


def test_all_overlapping_fragments_are_reported_and_recombined_atomically():
    base, response = edit_case()
    good = deepcopy(response["patches"][0])
    p = {"path": "game.js", "file_hash": sha256(base["files"]["game.js"]),
         "old_text": 'ctx.fillStyle="#5879e8"', "new_text": 'ctx.fillStyle="#ee88bb"'}
    response["patches"] = [good, p, {**p, "old_text": 'fillStyle="#5879e8"', "new_text": 'fillStyle="red"'}]
    policy = permission(response, files=base["files"], base_revision="base")
    assert policy["indices"] == [1, 2]
    reply = corrected(policy, base)
    reply["corrections"][1]["patches"] = []  # Consolidate the conflicting intent into slot 1.
    result = apply(base, reply, policy=policy)
    assert result["files"] == apply_patches(base["files"], [good, p])
    assert response["patches"][2]["new_text"] == 'fillStyle="red"'


@pytest.mark.parametrize("profile", ["full", "compact"])
def test_provider_validation_and_codex_prompts_use_the_narrow_correction_contract(profile):
    base, response = edit_case(profile)
    policy = permission(response, files=base["files"], base_revision="base", profile=profile)
    request = {"provider": "fake", "operation": "edit", "files": base["files"],
               "generation_profile": profile, "patch_repair": policy}
    reply = corrected(policy, base)
    with patch("generation.providers.fake.generate", return_value={"response": reply, "usage": {"input_tokens": 2}}):
        result = generate(request, on_event=lambda *a: None, is_cancelled=lambda: False)
    assert result["response"] == result["raw_response"] == reply
    assert "corrections" in schema_prompt(request)
    prompt = codex_prompt(request)
    assert "rejected_patches" in prompt
    assert '"checks":' not in build_messages(request)[1]["content"]
    if profile == "full":
        assert base["files"]["styles.css"] not in prompt


@pytest.mark.parametrize("defect", ["no_real_input", "duplicate", "inherited_duplicate"])
def test_valid_edit_code_survives_semantic_check_errors_and_receipt_keeps_usage(defect):
    base, response = edit_case()
    response["patches"] = response["patches"][:1]
    check = deepcopy(base["checks"][1])
    if defect == "no_real_input":
        check["steps"] = [{"action": "checkpoint"}, {"action": "wait_for", "ms": 300}]
        check["expect"] = {"operator": "changed", "value": None}
        response["checks"] = [check]
    elif defect == "duplicate":
        response["checks"] = [check, deepcopy(check)]
    else:
        base["checks"].append(check)
    with patch("generation.providers.fake.generate", return_value={"response": response, "usage": {"input_tokens": 7}}):
        receipt = generate({"provider": "fake", "operation": "edit"}, on_event=lambda *a: None, is_cancelled=lambda: False)
    game = apply(base, receipt["response"])
    assert receipt["usage"]["input_tokens"] == 7 and receipt["raw_response"] == response
    assert "#fff4ee" in game["files"]["styles.css"]
    with pytest.raises(ContractError):
        validate_checks(game["checks"])
    assert len(game["checks"]) == (3 if defect == "no_real_input" else 4)


def test_duplicate_promises_have_auditable_identity_mapping_without_dropping_distinct_requirements():
    checks = deepcopy(fixture_response()["checks"])
    repeated = {**deepcopy(checks[1]), "steps": checks[1]["steps"] * 2}
    conflicting = {**deepcopy(checks[1]), "requirement": "Отдельное обещание для второго касания"}
    checks += [repeated, conflicting, {**deepcopy(checks[1]), "id": "tap_check2"}]
    before = deepcopy(checks)
    policy = checks_permission("artifact", checks, {})
    assert len(policy["requirements"]) == 5
    assert [r["requirement_id"] for r in policy["identity_repairs"]] == ["start", "tap", "outcome", "tap", "tap_check3", "tap_check2"]
    assert checks == before
    assert {tuple(r[k] for k in IDENTITY[1:]) for r in policy["requirements"]} == {tuple(c[k] for k in IDENTITY[1:]) for c in checks}


def test_compact_duplicate_probes_are_retained_for_separate_repair():
    base, response = edit_case("compact")
    response["edits"] = response["edits"][:1]
    probe = compact_response()["probes"][1]
    response["probes"] = [probe, deepcopy(probe)]
    result = apply(base, response, "compact")
    assert len(result["checks"]) == 4 and result["checks_review_required"]
    assert result["files"]["game.js"] != base["files"]["game.js"]
    assert len(checks_permission(result["artifact_hash"], result["checks"], result["design"])["requirements"]) == 3


def test_duplicate_alias_does_not_shadow_a_frozen_promise():
    checks = deepcopy(fixture_response()["checks"])
    checks.append({**deepcopy(checks[1]), "requirement": "Другое исходное обещание при касании"})
    frozen = {"requirements": [{**{k: checks[1][k] for k in IDENTITY}, "id": "tap_check2"}]}
    policy = checks_permission("artifact", checks, {}, frozen)
    assert {r["id"] for r in policy["requirements"]} == {"start", "tap", "outcome", "tap_check2", "tap_check3"}
    assert next(r for r in policy["requirements"] if r["id"] == "tap_check3")["requirement"] == checks[-1]["requirement"]


@pytest.mark.browser
def test_compact_corrected_edit_passes_real_browser_without_changing_runtime():
    from tests.test_compact_generation import verify

    base, response = edit_case("compact")
    policy = permission(response, files=base["files"], base_revision="base", profile="compact")
    game = apply(base, corrected(policy, base), "compact", policy)
    result = verify(game)
    assert result["status"] == "passed", result["findings"]
    assert all(result["gates"].values())
