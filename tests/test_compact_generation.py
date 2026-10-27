from copy import deepcopy

import pytest

from generation.artifacts import materialize, sha256
from generation.compact import compile_checks, validate_wire, validation_contract, wire_schema
from generation.errors import ContractError
from validation.service import validate

SOURCE = """GameForge.register(api => {
  const state = {phase:'ready', hits:0, x:api.width/2, held:false};
  return {
    state,
    input(e) {
      if(e.type==='blur') state.held=false;
      if(e.type==='key' && e.key==='ArrowRight') state.held=e.phase==='down';
      if(e.phase!=='down') return;
      if(e.action==='start') {state.phase='play';state.hits=0;}
      if(e.action==='reset') {state.phase='ready';state.hits=0;}
      if(state.phase==='play' && e.type==='pointer' && Math.hypot(e.x-state.x,e.y-api.height/2)<40) {
        state.hits++; if(state.hits===3) state.phase='won';
      }
    },
    update(dt) {if(state.held) state.x=Math.min(api.width-40,state.x+dt*100);},
    render(ctx) {
      ctx.fillStyle='#17233a';ctx.fillRect(0,0,api.width,api.height);
      ctx.fillStyle='#ffd84d';ctx.beginPath();ctx.arc(state.x,api.height/2,40,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='white';ctx.font='20px sans-serif';ctx.fillText(state.phase+' '+state.hits,12,30);
    }
  };
});"""


def compact_response(source=SOURCE):
    return {
        "status": "ok",
        "message": "Тестовая механика, без модели.",
        "title": "Проверка утилит",
        "summary": "Три реальных попадания",
        "outcome": "Три попадания завершают партию",
        "world": {"width": 360, "height": 420},
        "controls": [
            {"id": "start", "label": "Играть", "key": "Enter"},
            {"id": "reset", "label": "Заново", "key": None},
        ],
        "observations": [
            {"id": "phase", "path": "phase", "type": "string"},
            {"id": "hits", "path": "hits", "type": "number"},
            {"id": "x", "path": "x", "type": "number"},
        ],
        "probes": [
            {
                "id": "begin",
                "category": "start",
                "requirement": "Настоящая кнопка начинает игру",
                "viewport": "mobile",
                "steps": [{"action": "control", "id": "start"}],
                "observation": "phase",
                "operator": "eq",
                "value": "play",
            },
            {
                "id": "hit",
                "category": "control",
                "requirement": "Касание центра увеличивает попадания",
                "viewport": "mobile",
                "steps": [{"action": "control", "id": "start"}, {"action": "canvas", "x": 0.5, "y": 0.5}],
                "observation": "hits",
                "operator": "eq",
                "value": 1,
            },
            {
                "id": "win",
                "category": "outcome",
                "requirement": "Три попадания завершают партию",
                "viewport": "desktop",
                "steps": [{"action": "control", "id": "start"}]
                + [{"action": "canvas", "x": 0.5, "y": 0.5}] * 3,
                "observation": "phase",
                "operator": "eq",
                "value": "won",
            },
        ],
        "source": source,
    }


def artifact(response=None, source_format="string"):
    return materialize(
        response or compact_response(),
        operation="create",
        generation_profile="compact",
        source_format=source_format,
    )


def verify(game, checks=None):
    return validate(
        game["html"],
        game["checks"] if checks is None else checks,
        artifact_hash=game["artifact_hash"],
        contract=validation_contract(game["compact_manifest"], game["files"]),
    )


def test_string_and_lines_build_identical_offline_artifacts_and_runtime_is_versioned():
    response = compact_response("/* 🍊 Привет */\n" + SOURCE + "\nconst escaped = 'line\\nend';\n")
    lines = deepcopy(response)
    lines["source_lines"] = lines.pop("source").split("\n")
    a, b = artifact(response), artifact(lines, "lines")
    assert a["files"] == b["files"] and a["artifact_hash"] == b["artifact_hash"]
    assert set(a["files"]) == {"index.html", "runtime.js", "runtime.css", "game.js", "gf-motion-v1.js"}
    assert a["runtime_version"] == 2 and a["generation_profile"] == "compact"
    assert "<script src=" not in a["html"] and "fetch(" not in a["html"]


def test_new_compact_game_schema_does_not_offer_an_unchanged_result_without_a_base():
    assert wire_schema({'operation': 'create'})['properties']['status']['enum'] == ['ok', 'scope_refusal']
    for operation in ['edit', 'repair', 'check_repair']:
        assert 'unchanged' in wire_schema({'operation': operation})['properties']['status']['enum']


def test_source_lines_wire_uses_portable_ascii_class_and_preserves_javascript_parentheses():
    from jsonschema import Draft202012Validator

    line = wire_schema({'source_format': 'lines'})['properties']['source_lines']['items']
    assert line['pattern'] == r'^[^\r\n]*$'
    assert Draft202012Validator(line).is_valid('GameForge.register(api => ({state:{}, input(e){}, render(ctx){}}));')


