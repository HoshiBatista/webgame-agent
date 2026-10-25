from copy import deepcopy

import pytest

from generation.artifacts import apply_patches, bundle, materialize, sha256
from generation.errors import ContractError
from generation.prompts import build_messages
from generation.providers.fake import fixture_response
from generation.schema import validate_response


def candidate():
    return materialize(fixture_response(), operation="create")


def edited(base):
    response = fixture_response()
    response.update(
        operation="edit",
        base_revision="version-1",
        files=[],
        patches=[
            {
                "path": "styles.css",
                "file_hash": base["file_hashes"]["styles.css"],
                "old_text": "#eff4ff",
                "new_text": "#fff5e8",
            }
        ],
    )
    return response


def test_create_bundles_exact_local_files_offline_deterministically():
    base = candidate()
    assert "<script src=" not in base["html"]
    assert "<link " not in base["html"]
    assert "window.gameState" in base["html"]
    assert sha256(base["html"]) == base["artifact_hash"]
    assert base == candidate()


def test_color_edit_preserves_mechanics_and_source_bytes():
    base = candidate()
    result = materialize(
        edited(base), operation="edit", base_revision="version-1", files=base["files"], previous_checks=base["checks"]
    )
    assert result["files"]["game.js"] == base["files"]["game.js"]
    assert result["files"]["index.html"] == base["files"]["index.html"]
    assert result["file_hashes"]["styles.css"] != base["file_hashes"]["styles.css"]
    assert "#fff5e8" in result["html"]
    assert base["files"]["styles.css"].count("#eff4ff") == 1


def test_cosmetic_patch_omits_checks_and_inherits_the_full_suite():
    base = candidate()
    response = edited(base)
    response["checks"] = []
    validate_response(response)
    result = materialize(
        response, operation="edit", base_revision="version-1", files=base["files"], previous_checks=base["checks"]
    )
    assert result["checks"] == base["checks"]
    assert result["files"]["game.js"] == base["files"]["game.js"]


@pytest.mark.parametrize("form", ["empty", "identical_patch", "reordered_checks", "metadata_only"])
def test_ok_edit_cannot_claim_a_change_when_final_sources_and_checks_are_identical(form):
    base = candidate()
    response = edited(base)
    response.update(patches=[], checks=[], message="Запрошенные изменения успешно выполнены.")
    if form == "identical_patch":
        response["patches"] = [
            {
                "path": "styles.css",
                "file_hash": base["file_hashes"]["styles.css"],
                "old_text": "#eff4ff",
                "new_text": "#eff4ff",
            }
        ]
    elif form == "reordered_checks":
        response["checks"] = list(reversed(deepcopy(base["checks"])))
    elif form == "metadata_only":
        response["title"] = "Другое название"
        response["design"]["summary"] = "Карточка изменена, но игра прежняя"
    with pytest.raises(ContractError) as error:
        materialize(response, operation="edit", base_revision="version-1", files=base["files"], previous_checks=base["checks"])
    assert error.value.code == "no_changes"
    assert base == candidate()


def test_check_only_change_requires_application_review_without_claiming_a_game_fix():
    base = candidate()
    response = edited(base)
    correction = deepcopy(base["checks"][1])
    correction["steps"] = [{"action": "tap_fraction", "selector": "#arena", "x": 0.5, "y": 0.5}]
    response.update(patches=[], checks=[correction])
    with pytest.raises(ContractError) as caught:
        materialize(response, operation="edit", base_revision="version-1", files=base["files"],
                    previous_checks=base["checks"])
    assert caught.value.code == "test_only_change"



def test_explicit_unchanged_returns_neutral_receipt_for_the_exact_existing_base():
    base = candidate()
    response = edited(base)
    response.update(
        status="unchanged",
        files=[],
        patches=[],
        checks=[],
        message="Запрошенное поведение уже есть в выбранной версии.",
    )
    validate_response(response)
    result = materialize(
        response, operation="edit", base_revision="version-1", files=base["files"], previous_checks=base["checks"]
    )
    assert result == {"status": "unchanged", "message": response["message"]}
    assert base == candidate()
    with pytest.raises(ContractError) as error:
        materialize(response, operation="edit", base_revision="version-2", files=base["files"], previous_checks=base["checks"])
    assert error.value.code == "stale_revision"
    with pytest.raises(ContractError) as error:
        materialize(response, operation="edit", base_revision="version-1")
    assert error.value.code == "invalid_unchanged"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda response: response.update(operation="create"),
        lambda response: response.update(base_revision=None),
        lambda response: response.update(message="  "),
        lambda response: response.update(files=[{"path": "new.js", "content": "let x=1;"}]),
        lambda response: response.update(
            patches=[{"path": "new.js", "file_hash": None, "old_text": "", "new_text": "let x=1;"}]
        ),
        lambda response: response.update(checks=[fixture_response()["checks"][0]]),
    ],
)
def test_unchanged_status_cannot_smuggle_mutations_or_skip_its_explanation(mutation):
    response = edited(candidate())
    response.update(status="unchanged", patches=[], checks=[], message="Поведение уже реализовано.")
    mutation(response)
    with pytest.raises(ContractError) as error:
        validate_response(response)
    assert error.value.code == "invalid_unchanged"


