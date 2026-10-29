"""Initial browser frames must run before probing a generated game's controls."""

import pytest

from generation.artifacts import sha256
from validation.service import validate


@pytest.mark.browser
@pytest.mark.parametrize("layout_ready", [True, False])
def test_initial_animation_frame_layout_is_measured_without_bypassing_obstruction(layout_ready):
    html = """<style>body{margin:0}canvas{display:block;width:1200px;height:900px}</style>
    <canvas id="board" width="200" height="200"></canvas>
    <button id="start">Start</button><button id="hit">Hit</button><p id="status">Ready</p>
    <script>
    const board=document.getElementById('board'), label=document.getElementById('status');
    const ctx=board.getContext('2d');ctx.fillStyle='orange';ctx.fillRect(20,20,100,100);
    let playing=false,count=0;
    document.getElementById('start').onclick=()=>{playing=true;label.textContent='Playing';};
    document.getElementById('hit').onclick=()=>{if(playing){count++;label.textContent=count===2?'Win':'One';}};
    requestAnimationFrame(()=>requestAnimationFrame(()=>{LAYOUT}));
    </script>""".replace(
        "LAYOUT", "board.style.width='200px';board.style.height='200px';" if layout_ready else ""
    )
    if not layout_ready:
        html += '<div style="position:fixed;inset:0;z-index:100;background:#ccc">Blocked</div>'

    def tap(selector):
        return {"action": "tap", "selector": selector, "x": None, "y": None}

    checks = [
        {"id": "start", "category": "start", "steps": [tap("#start")], "value": "Playing"},
        {"id": "move", "category": "control", "steps": [tap("#start"), tap("#hit")], "value": "One"},
        {
            "id": "win",
            "category": "outcome",
            "steps": [tap("#start"), tap("#hit"), tap("#hit")],
            "value": "Win",
        },
    ]
    checks = [
        {
            **{k: v for k, v in c.items() if k != "value"},
            "requirement": "Проверяем действие игрока",
            "viewport": "mobile",
            "observation": {"source": "text", "selector": "#status"},
            "expect": {"operator": "eq", "value": c["value"]},
        }
        for c in checks
    ]
    report = validate(html, checks, artifact_hash=sha256(html))
    if layout_ready:
        assert report["status"] == "passed", report
        for fact in report["facts"][1:]:
            pair = fact["causal_evidence"]
            assert pair["matched_setup"]
            assert pair["action"]["execution_valid"] and pair["control"]["execution_valid"]
            assert pair["action"]["comparison"] and not pair["control"]["comparison"]
            assert (
                pair["action"]["isolation"]["clock_matched"] and pair["control"]["isolation"]["clock_matched"]
            )
    else:
        assert report["status"] != "passed"
        assert any(f["code"] == "input_obstructed" for f in report["findings"]), [
            (f["code"], f.get("message")) for f in report["findings"]
        ]
