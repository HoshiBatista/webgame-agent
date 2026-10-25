import hashlib
import json
import os
import subprocess
import sys
import traceback
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from validation.contracts import browser_watchdog_seconds, implementation_hash
from validation.runner import InvalidCheck, compare
from validation.service import validate


@pytest.fixture(autouse=True)
def browser_failure_diagnostics(request, monkeypatch):
    if "browser" not in request.keywords:
        return
    # Only synthetic test games run here. Keep detailed errors out of ordinary
    # product reports, but expose the underlying failure in CI instead of losing
    # the browser's diagnostic behind the generic infrastructure_error message.
    def failed(*args):
        pytest.fail("Isolated test browser failed: " + traceback.format_exc())

    monkeypatch.setattr("validation.service._failure", failed)


def test_observations_do_not_accept_counter_when_position_is_unchanged():
    assert not compare(12, 12, {"operator": "decreased"})
    assert compare(12, 11, {"operator": "decreased"})
    assert compare("occupied", "occupied", {"operator": "eq", "value": "occupied"})
    assert not compare(False, 1, {"operator": "eq", "value": True})
    assert not compare(True, 2, {"operator": "increased"})
    with pytest.raises(InvalidCheck):
        compare(0, 1, {"operator": "passed"})


def test_mismatched_artifact_is_never_executed():
    with patch("validation.service.subprocess.run") as execute:
        report = validate("<html></html>", [], artifact_hash="stale")
    assert report["status"] == "infrastructure_error"
    execute.assert_not_called()


def test_networked_or_mounted_browser_is_rejected(monkeypatch):
    monkeypatch.setenv("VALIDATOR_BACKEND", "docker")
    monkeypatch.delenv("VALIDATOR_SOCKET", raising=False)
    html = "<html></html>"
    for changes in (
        {"NetworkMode": "bridge"},
        {"ReadonlyRootfs": False},
        {"Privileged": True},
        {"Init": False},
        {"Init": None},
    ):
        host = {"NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"], "Init": True, **changes}
        inspect = [{"HostConfig": host, "Config": {"User": "pwuser"}, "Mounts": []}]
        with patch(
            "validation.service.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(inspect))
        ) as execute:
            report = validate(html, [], artifact_hash=hashlib.sha256(html.encode()).hexdigest())
        assert report["status"] == "infrastructure_error"
        assert execute.call_count == 1


def fixture_html(broken=False, network=False):
    move = "" if broken else "state.x++;"
    network_js = "fetch('https://example.com/private');" if network else ""
    return (
        """<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>body{margin:0}canvas{width:280px;height:180px}</style>
    <button id="begin">Играть</button><canvas width="280" height="180"></canvas><p id="result">Готово</p>
    <script>window.state={x:0,active:false};
    const c=document.querySelector('canvas'),ctx=c.getContext('2d');
    function draw(){ctx.fillStyle='#f1da88';ctx.fillRect(0,0,280,180);ctx.fillStyle='#493abb';ctx.fillRect(state.x*20+4,60,18,18);}
    begin.onclick=()=>{state.active=true;result.textContent='Идёт игра';draw()};
    c.onclick=()=>{if(!state.active)return;"""
        + move
        + """draw();if(state.x===2)result.textContent='Победа'};
    draw();"""
        + network_js
        + "</script>"
    )


def fixture_checks():
    start = {"action": "click", "selector": "#begin"}
    tap = {"action": "tap", "selector": "canvas", "x": 100, "y": 80}
    return [
        {
            "id": "begin",
            "category": "start",
            "requirement": "Начинается игра",
            "viewport": "mobile",
            "steps": [start],
            "observation": {"source": "text", "selector": "#result"},
            "expect": {"operator": "eq", "value": "Идёт игра"},
        },
        {
            "id": "move",
            "category": "control",
            "requirement": "Нажатие двигает фигуру",
            "viewport": "mobile",
            "steps": [start, tap],
            "observation": {"source": "state", "path": "state.x"},
            "expect": {"operator": "increased"},
        },
        {
            "id": "goal",
            "category": "outcome",
            "requirement": "Два шага завершают игру",
            "viewport": "desktop",
            "steps": [start, tap, tap],
            "observation": {"source": "text", "selector": "#result"},
            "expect": {"operator": "eq", "value": "Победа"},
        },
    ]