def test_partial_check_correction_keeps_all_omitted_mechanics():
    base = candidate()
    response = edited(base)
    correction = deepcopy(base["checks"][1])
    correction["steps"] = [{"action": "tap_fraction", "selector": "#arena", "x": 0.5, "y": 0.5}]
    response["checks"] = [correction]
    validate_response(response)
    result = materialize(
        response, operation="edit", base_revision="version-1", files=base["files"], previous_checks=base["checks"]
    )
    actual = {check["id"]: check for check in result["checks"]}
    assert len(actual) == len(base["checks"])
    assert actual[correction["id"]] == correction
    for original in base["checks"]:
        if original["id"] != correction["id"]:
            assert actual[original["id"]] == original


def test_inherited_suite_is_validated_after_merge_not_just_new_checks():
    base = candidate()
    response = edited(base)
    response["checks"] = []
    with pytest.raises(ContractError) as error:
        materialize(response, operation="edit", base_revision="version-1", files=base["files"], previous_checks=[])
    assert error.value.code == "missing_effects"
    old = base["checks"] + [
        {**deepcopy(base["checks"][1]), "id": f"regression-{index}", "category": "regression"}
        for index in range(9)
    ]
    response["checks"] = [{**deepcopy(base["checks"][1]), "id": "new-effect", "category": "regression"}]
    with pytest.raises(ContractError) as error:
        materialize(response, operation="edit", base_revision="version-1", files=base["files"], previous_checks=old)
    assert error.value.code == "too_many_checks"


@pytest.mark.parametrize("coordinate", [-0.01, 1.01, None, True])
def test_fractional_coordinates_reject_invalid_ranges_and_types(coordinate):
    response = fixture_response()
    response["checks"][1]["steps"] = [
        {"action": "tap_fraction", "selector": "#arena", "x": coordinate, "y": 0.5}
    ]
    with pytest.raises(ContractError):
        validate_response(response)


def test_create_cannot_omit_the_required_suite():
    response = fixture_response()
    response["checks"] = []
    with pytest.raises(ContractError) as error:
        validate_response(response)
    assert error.value.code == "missing_effects"


def test_multiple_patches_use_original_offsets_not_previous_replacements():
    source = {"game.js": "let one = 1;\nlet two = 2;\nlet three = 3;"}
    patches = [
        {"path": "game.js", "file_hash": sha256(source["game.js"]), "old_text": a, "new_text": b}
        for a, b in [("one = 1", "two = 2"), ("two = 2", "second = 4")]
    ]
    assert apply_patches(source, patches)["game.js"] == "let two = 2;\nlet second = 4;\nlet three = 3;"


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda r: r.update(base_revision="wrong"), "stale_revision"),
        (lambda r: r["patches"][0].update(file_hash="wrong"), "stale_file"),
        (lambda r: r["patches"][0].update(old_text="not present"), "ambiguous_patch"),
        (lambda r: r["patches"][0].update(path="../secret.js"), "unsafe_path"),
        (lambda r: r["patches"].append(deepcopy(r["patches"][0])), "overlapping_patch"),
    ],
)
def test_bad_patch_is_atomic(mutation, code):
    base = candidate()
    saved = deepcopy(base["files"])
    response = edited(base)
    mutation(response)
    with pytest.raises(ContractError) as error:
        materialize(response, operation="edit", base_revision="version-1", files=base["files"])
    assert error.value.code == code
    assert base["files"] == saved


def test_full_js_rewrite_rejected_even_when_hash_matches():
    base = candidate()
    response = edited(base)
    response["patches"] = [
        {
            "path": "game.js",
            "file_hash": base["file_hashes"]["game.js"],
            "old_text": base["files"]["game.js"],
            "new_text": "alert(1)",
        }
    ]
    with pytest.raises(ContractError, match="локальная правка"):
        materialize(response, operation="edit", base_revision="version-1", files=base["files"])


