"""Independent v8 review: fail closed when evidence does not establish an effect."""

from copy import deepcopy

import pytest

from generation.artifacts import sha256
from validation.runner import without_last_input
from validation.service import _validated_report, validate


def scene(script):
    return ('<!doctype html><style>body{margin:0}canvas{width:280px;height:180px}</style>'
            '<button id="start">Начать</button><canvas width="280" height="180"></canvas>'
            '<script>const ctx=document.querySelector("canvas").getContext("2d");'
            'ctx.fillStyle="orange";ctx.fillRect(0,0,280,180);'
            'ctx.fillStyle="navy";ctx.fillRect(40,40,50,50);' + script + '</script>')


def scenarios(steps):
    return [{"id": category, "category": category, "requirement": "Настоящее действие даёт игровой эффект",
             "viewport": "desktop" if category == "outcome" else "mobile",
             "steps": deepcopy(steps), "observation": {"source": "state", "path": "s.done"},
             "expect": {"operator": "eq", "value": True}}
            for category in ["start", "control", "outcome"]]


def test_release_after_checkpoint_is_the_measured_action_not_its_setup():
    check = scenarios([
        {"action": "key_down", "key": "Space"}, {"action": "checkpoint"},
        {"action": "key_up", "key": "Space"},
    ])[1]
    control = without_last_input(check)
    assert control["_omitted"] == [2]
    assert control["steps"] == check["steps"][:2]


@pytest.mark.browser
def test_key_up_only_cannot_certify_constant_control_and_outcome():
    html = scene('window.s={done:true};')
    report = validate(html, scenarios([{"action": "key_up", "key": "Space"}]), artifact_hash=sha256(html))
    assert report["status"] == "unverified", report
    assert {f['check_id'] for f in report['findings'] if f['code'] == 'effect_not_causal'} == {'control', 'outcome'}


@pytest.mark.browser
def test_real_release_effect_after_checkpoint_keeps_setup_and_passes():
    html = scene('''window.s={done:false};
      addEventListener('keydown',()=>{s.done=false;});
      addEventListener('keyup',()=>{s.done=true;});''')
    checks = scenarios([{'action': 'key_down', 'key': 'Space'}, {'action': 'checkpoint'},
                        {'action': 'key_up', 'key': 'Space'}])
    for check in checks:
        check['expect'] = {'operator': 'changed', 'value': None}
    report = validate(html, checks, artifact_hash=sha256(html))
    # Keyboard evidence remains valid, but it cannot certify mobile touch coverage.
    assert report['status'] == 'unverified', report
    assert {f['code'] for f in report['findings']} == {'missing_mobile_control', 'incomplete_checks'}
    assert all(fact['status'] == 'passed' for fact in report['facts'])
    for fact in report['facts'][1:]:
        assert fact['counterfactual']['execution_valid'] is True
        assert fact['counterfactual']['omitted_steps'] == [2]
        assert fact['counterfactual']['comparison'] is False


@pytest.mark.browser
def test_counterfactual_runtime_failure_is_not_evidence_of_causality():
    html = scene('''window.s={done:false};
      start.onclick=()=>{setTimeout(()=>{if(!s.done)throw new Error('control run failed');},200);};
      addEventListener('keydown',()=>{s.done=true;});''')
    checks = scenarios([{"action": "click", "selector": "#start", "x": None, "y": None},
                        {"action": "press", "key": "Space"}, {"action": "wait", "ms": 300}])
    report = validate(html, checks, artifact_hash=sha256(html))
    assert report["status"] == "unverified", report
    assert all(f['status'] == 'unverified' for f in report['facts'] if f['category'] in {'control', 'outcome'})


@pytest.mark.browser
def test_keyboard_focus_does_not_click_a_game_control_on_the_players_behalf():
    html = scene('window.s={done:false};start.onclick=()=>{s.done=true;};').replace(
        '<button ', '<button style="position:fixed;top:0;left:0;width:70px;height:40px" ',
    )
    report = validate(html, scenarios([{'action': 'press', 'key': 'ArrowRight'}]), artifact_hash=sha256(html))
    assert all(f.get('comparison') is False for f in report['facts']), report
    assert report['status'] == 'failed'


@pytest.mark.parametrize('compact', [False, True])
def test_success_without_artifact_receipt_is_rejected(compact):
    from tests.test_validation import fixture_checks, fixture_html, fixture_report

    html, checks = fixture_html(), fixture_checks()
    report = fixture_report(html, checks)
    report.pop('artifact_evidence', None)
    contract = {'runtime_version': 2, 'source_hash': 'a' * 64, 'controls': [], 'observations': []} if compact else None
    with pytest.raises(ValueError, match='artifact.*receipt'):
        _validated_report(report, checks, sha256(html), 0, contract=contract)
