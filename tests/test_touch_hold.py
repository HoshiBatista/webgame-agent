"""Real held touch, release, duration bounds and time-matched control experiment."""
from copy import deepcopy

import pytest

from generation.artifacts import sha256
from validation.check_program import compile_check
from validation.contracts import suite_findings
from validation.service import validate


def holding():
    return {'id': 'hold', 'category': 'control', 'requirement': 'Удержание кнопки двигает игрока',
            'viewport': 'mobile', 'steps': [
                {'action': 'checkpoint'},
                {'action': 'hold_touch', 'selector': '#right', 'x': None, 'y': None, 'ms': 300}],
            'observation': {'source': 'text_number', 'selector': '#position'},
            'expect': {'operator': 'increased', 'value': None}}


def test_hold_counterfactual_omits_finger_but_preserves_time():
    check = holding()
    program = compile_check(check)
    assert program.issue is None
    copy = program.without_last_input()
    assert copy['steps'] == [{'action': 'checkpoint'}, {'action': 'wait', 'ms': 300}]
    assert program.wait_seconds == compile_check({k: v for k, v in copy.items() if not k.startswith('_')},
                                                timer_outcome=True).wait_seconds
    assert not any(f['code'] == 'missing_mobile_control' for f in suite_findings([check]))


@pytest.mark.parametrize('change', [{'ms': 0}, {'ms': 3001}, {'ms': True}, {'x': 1}, {'selector': None}])
def test_invalid_hold_is_rejected_before_browser(change):
    check = holding()
    check['steps'][-1].update(change)
    try:
        program = compile_check(check)
    except ValueError:
        return
    assert program.issue


def test_desktop_cannot_claim_touch_control():
    check = holding()
    check['viewport'] = 'desktop'
    assert compile_check(check).issue


HTML = '''<style>body{margin:0}button{width:120px;height:60px;touch-action:none}</style>
<canvas width="200" height="200"></canvas><button id="right">Вправо</button>
<output id="position">0</output><output id="input">нет</output>
<script>const c=document.querySelector('canvas');c.getContext('2d').fillRect(10,10,30,30);
let held=false,x=0;const b=document.querySelector('#right'),out=document.querySelector('#position');
b.addEventListener('pointerdown',e=>{if(e.pointerType==='touch'&&e.isTrusted){held=true;document.querySelector('#input').textContent='touch';}});
b.addEventListener('pointerup',()=>held=false);b.addEventListener('pointercancel',()=>held=false);
setInterval(()=>{if(CONDITION){x++;out.textContent=x}},20);</script>'''


@pytest.mark.browser
@pytest.mark.native_browser
def test_real_touch_is_held_then_released_without_mouse(monkeypatch):
    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    html = HTML.replace('CONDITION', 'held')
    check = holding()
    check['steps'].append({'action': 'assert', 'ms': 0,
                          'observation': {'source': 'text', 'selector': '#input'},
                          'expect': {'operator': 'eq', 'value': 'touch'}})
    release = deepcopy(holding())
    release.update(id='release', category='regression')
    release['steps'] = [release['steps'][-1], {'action': 'checkpoint'}, {'action': 'wait', 'ms': 150}]
    release['expect'] = {'operator': 'unchanged', 'value': None}
    report = validate(html, [check, release], artifact_hash=sha256(html))
    facts = {f['id']: f for f in report['facts']}
    assert facts['hold']['status'] == facts['release']['status'] == 'passed', report['findings']
    assert facts['hold']['counterfactual']['comparison'] is False
    assert not any(f['code'] == 'browser_error' for f in report['findings'])


@pytest.mark.browser
@pytest.mark.native_browser
def test_timer_progress_is_not_evidence_of_touch_control(monkeypatch):
    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    html = HTML.replace('CONDITION', 'true')
    report = validate(html, [holding()], artifact_hash=sha256(html))
    fact = next(f for f in report['facts'] if f['id'] == 'hold')
    assert fact['status'] != 'passed', report
    assert fact['counterfactual']['comparison'] is True
