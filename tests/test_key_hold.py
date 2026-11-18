from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from jsonschema import Draft202012Validator

from generation.schema import response_schema, validate_checks
from tests.test_pro_creative import creative_request
from validation.check_program import compile_check
from validation.runner import action


def check():
    return {'id': 'keys', 'category': 'control', 'viewport': 'desktop',
            'requirement': 'Клавиша перемещает игрока к видимой цели.',
            'steps': [{'action': 'hold_key', 'key': 'ArrowRight', 'ms': 250}],
            'observation': {'source': 'text_number', 'selector': '#score'},
            'expect': {'operator': 'gte', 'value': 1}}


def test_key_hold_keeps_identical_time_without_input():
    original = check()
    validate_checks([original], require_complete=False)
    program = compile_check(original)
    assert program.issue is None
    negative = program.without_last_input()
    assert negative['steps'] == [{'action': 'wait', 'ms': 250}]
    assert negative['expect'] == original['expect']
    assert original['steps'][0]['action'] == 'hold_key'


@pytest.mark.parametrize('change', [{'ms': 0}, {'ms': 3001}, {'ms': True},
                                    {'key': 'not-a-key'}, {'key': 'Control+a'}])
def test_key_hold_rejects_unbounded_time_and_invalid_keys(change):
    c = check()
    c['steps'][0].update(change)
    try:
        program = compile_check(c)
    except ValueError:
        return
    assert program.issue is not None


@pytest.mark.parametrize('fails', [False, True])
def test_key_hold_releases_even_when_browser_wait_fails(fails):
    page = MagicMock()
    page.evaluate.return_value = 'IFRAME'
    with patch('validation.runner.wait', side_effect=RuntimeError('closed') if fails else None) as wait:
        if fails:
            with pytest.raises(RuntimeError, match='closed'):
                action(page, MagicMock(), check()['steps'][0])
        else:
            action(page, MagicMock(), check()['steps'][0])
        wait.assert_called_once_with(page, 250)
    page.keyboard.down.assert_called_once_with('ArrowRight')
    page.keyboard.up.assert_called_once_with('ArrowRight')


@pytest.mark.parametrize('operation', ['create', 'edit', 'repair', 'check_repair'])
def test_only_v3_exposes_key_hold_to_the_model(operation):
    request = creative_request('gameplay')
    request.pop('pro_parallel_branch')
    request['operation'] = operation
    request['check_repair'] = {'protected_checks': []}
    for version in [None, 1, 2, 3]:
        req = {**deepcopy(request), 'pro_parallel': version}
        schema = response_schema(req)['properties']['checks']['items']
        assert Draft202012Validator(schema).is_valid(check()) is (version == 3)


@pytest.mark.browser
@pytest.mark.native_browser
@pytest.mark.parametrize('timer_only', [False, True])
def test_native_keyboard_hold_releases_and_rejects_timer_only_effect(monkeypatch, timer_only):
    from generation.artifacts import sha256
    from validation.service import validate

    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    html = '''<canvas width="200" height="200"></canvas><output id="score">0</output>
<script>document.querySelector('canvas').getContext('2d').fillRect(10,10,30,30);
let held=false,n=0;addEventListener('keydown',e=>{if(e.isTrusted&&e.code==='ArrowRight')held=true});
addEventListener('keyup',e=>{if(e.isTrusted&&e.code==='ArrowRight')held=false});
setInterval(()=>{if(CONDITION)document.querySelector('#score').textContent=++n},20);</script>'''
    html = html.replace('CONDITION', 'true' if timer_only else 'held')
    release = deepcopy(check())
    release.update(id='release', category='regression')
    release['steps'] += [{'action': 'checkpoint'}, {'action': 'wait', 'ms': 150}]
    release['expect'] = {'operator': 'unchanged', 'value': None}
    report = validate(html, [check(), release], artifact_hash=sha256(html))
    facts = {f['id']: f for f in report['facts']}
    assert (facts['keys']['status'] == 'passed') is not timer_only, report['findings']
    assert (facts['release']['status'] == 'passed') is not timer_only, report['findings']
    assert facts['keys']['counterfactual']['comparison'] is timer_only
