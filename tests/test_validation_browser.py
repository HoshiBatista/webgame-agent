"""Opt-in real Docker acceptance and regressions; never host-executes games."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest

from prompt2play.generation.runtime import (
    RUNTIME_VERSION,
    assemble_runtime,
    capture_runtime_identity,
    runtime_digest,
)
from prompt2play.paths import RESOURCE_ROOT
from prompt2play.validation import IsolatedValidator

pytestmark = pytest.mark.skipif(
    os.environ.get("P2P_RUN_ISOLATED_BROWSER") != "1",
    reason="Requires explicitly built Docker validator; no host execution fallback",
)


def fixture(name: str) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    base = RESOURCE_ROOT / "runtime" / "examples" / name
    files = {"game.js": (base / "game.js").read_text()}
    spec: dict[str, Any] = json.loads((base / "spec.json").read_text())
    acceptance: dict[str, Any] = json.loads((base / "acceptance.json").read_text())
    spec.update(
        format="runtime-v1",
        runtime={"version": RUNTIME_VERSION, "sha256": runtime_digest()},
        input_acceptance=acceptance,
    )
    return files, spec, acceptance


def execute(
    name: str,
    files: dict[str, str],
    spec: dict[str, Any],
    acceptance: dict[str, Any] | None = None,
    *,
    require_completion: bool = True,
) -> dict[str, Any]:
    root = Path(os.environ.get("P2P_BROWSER_EVIDENCE", "/tmp/prompt2play-browser-regressions"))
    directory = root / name
    report = IsolatedValidator(
        image=os.environ.get("P2P_VALIDATOR_IMAGE", "prompt2play-validator:local")
    ).validate(
        files,
        assemble_runtime(files, spec),
        spec,
        threading.Event(),
        directory,
        release_scenarios=acceptance,
        require_completion=require_completion,
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


@pytest.mark.parametrize("name", ["canvas", "dom"])
def test_reviewed_games_real_desktop_and_touch(name: str) -> None:
    files, spec, acceptance = fixture(name)
    report = execute(name, files, spec, acceptance)
    assert report["status"] == "passed", report["errors"]
    assert report["scope"] == {"isolated": True, "real_input": True, "webview": False}
    assert len(report["evidence_files"]) >= 12


def test_native_profile_rejects_smoke_oracle_instead_of_rewriting_it() -> None:
    files, spec, _ = fixture("dom")
    # A smoke oracle must be corrected; never silently reinterpret its input as a playthrough.
    spec["input_acceptance"]["desktop"]["completion"] = {"path": "/moves", "one_of": [0]}
    spec["input_acceptance"]["touch"]["completion"] = {"path": "/moves", "one_of": [0]}
    report = execute("native-conformance", files, spec)
    assert report["status"] == "unverified"
    assert "smoke test" in report["warnings"][0]
    assert report["scope"]["real_input"] is False


def test_animated_game_with_broken_keyboard_cannot_pass_input() -> None:
    files, spec, acceptance = fixture("canvas")
    files["game.js"] = files["game.js"].replace(
        'if (key === "ArrowRight" || key === " ") dispatch({type: "MOVE"});',
        'if (false) dispatch({type: "MOVE"});',
    )
    report = execute("broken-input", files, spec, acceptance)
    assert report["status"] == "failed"
    observed = next(check for check in report["checks"] if check["name"] == "input:1280")
    assert observed["status"] == "failed", "Idle animation is not caused by the keyboard input"


def test_requested_audio_and_game_owned_storage() -> None:
    files, spec, acceptance = fixture("dom")
    spec["capabilities"] += ["audio", "storage"]
    report = execute("optional-capabilities", files, spec, acceptance)
    assert report["status"] == "passed", report["errors"]
    for kind in ("audio", "persistence"):
        assert all(
            check["status"] == "passed"
            for check in report["checks"]
            if check["name"].startswith(kind + ":")
        )


def test_no_audio_no_storage_has_no_invented_obligations() -> None:
    files, spec, acceptance = fixture("dom")
    report = execute("no-optional-capabilities", files, spec, acceptance)
    assert report["status"] == "passed", report["errors"]
    assert not any(
        check["name"].startswith(("audio:", "persistence:")) for check in report["checks"]
    )


def test_csp_blocked_network_attempt_is_preserved_as_failure() -> None:
    files, spec, acceptance = fixture("dom")
    files["game.js"] = files["game.js"].replace(
        "function createGame(ctx) {",
        'function createGame(ctx) { const image = new Image(); image.src = "ht" + "tps://network.invalid/egress.png";',
    )
    report = execute("blocked-egress", files, spec, acceptance)
    assert report["status"] == "failed"
    check = next(check for check in report["checks"] if check["name"] == "external_requests:1280")
    assert check["status"] == "failed"


def test_physics_input_can_move_after_a_controlled_tick() -> None:
    files, spec, acceptance = fixture("canvas")
    files["game.js"] = (
        files["game.js"]
        .replace(
            'let phase = "ready", position = 0, elapsed = 0;',
            'let phase = "ready", position = 0, elapsed = 0, pending = false;',
        )
        .replace(
            'if (action.type === "MOVE" && phase === "playing") { position++; if (position >= 4) phase = "won"; }',
            'if (action.type === "MOVE" && phase === "playing") pending = true;',
        )
        .replace(
            "elapsed += dt; render();",
            'elapsed += dt; if (pending) { pending = false; position++; if (position >= 4) phase = "won"; } render();',
        )
        .replace(
            "({phase, position, elapsed:",
            "({phase, position, pending, elapsed:",
        )
    )
    report = execute("delayed-physics-input", files, spec, acceptance)
    assert report["status"] == "passed", report["errors"]
    check = next(check for check in report["checks"] if check["name"] == "input:1280")
    assert check["evidence"]["matched_timeline_control"] is True


@pytest.mark.parametrize("independent", [False, True])
def test_transparent_platform_toolbar_is_not_playable(independent: bool) -> None:
    files, spec, acceptance = fixture("dom")
    files["style.css"] = ".p2p-toolbar {opacity:0}"
    report = execute(
        f"transparent-toolbar-{independent}", files, spec, acceptance if independent else None
    )
    assert report["status"] == "failed"
    for width in (1280, 390):
        check = next(item for item in report["checks"] if item["name"] == f"startup:{width}")
        assert check["status"] == "failed"
        assert check["evidence"]["controls"]["rendered"] is False


def test_platform_controls_cannot_disappear_at_completion() -> None:
    files, spec, acceptance = fixture("dom")
    files["game.js"] = files["game.js"].replace(
        "function render() {", "function render() { progress.dataset.phase = phase;"
    )
    files["style.css"] = 'body:has([data-phase="won"]) .p2p-toolbar {opacity:0}'
    report = execute("transparent-terminal-toolbar", files, spec, acceptance)
    assert report["status"] == "failed"
    for width in (1280, 390):
        for kind in ("completion", "restart"):
            check = next(item for item in report["checks"] if item["name"] == f"{kind}:{width}")
            assert check["status"] == "failed"


def test_below_fold_controls_require_real_swipes_before_touch_input() -> None:
    files, spec, acceptance = fixture("dom")
    files["game.js"] = files["game.js"].replace(
        '<div id="beacons">',
        '<p style="min-height:1100px">Swipe upwards to reach the controls below.</p><div id="beacons">',
    )
    report = execute("long-dom-real-scroll", files, spec, acceptance)
    assert report["status"] == "passed", report["errors"]
    check = next(item for item in report["checks"] if item["name"] == "mobile_layout:390")
    assert check["evidence"]["real_scroll_required"] is True
    assert check["evidence"]["scroll_probe"]["actual_touch"] is True
    assert check["evidence"]["scroll_probe"]["scroll_changed"] is True
    assert any(item["path"] == "touch-scroll-after-390.png" for item in report["evidence_files"])


def test_blocked_finger_scrolling_is_a_mobile_layout_failure() -> None:
    files, spec, acceptance = fixture("dom")
    files["game.js"] = files["game.js"].replace(
        '<p id="progress"></p>',
        '<p id="progress"></p><p style="min-height:1100px">Scroll-only content below the controls.</p>',
    )
    files["style.css"] = "#p2p-surface {touch-action:none}"
    report = execute("blocked-touch-scroll", files, spec, acceptance)
    assert report["status"] == "failed"
    layout = next((item for item in report["checks"] if item["name"] == "mobile_layout:390"), None)
    if layout is not None:
        assert layout["status"] == "failed"
        assert layout["evidence"]["scroll_probe"]["actual_touch"] is True
        assert layout["evidence"]["scroll_probe"]["scroll_changed"] is False
    else:
        # Element screenshot normalization may move the viewport earlier;
        # the same blocked gesture must reject reaching the control itself.
        failure = next(item for item in report["checks"] if item["name"] == "runtime_harness:390")
        assert failure["status"] == "failed"
        reachability = failure["evidence"]["touch_reachability"]
        assert reachability["real_touch_attempted"] is True
        assert all(swipe["scroll_changed"] is False for swipe in reachability["swipes"])


def test_dense_buttons_can_pan_without_locator_auto_scrolling() -> None:
    files, spec, acceptance = fixture("dom")
    files["style.css"] = (
        "#beacons{display:flex;flex-direction:column}"
        "#beacons button{width:100%;margin:0!important;min-height:210px!important}"
    )
    report = execute("dense-buttons-real-scroll", files, spec, acceptance)
    assert report["status"] == "passed", report["errors"]
    layout = next(item for item in report["checks"] if item["name"] == "mobile_layout:390")
    assert layout["evidence"]["scroll_probe"]["point"]["button_fallback"] is True
    assert layout["evidence"]["scroll_probe"]["actual_touch"] is True
    assert layout["evidence"]["scroll_probe"]["scroll_changed"] is True


@pytest.mark.parametrize("scenario", ["scope", "resize"])
def test_runtime_scoped_input_and_resize_lifecycle(scenario: str) -> None:
    """Qualify platform event ownership with real input and explicit API negatives."""
    fixtures = Path(__file__).parent / "browser_fixtures"
    root = Path(os.environ.get("P2P_BROWSER_EVIDENCE", "/tmp/prompt2play-browser-regressions"))
    directory = root / f"runtime-{scenario}"
    inputs, evidence = directory / "input", directory / "evidence"
    inputs.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    inputs.chmod(0o755)
    evidence.chmod(0o777)
    source = (fixtures / f"runtime_{scenario}_game.js").read_text()
    spec = {
        "title": "Scoped input API qualification",
        "capabilities": ["input", "lifecycle"],
        "runtime": capture_runtime_identity(),
    }
    html = assemble_runtime(
        {
            "game.js": source,
            "style.css": (
                "button{display:block;min-height:48px;margin:8px;padding:8px}main{padding:12px}"
                if scenario == "scope"
                else ""
            ),
        },
        spec,
    )
    image = os.environ.get("P2P_VALIDATOR_IMAGE", "prompt2play-validator:local")
    inspected = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )
    image_id = inspected.stdout.strip()
    assert image_id.startswith("sha256:")
    harness_files = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(IsolatedValidator().runtime_path.parent.glob("*.mjs"))
    }
    (inputs / "game.html").write_text(html)
    (inputs / "config.json").write_text(
        json.dumps(
            {
                "image": image_id,
                "runtime": spec["runtime"],
                "harness_files_sha256": harness_files,
            }
        )
    )
    name = "p2p-input-scope-" + uuid.uuid4().hex
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--pull=never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--cpus",
        "1",
        "--memory",
        "768m",
        "--memory-swap",
        "768m",
        "--pids-limit",
        "256",
        "--user",
        "10001:10001",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=192m",
        "--shm-size",
        "128m",
        "--mount",
        f"type=bind,src={inputs.resolve()},dst=/input,readonly",
        "--mount",
        f"type=bind,src={evidence.resolve()},dst=/evidence",
        "--mount",
        f"type=bind,src={(fixtures / f'runtime_{scenario}.mjs').resolve()},dst=/review/challenge.mjs,readonly",
        image_id,
        "node",
        "/review/challenge.mjs",
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=90, check=True)
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, timeout=15, check=False
        )
    report = json.loads(completed.stdout)
    (root / f"runtime-{scenario}-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    assert report["passed"] is True, [check for check in report["checks"] if not check["passed"]]
    assert report["html_sha256"] == hashlib.sha256(html.encode()).hexdigest()
    assert (
        report["script_sha256"]
        == hashlib.sha256((fixtures / f"runtime_{scenario}.mjs").read_bytes()).hexdigest()
    )
    assert report["runtime"] == spec["runtime"] and report["validator_image_sha256"] == image_id
    assert report["harness_files_sha256"] == harness_files
    for item in report["evidence_files"]:
        path = evidence / item["path"]
        assert path.is_file() and not path.is_symlink() and path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_strategy_wait_advances_all_ticks_and_preserves_step_observations() -> None:
    files, spec, acceptance = fixture("canvas")
    files["game.js"] = files["game.js"].replace('if (position >= 4) phase = "won";', "")
    files["game.js"] = files["game.js"].replace(
        "elapsed += dt; render();",
        'elapsed += dt; if (position >= 4 && elapsed >= 20) phase = "won"; render();',
    )
    for device in ("desktop", "touch"):
        acceptance[device]["steps"].append({"kind": "wait", "ms": 21000})
    report = execute("strategy-long-wait", files, spec, acceptance)
    assert report["status"] == "passed", report["errors"]
    for width in (1280, 390):
        completion = next(c for c in report["checks"] if c["name"] == f"completion:{width}")
        assert completion["evidence"]["observed"] == "won"
        assert completion["evidence"]["recent_observations"][-1]["action"]["ms"] == 21000
        assert any(f["path"] == f"scenario-{width}.json" for f in report["evidence_files"])


def test_incomplete_gameplay_does_not_get_automatic_terminal_success() -> None:
    files, spec, acceptance = fixture("dom")
    for device in ("desktop", "touch"):
        acceptance[device]["steps"] = acceptance[device]["steps"][:1]
    report = execute("incomplete-playthrough", files, spec, acceptance)
    assert report["status"] == "failed"
    for width in (1280, 390):
        completion = next(c for c in report["checks"] if c["name"] == f"completion:{width}")
        assert completion["status"] == "failed"
        assert completion["evidence"]["observed"] == "playing"
        assert len(completion["evidence"]["steps"]) == 1


def test_manual_playthrough_runs_controls_restart_and_never_claims_victory() -> None:
    files, spec, acceptance = fixture("dom")
    for device in ("desktop", "touch"):
        acceptance[device]["steps"] = acceptance[device]["steps"][:1]
        acceptance[device]["completion"] = {"path": "/moves", "one_of": [1]}
    report = execute("manual-playthrough", files, spec, acceptance, require_completion=False)
    assert report["status"] == "passed", report["errors"]
    assert (
        report["completion_required"] is False and report["playthrough"] == "human_review_required"
    )
    for width in (1280, 390):
        complete = next(c for c in report["checks"] if c["name"] == f"completion:{width}")
        assert (
            complete["status"] == "skipped" and complete["evidence"]["observed_phase"] == "playing"
        )
        assert (
            next(c for c in report["checks"] if c["name"] == f"restart:{width}")["status"]
            == "passed"
        )


def test_manual_playthrough_still_rejects_broken_keyboard() -> None:
    files, spec, acceptance = fixture("canvas")
    files["game.js"] = files["game.js"].replace(
        'if (key === "ArrowRight" || key === " ") dispatch({type: "MOVE"});',
        'if (false) dispatch({type: "MOVE"});',
    )
    report = execute("manual-broken-input", files, spec, acceptance, require_completion=False)
    assert report["status"] == "failed"
    assert next(c for c in report["checks"] if c["name"] == "input:1280")["status"] == "failed"


@pytest.mark.parametrize("broken", [True, False])
def test_held_controls_release_and_opposites_are_required(broken: bool) -> None:
    files, spec, acceptance = fixture("canvas")
    source = """function createGame(ctx) {
      let phase='ready', x=200, y=140, vx=0, vy=0;
      ctx.root.innerHTML='<h1>Authored input regression</h1><canvas width="640" height="320"></canvas><button id="left">Left</button><button id="right">Right</button>';
      const c=ctx.root.querySelector('canvas'),g=c.getContext('2d');
      function render(){g.fillStyle='#132030';g.fillRect(0,0,640,320);g.fillStyle='#f1d080';g.fillRect(x,y,32,32);}
      function movement(pressed){vx=(pressed.includes('ArrowRight')?60:0)-(pressed.includes('ArrowLeft')?60:0);vy=(pressed.includes('ArrowDown')?60:0)-(pressed.includes('ArrowUp')?60:0);}
      INPUT_BINDING
      ctx.input.on(ctx.root.querySelector('#left'),'click',()=>{x-=20;render();});
      ctx.input.on(ctx.root.querySelector('#right'),'click',()=>{x+=20;render();});
      ctx.clock.fixedStep(dt=>{if(phase==='playing'){x+=vx*dt;y+=vy*dt;render();}});
      render();return {snapshot:()=>({phase,x,y,vx,vy}),dispatch(a){if(a.type==='START')phase='playing';render();}};
    }"""
    binding = "ctx.input.keys(pressed=>movement(pressed));"
    if broken:
        binding = "const held=new Set();ctx.input.key((key,event)=>{if(event.type==='keyup')held.delete(key);else held.add(key);movement([...held]);});"
    files["game.js"] = source.replace("INPUT_BINDING", binding)

    def check(after: int, before: int, path: str, op: str, literal: str = "") -> dict[str, Any]:
        return {
            "after_step": after,
            "before_step": before,
            "path": path,
            "op": op,
            "value_json": literal,
            "tolerance": 0.001,
        }

    steps: list[dict[str, Any]] = []
    assertions = []
    keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"]
    for key in keys:
        path = "/x" if key in keys[:2] else "/y"
        velocity = "/vx" if key in keys[:2] else "/vy"
        op = "less" if key in ("ArrowLeft", "ArrowUp") else "greater"
        start = len(steps)
        steps.extend(
            [
                {"kind": "key_down", "key": key},
                {"kind": "wait", "ms": 200},
                {"kind": "key_up", "key": key},
                {"kind": "wait", "ms": 200},
                {"kind": "key_down", "key": key},
                {"kind": "wait", "ms": 200},
                {"kind": "key_up", "key": key},
            ]
        )
        assertions.extend(
            [
                check(start + 2, start + 1, path, op),
                check(start + 3, -1, velocity, "equal", "0"),
                check(start + 4, start + 3, path, "equal"),
                check(start + 6, start + 5, path, op),
            ]
        )
    steps.extend([{"kind": "key_down", "key": "ArrowRight"}, {"kind": "blur"}, {"kind": "focus"}])
    assertions.append(check(len(steps) - 1, -1, "/vx", "equal", "0"))
    matrix = [
        {
            "id": "movement",
            "description": "Every arrow supports hold, release, repeat and focus recovery",
            "actions": ["MOVE"],
            "keyboard_keys": keys,
            "continuous": True,
            "desktop": {"steps": steps, "assertions": assertions},
            "touch": {
                "steps": [
                    {"kind": "tap", "selector": "#left"},
                    {"kind": "tap", "selector": "#right"},
                ],
                "assertions": [check(1, 0, "/x", "less"), check(2, 1, "/x", "greater")],
            },
        }
    ]
    acceptance["desktop"]["steps"] = [{"kind": "key", "key": "ArrowRight", "repeat": 1}]
    acceptance["touch"]["steps"] = [{"kind": "tap", "selector": "#left", "repeat": 1}]
    spec.update(
        mechanics_required=True, mechanics_required_actions=["MOVE"], mechanics_acceptance=matrix
    )
    report = execute(
        "held-controls-" + ("broken" if broken else "fixed"),
        files,
        spec,
        acceptance,
        require_completion=False,
    )
    assert report["status"] == ("failed" if broken else "passed"), report.get("errors")
    desktop = next(c for c in report["checks"] if c["name"] == "mechanics:1280")
    assert desktop["status"] == ("failed" if broken else "passed")
    assert any(c["name"] == "input:1280" and c["status"] == "passed" for c in report["checks"]), (
        "Smoke input alone should miss this defect"
    )