def test_new_local_file_added_without_rewriting_existing_files():
    source = {"game.js": "const value=1;\nconst x=2;"}
    result = apply_patches(
        source, [{"path": "levels.json", "file_hash": None, "old_text": "", "new_text": "[1,2]"}]
    )
    assert result["game.js"] == source["game.js"]
    assert result["levels.json"] == "[1,2]"


def test_repair_inherits_checks_and_cannot_silently_remove_requirements():
    base = candidate()
    old = deepcopy(base["checks"][1])
    old.update(id="blocked-move", category="regression", requirement="Неверный ход не изменяет состояние")
    base["checks"].append(old)
    response = edited(base)
    response["operation"] = "repair"
    result = materialize(
        response, operation="repair", base_revision="version-1", files=base["files"], previous_checks=base["checks"]
    )
    assert result["checks"][-1] == old
    response["checks"][1]["requirement"] = "Просто видна любая кнопка"
    with pytest.raises(ContractError) as error:
        materialize(response, operation="repair", base_revision="version-1", files=base["files"], previous_checks=base["checks"])
    assert error.value.code == "repair_checks_locked"


def test_intentional_edit_updates_effect_then_repair_keeps_that_new_requirement():
    base = candidate()
    response = edited(base)
    changed = deepcopy(base["checks"][2])
    changed["requirement"] = "Новый заданный пользователем результат после пяти попаданий"
    changed["steps"] = changed["steps"] + changed["steps"][:2]
    response["checks"] = [changed]
    result = materialize(
        response,
        operation="edit",
        base_revision="version-1",
        files=base["files"],
        previous_checks=base["checks"],
    )
    actual = {check["id"]: check for check in result["checks"]}
    assert actual[changed["id"]] == changed
    assert actual[base["checks"][1]["id"]] == base["checks"][1]
    repair = edited(result)
    repair.update(operation="repair", patches=[], checks=[deepcopy(changed)])
    repair["checks"][0]["requirement"] = base["checks"][2]["requirement"]
    with pytest.raises(ContractError) as error:
        materialize(
            repair,
            operation="repair",
            base_revision="version-1",
            files=result["files"],
            previous_checks=result["checks"],
        )
    assert error.value.code == "repair_checks_locked"


def test_model_cannot_claim_edit_permissions_during_a_trusted_repair():
    base = candidate()
    response = edited(base)
    response["checks"][2]["requirement"] = "Любой клик достаточен"
    with pytest.raises(ContractError) as error:
        materialize(
            response,
            operation="repair",
            base_revision="version-1",
            files=base["files"],
            previous_checks=base["checks"],
        )
    assert error.value.code == "operation_mismatch"


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["checks"][1]["observation"].update(path="gameState.testPassed"),
        lambda r: r["checks"][1].update(steps=[]),
        lambda r: r["checks"][1]["steps"].extend([{"action": "wait", "ms": 6000}] * 2),
    ],
)
def test_check_contract_rejects_self_report_missing_input_and_unbounded_wait(change):
    response = fixture_response()
    change(response)
    with pytest.raises(ContractError):
        validate_response(response)


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("desktop_only", "missing_mobile_start"),
        ("desktop_control", "missing_mobile_control"),
        ("mouse_only", "missing_mobile_control"),
        ("keyboard_only", "missing_mobile_control"),
        ("keyboard_with_touch", "missing_mobile_control"),
    ],
)
def test_full_suite_requires_mobile_start_and_touch_gameplay(mutation, code):
    response = fixture_response()
    control = response["checks"][1]
    if mutation == "desktop_only":
        for check in response["checks"]:
            check["viewport"] = "desktop"
    elif mutation == "desktop_control":
        control["viewport"] = "desktop"
    elif mutation == "mouse_only":
        control["steps"][0]["action"] = "click"
    elif mutation == "keyboard_only":
        control["steps"] = [{"action": "press", "key": "Space"}]
    else:
        control["steps"].append({"action": "press", "key": "Space"})
    with pytest.raises(ContractError) as error:
        validate_response(response)
    assert error.value.code == code


def test_edit_cannot_remove_inherited_mobile_coverage():
    base = candidate()
    response = edited(base)
    response["checks"] = [deepcopy(base["checks"][1])]
    response["checks"][0]["viewport"] = "desktop"
    # Partial model output is valid, but its merged suite is not playable on mobile.
    validate_response(response)
    with pytest.raises(ContractError) as error:
        materialize(
            response,
            operation="edit",
            base_revision="version-1",
            files=base["files"],
            previous_checks=base["checks"],
        )
    assert error.value.code == "missing_mobile_control"