def fixture_report(html, checks):
    from validation.evidence import gates, receipt

    report = {
        "status": "passed",
        "artifact_hash": hashlib.sha256(html.encode()).hexdigest(),
        "environment": f"mini-browser-v1:{implementation_hash()}:test-browser",
        "findings": [],
        "facts": [
            {
                **{key: check[key] for key in ("id", "category", "requirement", "viewport")},
                "status": "passed",
                "actions": deepcopy(check["steps"]),
            }
            for check in checks
        ],
    }
    evidence = receipt(report['artifact_hash'], report['environment'], {'status': 'passed', 'scripts': 1}, [
        {'viewport': viewport, 'loaded': True, 'errors': [], 'requests': [],
         'surface': {'canvases': [{'visible': True, 'width': 280, 'height': 180, 'pixel_evidence': 'varied'}], 'overflow': False}}
        for viewport in ['mobile', 'desktop']])
    report.update(artifact_evidence=evidence, gates=gates(evidence), stages=[{'stage': 'syntax', 'status': 'passed'}])
    return report


@pytest.mark.parametrize("transport", ["socket", "docker", "native"])
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "status",
        "facts_missing",
        "facts_duplicate",
        "actions",
        "requirement",
        "stale",
        "hash",
        "findings",
        "desktop_only",
        "mouse_only",
    ],
)
def test_all_transports_require_actual_complete_browser_receipts(monkeypatch, transport, fault):
    html, checks = fixture_html(), fixture_checks()
    if fault == "desktop_only":
        for check in checks:
            check["viewport"] = "desktop"
    elif fault == "mouse_only":
        checks[1]["steps"][1]["action"] = "click"
    report = fixture_report(html, checks)
    if fault == "status":
        report["status"] = "looks_good"
    elif fault == "facts_missing":
        report["facts"] = []
    elif fault == "facts_duplicate":
        report["facts"][1] = deepcopy(report["facts"][0])
    elif fault == "actions":
        report["facts"][1]["actions"] = []
    elif fault == "requirement":
        report["facts"][1]["requirement"] = "Модель утверждает, что всё хорошо"
    elif fault == "stale":
        report["environment"] = "mini-browser-v1:outdated:browser"
    elif fault == "hash":
        report["artifact_hash"] = "another-candidate"
    elif fault == "findings":
        report["findings"] = [{"code": "effect_mismatch"}]
    monkeypatch.setenv("VALIDATOR_BACKEND", "native" if transport == "native" else "docker")
    if transport == "native":
        monkeypatch.setattr("validation.native.execute", lambda *_: report)
    elif transport == "socket":
        monkeypatch.setenv("VALIDATOR_SOCKET", "/private-test/validator.sock")
        monkeypatch.setattr("validation.service._socket_validate", lambda *_: report)
    else:
        monkeypatch.delenv("VALIDATOR_SOCKET", raising=False)
        config = {
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"], "Init": True},
            "Config": {"User": "10001"},
            "Mounts": [],
        }
        responses = iter(
            [SimpleNamespace(stdout=json.dumps([config])), SimpleNamespace(stdout=json.dumps(report))]
        )
        monkeypatch.setattr("validation.service.subprocess.run", lambda *_, **__: next(responses))
    result = validate(html, checks, artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert result["status"] == ("passed" if fault == "none" else "infrastructure_error")
    assert result["elapsed_seconds"] >= 0


def test_incomplete_mobile_suite_cannot_claim_complete_effect_coverage():
    from validation.contracts import suite_findings

    checks = fixture_checks()
    checks[1]["viewport"] = "desktop"
    assert suite_findings(checks)[0]["code"] == "missing_mobile_control"


def test_check_geometry_and_protocol_are_part_of_acceptance_identity(tmp_path):
    import validation.contracts as contracts

    directory = Path(contracts.__file__).parent
    for name in ("runner.py", "contracts.py", "protocol.py", "syntax.py", "checks.py", "evidence.py", "diagnostics.py"):
        (tmp_path / name).write_bytes((directory / name).read_bytes())
    assert implementation_hash(tmp_path) == implementation_hash()
    original = implementation_hash(tmp_path)
    (tmp_path / "contracts.py").write_text(
        (tmp_path / "contracts.py").read_text().replace('"width": 390', '"width": 400')
    )
    assert implementation_hash(tmp_path) != original
    original = implementation_hash(tmp_path)
    with (tmp_path / "syntax.py").open("a") as source:
        source.write("\n# parser version changed\n")
    assert implementation_hash(tmp_path) != original


def test_syntax_parser_keeps_script_bytes_and_source_locations():
    from validation.syntax import Scripts

    parser = Scripts()
    parser.feed(
        "<!-- <script>not executable</script> -->\n"
        '<script type="application/json">{"not": "javascript"}</script>\n'
        '<script\n type="text/javascript">const text = "&amp;";\n// keep newline\nstart();</script>'
    )
    parser.close()
    assert parser.scripts == [
        {
            "content": 'const text = "&amp;";\n// keep newline\nstart();',
            "line": 4,
            "column": 24,
        }
    ]


@pytest.mark.browser
@pytest.mark.parametrize(
    "broken_source",
    [
        "function start(){const active=true; // initialize game draw();}",
        "\nfunction start() {\nconst active = ;\n}\n",
    ],
)
def test_syntax_gate_reports_one_error_and_skips_game_execution(broken_source):
    # The first script would throw immediately if the parser executed game code.
    # Both scripts must compile before ANY game page or gameplay check is opened.
    html = fixture_html().replace(
        "</script>",
        "</script><script>throw new Error('game must not execute');</script>"
        f"<script>{broken_source}</script>",
    )
    report = validate(html, fixture_checks(), artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report["status"] == "failed", report
    assert report["stage"] == "syntax"
    assert report["stages"] == [{"stage": "syntax", "status": "failed", "scripts": 3}]
    assert report["facts"] == []
    assert report["screenshot_base64"] == ""
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["code"] == "javascript_syntax"
    assert finding["file"] == "index.html"
    assert finding["script_index"] == 3
    assert finding["script_line"] == (1 if broken_source.startswith("function") else 3)
    assert finding["location"] == "bundled_html"
    assert "Собранный HTML" in finding["message"]
    assert f'скрипт №3, строка {finding["script_line"]}' in finding["message"]
    assert finding["line"] >= finding["script_line"]
    assert finding["column"] > 0
    assert "SyntaxError" in finding["message"]


@pytest.mark.browser
def test_syntax_gate_ignores_non_javascript_data_blocks():
    html = fixture_html() + '<script type="application/json">{"example":"function ("}</script>'
    report = validate(html, fixture_checks(), artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report["status"] == "passed", report["findings"]
    assert report["stages"][0] == {"stage": "syntax", "status": "passed", "scripts": 1}
    assert len(report["facts"]) == len(fixture_checks())


@pytest.mark.parametrize("probe", [{"environment": "mini-browser-v1:stale:browser"}, [], None])
def test_unusable_socket_identity_never_reuses_old_browser_acceptance(monkeypatch, probe):
    from validation.service import environment_identity

    monkeypatch.setenv("VALIDATOR_BACKEND", "docker")
    monkeypatch.setenv("VALIDATOR_SOCKET", "/private-test/validator.sock")
    monkeypatch.setattr("validation.service._socket_validate", lambda *_: probe)
    assert environment_identity() == f"mini-browser-v1:{implementation_hash()}:unavailable"


def test_browser_watchdog_kills_hung_process_and_accepts_following_job(monkeypatch):
    from validation import daemon

    html, checks = fixture_html(), fixture_checks()
    expected = fixture_report(html, checks)
    real_popen = subprocess.Popen
    children = []
    programs = iter(["import time; time.sleep(30)", f"import json; print(json.dumps({expected!r}))"])

    def worker(*args, **kwargs):
        process = real_popen([sys.executable, "-c", next(programs)], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(daemon.subprocess, "Popen", worker)
    monkeypatch.setattr(daemon, "identity", lambda: expected["environment"])
    monkeypatch.setattr(daemon, "browser_watchdog_seconds", lambda _: 0.3)
    payload = {"html": html, "checks": checks, "artifact_hash": expected["artifact_hash"]}
    failure = daemon.run_bounded(payload)
    assert failure["status"] == "infrastructure_error"
    assert failure["findings"][0]["code"] == "browser_watchdog"
    assert children[0].poll() is not None
    assert daemon.run_bounded(payload) == expected
    assert children[1].returncode == 0


def test_watchdog_bounds_browser_waits_but_accepts_supported_suite():
    # Two extra clean contexts check control/outcome with the last useful input omitted.
    assert browser_watchdog_seconds(fixture_checks()) == 40
    checks = fixture_checks()
    checks[0]["steps"] = [{"action": "wait", "ms": 6000}] * 2
    with pytest.raises(ValueError):
        browser_watchdog_seconds(checks)


@pytest.mark.browser
def test_real_unix_transport_reaches_isolated_browser_without_docker_socket():
    html, checks = fixture_html(), fixture_checks()
    payload = {"html": html, "checks": checks, "artifact_hash": hashlib.sha256(html.encode()).hexdigest()}
    # Both sides run in the existing secretless networkless browser container;
    # this exercises framing and a real subprocess, not a mocked status response.
    program = """
import json, os, pathlib, sys, tempfile, threading, time
from validation.daemon import serve
from validation.service import validate
payload = json.load(sys.stdin)
with tempfile.TemporaryDirectory() as directory:
    socket_path = pathlib.Path(directory) / 'validator.sock'
    os.environ['VALIDATOR_SOCKET'] = str(socket_path)
    threading.Thread(target=serve, daemon=True).start()
    deadline = time.monotonic() + 5
    while not socket_path.exists():
        if time.monotonic() > deadline: raise RuntimeError('socket did not start')
        time.sleep(0.01)
    print(json.dumps(validate(payload['html'], payload['checks'], artifact_hash=payload['artifact_hash'])))
"""
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            os.environ.get("VALIDATOR_CONTAINER", "gf-mini-validator"),
            "python",
            "-c",
            program,
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=50,
        check=True,
    )
    report = json.loads(result.stdout)
    assert report["status"] == "passed", report["findings"]
    assert report["artifact_hash"] == payload["artifact_hash"]
    assert len(report["facts"]) == len(checks)


@pytest.mark.browser
def test_state_snapshot_is_plain_bounded_and_never_calls_accessors_or_tojson():
    program = """
import json, os
from playwright.sync_api import sync_playwright
from validation.runner import InvalidCheck, observe
cases = {
    'plain': "({position:{x:1,y:2},items:[true,null,'ready'],active:false})",
    'getter': "({nested:{get value(){window.sideEffects++;return 1}}})",
    'tojson': "({toJSON(){window.sideEffects++;return {value:1}}})",
    'function': "({callback(){window.sideEffects++}})",
    'cycle': "(()=>{const v={};v.self=v;return v})()",
    'deep': "(()=>{let v={};for(let i=0;i<14;i++)v={nested:v};return v})()",
    'wide': "Array.from({length:600},()=>1)",
    'large': "({text:'x'.repeat(9000)})",
    'sparse': "[,1]",
}
result = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path=os.environ['CHROMIUM_EXECUTABLE'])
    page = browser.new_page()
    for name, source in cases.items():
        page.evaluate('window.sideEffects=0;window.snapshot='+source+';void 0')
        try:
            observed = observe(page, {'source':'state','path':'snapshot'}, 'eq')
            result[name] = {'value':observed}
        except InvalidCheck:
            result[name] = {'unavailable':True}
        result[name]['sideEffects'] = page.evaluate('window.sideEffects')
    browser.close()
print(json.dumps(result))
"""
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            os.environ.get("VALIDATOR_CONTAINER", "gf-mini-validator"),
            "python",
            "-c",
            program,
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed.pop("plain") == {
        "value": {"position": {"x": 1, "y": 2}, "items": [True, None, "ready"], "active": False},
        "sideEffects": 0,
    }
    assert all(value == {"unavailable": True, "sideEffects": 0} for value in observed.values())


@pytest.mark.browser
@pytest.mark.parametrize(
    "broken,network,expected", [(False, False, "passed"), (True, False, "failed"), (False, True, "failed")]
)
def test_real_input_and_offline_surface(broken, network, expected):
    html = fixture_html(broken, network)
    report = validate(html, fixture_checks(), artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report["status"] == expected, report["findings"]
    assert len(report["facts"]) == 3
    assert report["stage"] == "browser"
    assert report["stages"][0] == {"stage": "syntax", "status": "passed", "scripts": 1}
    assert report["stages"][1] == {"stage": "browser", "status": expected}


@pytest.mark.browser
@pytest.mark.parametrize("broken_restart", [False, True])
def test_replay_requires_reset_and_playable_input_in_the_new_round(broken_restart):
    html = fixture_html()
    if not broken_restart:
        html = html.replace("state.active=true;", "state.x=0;state.active=true;")
    checks = fixture_checks()
    start, tap = checks[1]["steps"]
    checks.append(
        {
            "id": "replay",
            "category": "restart",
            "requirement": "Новый раунд принимает ввод с нуля",
            "viewport": "mobile",
            "steps": [start, tap, tap, start, tap],
            "observation": {"source": "state", "path": "state.x"},
            "expect": {"operator": "eq", "value": 1},
        }
    )
    report = validate(html, checks, artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report["status"] == ("failed" if broken_restart else "passed"), report["findings"]
    assert report["facts"][-1]["after"] == (3 if broken_restart else 1)


@pytest.mark.browser
def test_game_self_report_is_not_evidence():
    html = fixture_html().replace("x:0,active:false", "x:0,active:false,passed:true")
    checks = fixture_checks()
    checks[1]["observation"] = {"source": "state", "path": "state.passed"}
    checks[1]["expect"] = {"operator": "eq", "value": True}
    report = validate(html, checks, artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report["status"] == "unverified", report["findings"]


@pytest.mark.browser
def test_empty_canvas_is_visual_uncertainty_not_a_successful_game_or_mechanics_failure():
    html = fixture_html().replace("ctx.fillRect(state.x*20+4,60,18,18);", "")
    report = validate(html, fixture_checks(), artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report["status"] == "unverified", report["findings"]
    assert any(finding["code"] == "scene_visually_unverified" for finding in report["findings"])
    assert all(fact["status"] == "passed" for fact in report["facts"])
    assert all(
        canvas["pixel_evidence"] == "uniform"
        for fact in report["facts"]
        for canvas in fact["surface"]["canvases"]
    )


@pytest.mark.browser
def test_equality_can_observe_element_created_after_real_input():
    html = fixture_html().replace(
        "if(state.x===2)result.textContent='Победа'",
        "if(state.x===2){result.textContent='Победа';const message=document.createElement('p');message.id='outcome';message.textContent='Победа';document.body.appendChild(message)}",
    )
    checks = fixture_checks()
    checks[2]["observation"] = {"source": "text", "selector": "#outcome"}
    report = validate(html, checks, artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report["status"] == "passed", report["findings"]
    assert report["facts"][2]["before"] is None
    assert report["facts"][2]["after"] == "Победа"


@pytest.mark.browser
@pytest.mark.parametrize("kind", ["click_fraction", "tap_fraction"])
def test_fraction_input_measures_displayed_canvas_and_preserves_pixel_units(kind):
    html = """<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>canvas{display:block;width:300px;height:180px}</style>
    <button id="begin">Играть</button><canvas width="600" height="360"></canvas><p id="result">Готово</p>
    <script>
    window.state={active:false,x:0,hits:0};
    const c=document.querySelector('canvas'),ctx=c.getContext('2d'),result=document.querySelector('#result');
    ctx.fillStyle='#abc';ctx.fillRect(0,0,600,360);ctx.fillStyle='#936';ctx.fillRect(400,140,100,80);
    document.querySelector('#begin').onclick=()=>{state.active=true;result.textContent='Идёт игра'};
    c.addEventListener('pointerdown',e=>{if(!state.active)return;const r=c.getBoundingClientRect();
    state.x=Math.round((e.clientX-r.left)*c.width/r.width);
    if(state.x===450){state.hits++;if(state.hits===2)result.textContent='Победа'}});
    </script>"""
    checks = fixture_checks()
    point = {"action": kind, "selector": "canvas", "x": 0.75, "y": 0.5}
    checks[1]["steps"] = [checks[0]["steps"][0], point]
    checks[1]["expect"] = {"operator": "eq", "value": 450}
    checks[2]["steps"] = [checks[0]["steps"][0], point, point]
    if kind == "click_fraction":
        touch = deepcopy(checks[1])
        touch["id"] = "mobile-touch"
        touch["steps"][-1]["action"] = "tap_fraction"
        checks.append(touch)
        checks[1]["viewport"] = "desktop"
    artifact_hash = hashlib.sha256(html.encode()).hexdigest()
    report = validate(html, checks, artifact_hash=artifact_hash)
    assert report["status"] == "passed", report["findings"]
    assert report["facts"][1]["after"] == 450
    assert report["facts"][1]["actions"][-1] == point
    # Existing CSS-pixel actions keep their exact meaning: .75 pixels is not 75%.
    pixels = deepcopy(checks)
    for check in pixels:
        for step in check["steps"]:
            if step["action"] == kind:
                step["action"] = kind.removesuffix("_fraction")
    report = validate(html, pixels, artifact_hash=artifact_hash)
    assert report["status"] == "failed", report["findings"]
    assert report["facts"][1]["after"] != 450


@pytest.mark.parametrize("coordinate", [-0.01, 1.01, None, True, float("nan")])
def test_browser_does_not_execute_invalid_fraction_input(coordinate):
    from validation.runner import action

    with pytest.raises(InvalidCheck):
        action(None, None, {"action": "click_fraction", "selector": "canvas", "x": coordinate, "y": 0.5})


@pytest.mark.browser
def test_incomplete_scenarios_do_not_hide_javascript_syntax():
    html = '<canvas width="300" height="200"></canvas><script>return 1;</script>'
    report = validate(html, [], artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report['status'] == 'failed'
    assert any(f['code'] == 'javascript_syntax' for f in report['findings'])
    assert report['stages'][0]['stage'] == 'syntax'


@pytest.mark.browser
@pytest.mark.parametrize('kind', ['empty', 'runtime', 'network', 'type', 'missing', 'getter'])
def test_independent_receipts_and_bounded_diagnostics(kind):
    from generation.feedback import focus_findings
    from validation.checks import gates_verified

    html = fixture_html(network=kind == 'network')
    checks = fixture_checks()
    if kind == 'empty':
        checks = []
    elif kind == 'runtime':
        html += '<script>throw new Error("broken game")</script>'
        checks = []
    elif kind == 'type':
        html += '<script>window.visibleData=[1,2];</script>'
        checks[1]['observation'] = {'source': 'state', 'path': 'visibleData'}
        checks[1]['expect'] = {'operator': 'eq', 'value': 'wrong type'}
    elif kind == 'getter':
        html += '<script>Object.defineProperty(window,"hiddenData",{get(){throw new Error("getter executed")}});</script>'
        checks[1]['observation'] = {'source': 'state', 'path': 'hiddenData'}
    elif kind == 'missing':
        checks[1]['observation'] = {'source': 'text', 'selector': '#missing'}
    report = validate(html, checks, artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    assert report['artifact_evidence']['artifact_hash'] == report['artifact_hash']
    assert {v['viewport'] for v in report['artifact_evidence']['viewports']} == {'mobile', 'desktop'}
    if kind in {'runtime', 'network'}:
        assert report['status'] == 'failed'
        assert not gates_verified(report, checks)
    elif kind == 'empty':
        assert report['status'] == 'unverified'
        assert gates_verified(report, checks)
        assert not report['facts']
    else:
        finding = next(f for f in report['findings'] if f.get('check_id') == checks[1]['id'])
        diagnostic = finding['diagnostic']
        assert len(json.dumps(diagnostic, ensure_ascii=False).encode()) <= 8192
        assert diagnostic['controls'] and 'viewport' in diagnostic
        assert 'diagnostic' in focus_findings([finding])[0]
        if kind == 'type':
            assert diagnostic['actual_type'] == 'list'
        if kind == 'missing':
            assert diagnostic['selector_matches'] == 0
        if kind == 'getter':
            assert diagnostic['state']['missing'] is True
            assert not any('getter executed' in e for v in report['artifact_evidence']['viewports'] for e in v['errors'])


@pytest.mark.browser
@pytest.mark.parametrize('started', [False, True])
def test_canvas_created_only_after_start_is_not_inferred_broken_from_initial_probe(started):
    html = fixture_html().replace('<canvas ', '<canvas style="display:none" ')
    html = html.replace('state.active=true;', 'state.active=true;c.style.display="block";')
    checks = fixture_checks() if started else []
    report = validate(html, checks, artifact_hash=hashlib.sha256(html.encode()).hexdigest())
    if started:
        assert report['status'] == 'passed', report['findings']
    else:
        assert report['status'] == 'unverified'
        assert report['gates']['surface'] is False
        assert 'canvas_missing' not in {f['code'] for f in report['findings']}
