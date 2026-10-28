"""Regressions from the 28 October review; browser cases execute isolated Chromium."""

from copy import deepcopy

import pytest

from generation.artifacts import sha256
from generation.requirements import coverage, manifest
from validation.check_program import compile_check
from validation.service import validate


def regression(steps, operator='unchanged'):
    return {'id': 'stable', 'category': 'regression', 'requirement': 'Состояние сохраняется',
            'viewport': 'mobile', 'steps': steps, 'observation': {'source': 'state', 'path': 's.value'},
            'expect': {'operator': operator, 'value': None}}


def test_edit_preserves_frozen_requirements_across_five_amendments():
    original = manifest('игра', {'requirements': [
        {'id': 'goal', 'category': 'outcome', 'requirement': 'Достичь цели', 'viewport': 'mobile'},
    ]})
    frozen = deepcopy(original)
    for i in range(5):
        frozen = manifest('игра', previous=frozen, amendment=f'Изменить цвет {i}')
        assert frozen['requirements'] == original['requirements']
        assert coverage([], frozen)['uncovered'] == ['goal']
    assert len(frozen['amendments']) == 5
    frozen['requirements'][0]['requirement'] = 'changed'
    assert original['requirements'][0]['requirement'] == 'Достичь цели'


@pytest.mark.parametrize('key', ['ц', 'NotAKey', 'Control+ц', 'Control++A'])
def test_unsupported_key_is_a_scenario_error_before_browser(key):
    program = compile_check(regression([{'action': 'press', 'key': key}]))
    assert program.issue and program.issue.code == 'invalid_check'
    assert program.issue.field == 'steps.key'


@pytest.mark.browser
@pytest.mark.native_browser
@pytest.mark.parametrize('return_to_initial', [False, True])
def test_unchanged_observes_the_entire_window(monkeypatch, return_to_initial):
    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    html = '''<style>body{margin:0}</style><canvas width="200" height="200"></canvas>
    <script>window.s={value:0};const c=document.querySelector('canvas');
    c.getContext('2d').fillRect(10,10,20,20);
    c.onclick=()=>{setTimeout(()=>s.value=1,180);RETURN};</script>'''.replace(
        'RETURN', 'setTimeout(()=>s.value=0,360)' if return_to_initial else '')
    check = regression([{'action': 'click', 'selector': 'canvas', 'x': 20, 'y': 20},
                        {'action': 'wait_for', 'ms': 550}])
    report = validate(html, [check], artifact_hash=sha256(html))
    fact = next(f for f in report['facts'] if f['id'] == 'stable')
    assert fact['status'] == 'failed', report
    assert fact['comparison'] is False
    assert not any(f['code'] == 'browser_error' for f in report['findings'])


@pytest.mark.browser
@pytest.mark.native_browser
def test_intermediate_conditions_wait_for_readiness_and_keep_real_input(monkeypatch):
    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    html = '''<canvas width="200" height="200"></canvas><button id="start">Старт</button>
    <script>window.s={ready:false,count:0};const c=document.querySelector('canvas');
    c.getContext('2d').fillRect(10,10,30,30);start.onclick=()=>setTimeout(()=>s.ready=true,180);
    c.onclick=()=>{if(s.ready)s.count++};</script>'''
    condition = {'observation': {'source': 'state', 'path': 's.ready'}, 'expect': {'operator': 'eq', 'value': True}}
    check = {**regression([]), 'steps': [
        {'action': 'click', 'selector': '#start'},
        {'action': 'await_condition', 'ms': 600, **condition},
        {'action': 'assert', 'ms': 0, **condition},
        {'action': 'click', 'selector': 'canvas', 'x': 20, 'y': 20}],
        'observation': {'source': 'state', 'path': 's.count'}, 'expect': {'operator': 'eq', 'value': 1}}
    report = validate(html, [check], artifact_hash=sha256(html))
    fact = report['facts'][0]
    assert fact['status'] == 'passed', report
    assert len(fact['input_probes']) == 2
    assert len([s for s in fact['trace'] if 'assertion' in s]) == 2


@pytest.mark.browser
@pytest.mark.native_browser
def test_bad_key_is_not_infrastructure_and_hidden_text_is_not_a_visible_outcome(monkeypatch):
    from studio.acceptance import assess

    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    html = '<canvas width="100" height="100"></canvas><p id="end" hidden>Победа</p><script>window.s={value:0}</script>'
    checks = [regression([{'action': 'press', 'key': 'ц'}]),
              {**regression([]), 'id': 'hidden', 'observation': {'source': 'text', 'selector': '#end'},
               'expect': {'operator': 'eq', 'value': 'Победа'}}]
    report = validate(html, checks, artifact_hash=sha256(html))
    assert all(f['status'] == 'unverified' for f in report['facts'])
    assert {f['code'] for f in report['findings']} >= {'invalid_check'}
    assert not any(f['code'] == 'browser_error' for f in report['findings'])
    assert assess(report, checks, [])['action'] == 'review'