def test_desktop_keyboard_check_can_supplement_mobile_touch_gameplay():
    response = fixture_response()
    keyboard = deepcopy(response["checks"][1])
    keyboard.update(id="keyboard", viewport="desktop", steps=[{"action": "press", "key": "Space"}])
    response["checks"].append(keyboard)
    validate_response(response)


def test_restart_check_requires_real_input_and_survives_cosmetic_edits():
    base = candidate()
    restart = deepcopy(base["checks"][1])
    restart.update(id="replay", category="restart", requirement="После повтора доступен новый раунд")
    base["checks"].append(restart)
    response = edited(base)
    response["checks"] = []
    result = materialize(
        response,
        operation="edit",
        base_revision="version-1",
        files=base["files"],
        previous_checks=base["checks"],
    )
    assert restart in result["checks"]
    response["checks"] = [{**restart, "steps": []}]
    with pytest.raises(ContractError) as error:
        validate_response(response)
    assert error.value.code == "no_real_input"


def test_compact_context_includes_current_hashes_and_preferences_not_past_chat():
    messages = build_messages(
        {
            "prompt": "Перекрась",
            "files": {"game.js": "const x=1"},
            "preferences": {"clear_controls": True},
            "history": ["SECRET_OLD_PROMPT"],
        }
    )
    assert "SECRET_OLD_PROMPT" not in str(messages)
    assert sha256("const x=1") in messages[1]["content"]
    assert "clear_controls" in messages[1]["content"]


def test_pointer_contract_explains_css_pixels_and_automatic_button_center():
    from generation.prompts import SYSTEM_PROMPT
    from generation.schema import POINT
    from validation.contracts import VIEWPORTS

    assert "never normalized 0..1" in SYSTEM_PROMPT
    assert "x=null,y=null" in SYSTEM_PROMPT
    for name in ("x", "y"):
        assert "CSS pixels" in POINT["properties"][name]["description"]
        assert "Never normalized 0..1" in POINT["properties"][name]["description"]
    for viewport in VIEWPORTS.values():
        assert f"{viewport['width']}x{viewport['height']}" in SYSTEM_PROMPT


def test_bundler_preserves_json_data_and_defer_semantics():
    files = {
        "index.html": '<html><head><script src=game.js defer></script></head><body><canvas></canvas><script type="application/json" id="levels">[1,2]</script></body></html>',
        "game.js": 'document.querySelector("canvas").width=320;',
    }
    result = bundle(files)
    assert '<script type="application/json" id="levels">[1,2]</script>' in result
    assert result.index("width=320") > result.index("<canvas>")


def test_state_contract_describes_data_properties_without_prescribing_game_state():
    from generation.prompts import SYSTEM_PROMPT
    from generation.schema import OBSERVATION

    description = OBSERVATION["anyOf"][2]["properties"]["path"]["description"]
    assert "own data properties" in description
    assert "No getters" in description
    assert "DOM text/attributes" in description
    assert "Top-level let/const variables are not window properties" in SYSTEM_PROMPT
    assert "No mandatory global name or state schema" in SYSTEM_PROMPT


def test_dynamic_canvas_is_allowed_for_runtime_checker():
    assert "createElement" in bundle(
        {
            "index.html": '<html><body><script>document.body.appendChild(document.createElement("canvas"));</script></body></html>'
        }
    )


@pytest.mark.parametrize(
    "html",
    [
        '<html><body><canvas/><script src="https://evil.test/x.js"></script></body></html>',
        '<html><body><canvas/><iframe src="x"></iframe></body></html>',
        '<html><head><link rel="stylesheet" href="missing.css"></head><canvas></canvas></html>',
    ],
)
def test_missing_and_external_resources_rejected(html):
    with pytest.raises(ContractError):
        bundle({"index.html": html})


def test_separate_json_levels_embed_offline_and_small_patch_preserves_js():
    files = {
        "index.html": '<html><body><canvas></canvas><script type="application/json" src="levels.json" id="levels"></script><script src="game.js"></script></body></html>',
        "game.js": 'const levels = JSON.parse(document.getElementById("levels").textContent);\nwindow.levelCount=levels.length;',
        "levels.json": '[{"goal":2}]',
    }
    patched = apply_patches(
        files,
        [
            {
                "path": "levels.json",
                "file_hash": sha256(files["levels.json"]),
                "old_text": '[{"goal":2}]',
                "new_text": '[{"goal":2},{"goal":3},{"goal":4}]',
            }
        ],
    )
    result = bundle(patched)
    assert 'src="levels.json"' not in result
    assert '<script type="application/json" id="levels">[{"goal":2},{"goal":3},{"goal":4}]</script>' in result
    assert patched["game.js"] == files["game.js"]
