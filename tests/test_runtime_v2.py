"""Instrumented fixture mechanics run only inside the isolated validator browser."""

from copy import deepcopy

import pytest

from generation.compact import validation_contract
from tests.test_compact_generation import SOURCE, artifact, compact_response, verify
from validation.service import validate


@pytest.mark.browser
def test_render_only_module_redraws_delayed_input_effect_without_its_own_loop():
    source = """const output = document.createElement('output');
output.id='painted';output.style='position:fixed;top:0;pointer-events:none';document.body.appendChild(output);
GameForge.register(api=>{
  const state={phase:'ready',hits:0};
  return {state,input(e){
    if(e.phase!=='down') return;
    if(e.action==='start'){state.phase='play';state.hits=0;}
    if(e.type==='pointer' && state.phase==='play') setTimeout(()=>{state.hits++;if(state.hits===3)state.phase='won';},50);
  },render(ctx){
    ctx.fillStyle='#243857';ctx.fillRect(0,0,api.width,api.height);
    ctx.fillStyle='gold';ctx.fillRect(50,50,120,120);output.textContent=String(state.hits);
  }};
});"""
    game = artifact(compact_response(source))
    checks = deepcopy(game["checks"])
    for check in checks:
        check["steps"].append({"action": "wait", "ms": 300})
    checks[1]["observation"] = {"source": "text_number", "selector": "#painted"}
    report = verify(game, checks)
    assert report["status"] == "passed", report["findings"]


@pytest.mark.browser
def test_runtime_restart_releases_input_and_resize_keeps_world_coordinates():
    source = SOURCE.replace(
        "state.hits=0;}\n      if(state.phase", "state.hits=0;api.resetInput();}\n      if(state.phase"
    )
    source = source.replace("x:api.width/2, held:false", "x:api.width/2, held:false,nx:0,ny:0")
    source = source.replace(
        "if(e.phase!=='down') return;",
        """if(e.phase!=='down') return;
      if(e.type==='pointer') {state.nx=Math.round(e.nx*1000)/1000;state.ny=Math.round(e.ny*1000)/1000;}
      if(e.action==='resize') {document.getElementById('gf-stage').style.width='65%';}
""",
    )
    response = compact_response(source)
    response["controls"].append({"id": "resize", "label": "Размер поля", "key": None})
    for name in ("nx", "ny"):
        response["observations"].append({"id": name, "path": name, "type": "number"})
    response["probes"] += [
        {
            "id": "restart_release",
            "category": "regression",
            "requirement": "Заново отпускает удержанную клавишу",
            "viewport": "mobile",
            "steps": [
                {"action": "key_down", "key": "ArrowRight"},
                {"action": "wait", "ms": 100},
                {"action": "control", "id": "reset"},
                {"action": "checkpoint"},
                {"action": "wait", "ms": 200},
            ],
            "observation": "x",
            "operator": "unchanged",
            "value": None,
        },
        *[
            {
                "id": "resize_" + axis,
                "category": "regression",
                "requirement": "Координаты после изменения размера остаются нормализованными",
                "viewport": "mobile",
                "steps": [
                    {"action": "control", "id": "start"},
                    {"action": "control", "id": "resize"},
                    {"action": "wait", "ms": 200},
                    {"action": "canvas", "x": 0.5, "y": 0.5},
                ],
                "observation": axis,
                "operator": "eq",
                "value": 0.5,
            }
            for axis in ("nx", "ny")
        ],
    ]
    game = artifact(response)
    checks = deepcopy(game["checks"])
    for check in checks:
        if check["id"].startswith("resize_"):
            check["steps"][2:2] = [
                {"action": "resize", "viewport": "desktop"},
                {"action": "resize", "viewport": "mobile"},
            ]
    report = verify(game, checks)
    assert report["status"] == "passed", report["findings"]


@pytest.mark.browser
def test_large_control_labels_leave_real_canvas_and_reachable_scrolling_controls():
    response = compact_response()
    for i in range(6):
        response["controls"].append(
            {"id": f"other{i}", "label": ("Длинная подпись действия " * 3).strip(), "key": None}
        )
    report = verify(artifact(response))
    assert report["status"] == "passed", report["findings"]


@pytest.mark.browser
def test_restart_does_not_duplicate_animation_loop():
    # Test-only frame instrumentation is not a recommended gameplay state/acceptance API.
    source = SOURCE.replace("held:false", "held:false,frames:0").replace(
        "render(ctx) {", "render(ctx) {state.frames++;"
    )
    response = compact_response(source)
    response["observations"].append({"id": "frames", "path": "frames", "type": "number"})
    game = artifact(response)
    checks = deepcopy(game["checks"])
    for count in (0, 5):
        checks.append(
            {
                "id": f"loop_{count}",
                "category": "regression",
                "requirement": "Перезапуск не создаёт второй цикл кадров",
                "viewport": "mobile",
                "steps": ([{"action": "tap", "selector": '[data-gf-action="reset"]'}] * count)
                + [{"action": "checkpoint"}, {"action": "wait", "ms": 300}],
                "observation": {"source": "state", "path": "gfState.frames"},
                "expect": {"operator": "increased", "value": None},
            }
        )
    report = validate(
        game["html"],
        checks,
        artifact_hash=game["artifact_hash"],
        contract=validation_contract(game["compact_manifest"], game["files"]),
        test_profile={"seed": 1729, "clock": True},
    )
    assert report["status"] == "passed", report["findings"]
    facts = {f["id"]: f for f in report["facts"]}
    deltas = [facts[f"loop_{n}"]["after"] - facts[f"loop_{n}"]["before"] for n in (0, 5)]
    assert abs(deltas[0] - deltas[1]) <= 1 and all(10 < delta < 30 for delta in deltas)