@pytest.mark.parametrize('bad_lines', [[], ['// only a comment'], 'not an array', ['x\r\ny'], ['x\u2028y'], ['x\n'], ['x\u2028'], ['x\u2029']])
def test_source_lines_does_not_guess_empty_or_invalid_input(bad_lines):
    response = compact_response()
    response.pop('source')
    response['source_lines'] = bad_lines
    with pytest.raises(ContractError):
        artifact(response, 'lines')


@pytest.mark.parametrize('source_format', ['string', 'lines'])
def test_unicode_source_byte_limit_is_not_replaced_by_json_character_limits(source_format):
    source = '/*\n' + '\n'.join(['я' * 1100] * 6) + '\n*/\n' + SOURCE
    response = compact_response(source)
    if source_format == 'lines':
        response['source_lines'] = response.pop('source').split('\n')
    with pytest.raises(ContractError) as error:
        artifact(response, source_format)
    assert error.value.code == 'module_too_large'


@pytest.mark.browser
def test_complete_json_with_truncated_source_lines_is_preserved_for_syntax_repair():
    response = compact_response()
    response['source_lines'] = response.pop('source').split('\n')[:-1]
    game = artifact(response, 'lines')
    assert game['files']['game.js'] == '\n'.join(response['source_lines'])
    report = verify(game)
    assert report['status'] == 'failed'
    assert 'javascript_syntax' in {f['code'] for f in report['findings']}


@pytest.mark.parametrize("kind", ["newline", "unknown_field", "duplicate_control", "too_big", "comment_only"])
def test_invalid_compact_sources_and_manifests_are_not_guessed(kind):
    response = compact_response()
    fmt = "string"
    if kind == "newline":
        response["source_lines"] = [response.pop("source")]
        fmt = "lines"
    elif kind == "unknown_field":
        response["host_shell"] = "forbidden"
    elif kind == "duplicate_control":
        response["controls"].append(response["controls"][0])
    elif kind == "too_big":
        response["source"] = "x" * 13000
    else:
        response["source"] = "// function game(){pretend();}"
    with pytest.raises(ContractError):
        artifact(response, fmt)


def test_compact_patch_changes_only_mechanic_bytes_and_cannot_replace_whole_game():
    game = artifact()
    response = {
        "status": "ok",
        "message": "Другой цвет",
        "observations": [],
        "probes": [],
        "edits": [{"old_text": "'#ffd84d'", "new_text": "'#77ff99'"}],
    }
    edited = materialize(
        response,
        operation="edit",
        files=game["files"],
        previous_checks=game["checks"],
        generation_profile="compact",
        compact_manifest=game["compact_manifest"],
    )
    assert edited["files"]["game.js"] != game["files"]["game.js"]
    assert edited["checks"] == game["checks"]
    assert all(edited["files"][p] == value for p, value in game["files"].items() if p != "game.js")
    response["edits"] = [{"old_text": SOURCE, "new_text": SOURCE + "\n/* changed */"}]
    with pytest.raises(ContractError, match="локальная правка"):
        materialize(
            response,
            operation="edit",
            files=game["files"],
            previous_checks=game["checks"],
            generation_profile="compact",
            compact_manifest=game["compact_manifest"],
        )


def test_compact_edit_updates_observation_without_replacing_inherited_probes():
    game = artifact()
    response = {'status': 'ok', 'message': 'Новый счётчик', 'probes': [],
                'observations': [{'id': 'hits', 'path': 'count', 'type': 'number'}],
                'edits': [{'old_text': 'hits:0', 'new_text': 'hits:0, count:0'}]}
    updated = materialize(response, operation='edit', files=game['files'], previous_checks=game['checks'],
                          generation_profile='compact', compact_manifest=game['compact_manifest'])
    assert updated['compact_manifest']['probes'] == game['compact_manifest']['probes']
    assert updated['checks'][1]['observation']['path'] == 'gfState.count'
    assert updated['checks_review_required'] is True


@pytest.mark.parametrize('part,limit', [('observations', 16), ('probes', 12)])
def test_compact_edit_cannot_accumulate_an_unrepairable_oversized_manifest(part, limit):
    response = compact_response()
    template = response[part][0]
    response[part].extend({**template, 'id': 'existing' + str(i)} for i in range(limit - len(response[part])))
    game = artifact(response)
    change = {'status': 'ok', 'message': 'Один новый сценарий', 'probes': [], 'observations': [],
              'edits': [{'old_text': "'#ffd84d'", 'new_text': "'#77ff99'"}]}
    change[part] = [{**template, 'id': 'new_entry'}]
    with pytest.raises(ContractError, match='(наблюдений|сценариев)'):
        materialize(change, operation='edit', files=game['files'], previous_checks=game['checks'],
                    generation_profile='compact', compact_manifest=game['compact_manifest'])


def test_compact_wire_has_one_application_selected_repair_format():
    from generation.schema import response_schema

    request = {"operation": "repair", "generation_profile": "compact"}
    assert "edits" in response_schema(request)["properties"]
    request["module_repair"] = {"files": {"game.js": "a" * 64}}
    assert (
        "source" in response_schema(request)["properties"]
        and "edits" not in response_schema(request)["properties"]
    )
    validate_wire(
        {"status": "unchanged", "message": "Нельзя исправить без изменения правил", "source": ""}, request
    )


@pytest.mark.browser
def test_compact_game_registers_and_real_input_works_on_both_viewports():
    report = verify(artifact())
    assert report["status"] == "passed", report["findings"]
    assert report["gates"]["startup"] and report["gates"]["controls"]
    assert len(report["facts"]) == 3


@pytest.mark.browser
@pytest.mark.parametrize(
    "defect", ["no_registration", "commented_tail", "ignored_input", "wrong_observation", "occluded_control"]
)
def test_known_bad_modules_do_not_receive_automatic_success(defect):
    response = compact_response()
    if defect == "no_registration":
        response["source"] = 'const state={phase:"ready"};'
    elif defect == "commented_tail":
        response["source"] = "const state={}; // " + SOURCE.replace("\n", " ")
    elif defect == "ignored_input":
        response["source"] = SOURCE.replace("state.hits++;", "/* ignored real input */")
    elif defect == "wrong_observation":
        response["observations"][0]["path"] = "nonexistentDirection"
    else:
        response["source"] = (
            SOURCE
            + '\nconst cover=document.createElement("div");cover.style="position:fixed;inset:0;z-index:99";document.body.appendChild(cover);'
        )
    report = verify(artifact(response))
    assert report["status"] != "passed"
    if defect in {"no_registration", "commented_tail"}:
        assert "module_not_registered" in {f["code"] for f in report["findings"]}
        assert not report["gates"]["startup"]
    if defect == "occluded_control":
        assert "control_obstructed" in {f["code"] for f in report["findings"]}


def test_unknown_observation_reference_remains_a_saved_candidate_with_unverifiable_checks():
    response = compact_response()
    response["probes"][1]["observation"] = "notDeclared"
    game = artifact(response)
    assert game["files"]["game.js"] == SOURCE
    assert "__unregistered" in compile_checks(game["compact_manifest"])[1]["observation"]["path"]
    assert sha256(game["html"]) == game["artifact_hash"]


@pytest.mark.browser
@pytest.mark.parametrize("seed", [1, 1729])
def test_seeded_clock_executes_motion_then_release_and_blur_stop_it(seed):
    game = artifact()
    manifest = deepcopy(game["compact_manifest"])
    begin = [{"action": "control", "id": "start"}]
    motion = [{"action": "key_down", "key": "ArrowRight"}, {"action": "wait", "ms": 300}]
    manifest["probes"].append(
        {
            "id": "motion",
            "category": "regression",
            "requirement": "Удержание реально перемещает объект",
            "viewport": "mobile",
            "steps": begin + [{"action": "checkpoint"}] + motion,
            "observation": "x",
            "operator": "increased",
            "value": None,
        }
    )
    for kind in ["key_up", "blur"]:
        release = {"action": kind, "key": "ArrowRight"} if kind == "key_up" else {"action": "blur"}
        manifest["probes"].append(
            {
                "id": "release_" + kind,
                "category": "regression",
                "requirement": "Отпускание и потеря фокуса прекращают движение",
                "viewport": "mobile",
                "steps": begin + motion + [release, {"action": "checkpoint"}, {"action": "wait", "ms": 300}],
                "observation": "x",
                "operator": "unchanged",
                "value": None,
            }
        )
    report = validate(
        game["html"],
        compile_checks(manifest),
        artifact_hash=game["artifact_hash"],
        contract=validation_contract(manifest, game["files"]),
        test_profile={"seed": seed, "clock": True},
    )
    assert report["status"] == "passed", report["findings"]
    assert ":test-" in report["environment"]


@pytest.mark.browser
def test_resize_keeps_game_progress_and_pointer_mapping():
    game = artifact()
    checks = deepcopy(game["checks"])
    checks[2]["steps"].insert(2, {"action": "resize", "viewport": "mobile"})
    checks[2]["steps"].insert(4, {"action": "resize", "viewport": "desktop"})
    report = verify(game, checks)
    assert report["status"] == "passed", report["findings"]


@pytest.mark.browser
def test_control_assertion_that_also_passes_without_its_input_is_not_accepted():
    response = compact_response(SOURCE.replace("hits:0", "hits:0, decorative:1"))
    response["observations"].append({"id": "decorative", "path": "decorative", "type": "number"})
    response["probes"][1].update(observation="decorative", value=1)
    report = verify(artifact(response))
    assert report["status"] == "unverified", report
    assert "effect_not_causal" in {f["code"] for f in report["findings"]}
