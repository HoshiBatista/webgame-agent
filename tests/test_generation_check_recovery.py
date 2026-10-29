"""Reported cloud failure: quoted numbers and a result screen hiding the field."""

from copy import deepcopy

import pytest

from generation.artifacts import sha256
from validation.check_program import compile_check
from validation.checks import review_checks
from validation.service import validate


def numeric_check(value='1'):
    return {'id': 'count', 'category': 'control', 'viewport': 'mobile',
            'requirement': 'Нажатие открывает карточку и увеличивает счёт',
            'steps': [{'action': 'tap', 'selector': '#hit', 'x': None, 'y': None}],
            'observation': {'source': 'text_number', 'selector': '#count'},
            'expect': {'operator': 'eq', 'value': value}}


@pytest.mark.parametrize('value,expected', [('1', 1), (' 36 ', 36), ('-1.5', -1.5), ('1e2', 100)])
@pytest.mark.parametrize('action,ms', [('assert', 0), ('await_condition', 100)])
def test_quoted_numeric_expectation_is_normalized_including_nested_assertions(value, expected, action, ms):
    check = numeric_check(value)
    check['steps'].append({'action': action, 'ms': ms, 'observation': deepcopy(check['observation']),
                           'expect': deepcopy(check['expect'])})
    original = deepcopy(check)
    effective, changes = review_checks([check])
    assert check == original
    assert effective[0]['expect']['value'] == expected
    assert effective[0]['steps'][-1]['expect']['value'] == expected
    assert len(changes) == 2 and changes[0]['step_index'] == 1
    assert all(c['code'] == 'explicit_numeric_expectation' for c in changes)
    assert review_checks(effective) == (effective, [])
    assert compile_check(check).issue is None
    assert compile_check(check).check() == effective[0]


@pytest.mark.parametrize('value', ['Счёт: 1', '1px', '1,5', '', 'NaN', '1e999', '9007199254740993', True, None])
def test_ambiguous_or_lossy_numeric_expectations_are_not_repaired(value):
    check = numeric_check(value)
    assert review_checks([check]) == ([check], [])
    assert compile_check(check).issue is not None


@pytest.mark.parametrize('source', ['text', 'attribute', 'state'])
def test_numbers_inside_text_or_state_expectations_remain_strings(source):
    check = numeric_check('01')
    check['observation']['source'] = source
    assert review_checks([check]) == ([check], [])


def game_and_checks(*, never_visible=False, category='outcome'):
    html = '''<!doctype html><style>body{margin:0}canvas{width:200px;height:150px}</style>
    <button id="start">Начать</button><section id="play" hidden>
    <canvas width="200" height="150" CANVAS_HIDDEN></canvas><button id="hit">Карточка</button>
    <p id="count">0</p><button id="finish">Завершить</button></section><p id="result" hidden>Победа</p>
    <script>
    const start=document.querySelector('#start'),play=document.querySelector('#play');
    const count=document.querySelector('#count'),result=document.querySelector('#result');
    const ctx=document.querySelector('canvas').getContext('2d');
    ctx.fillStyle='#28a';ctx.fillRect(20,20,40,40);
    start.onclick=()=>{start.hidden=true;play.hidden=false;};
    document.querySelector('#hit').onclick=()=>{count.textContent=String(Number(count.textContent)+1);};
    document.querySelector('#finish').onclick=()=>{play.hidden=true;result.hidden=false;};
    </script>'''.replace('CANVAS_HIDDEN', 'hidden' if never_visible else '')
    start = {'action': 'click', 'selector': '#start', 'x': None, 'y': None}
    control = numeric_check()
    control['steps'].insert(0, deepcopy(start))
    return html, [
        {'id': 'begin', 'category': 'start', 'viewport': 'mobile', 'requirement': 'Начать партию',
         'steps': [start], 'observation': {'source': 'text', 'selector': '#play'},
         'expect': {'operator': 'visible', 'value': None}},
        control,
        {'id': 'finish', 'category': category, 'viewport': 'desktop', 'requirement': 'Показать итог партии',
         'steps': [deepcopy(start), {'action': 'click', 'selector': '#finish', 'x': None, 'y': None}],
         'observation': {'source': 'text', 'selector': '#result'},
         'expect': {'operator': 'visible', 'value': None}},
    ]


@pytest.mark.browser
def test_result_screen_can_hide_a_scene_seen_in_the_same_scenario():
    html, checks = game_and_checks()
    original = deepcopy(checks)
    result = validate(html, checks, artifact_hash=sha256(html))
    assert result['status'] == 'passed', result
    assert all(result['gates'].values()) and checks == original
    final = next(f for f in result['facts'] if f['id'] == 'finish')
    assert final['comparison'] is True and final['status'] == 'passed'
    assert not any(c['visible'] for c in final['surface']['canvases'])
    assert any(c['visible'] for c in final['scene_surface']['canvases'])
    assert final['scene_observed_after_step'] == 0
    assert final['counterfactual']['comparison'] is False
    assert not any(f['code'] == 'canvas_missing' for f in result['findings'])


@pytest.mark.browser
@pytest.mark.parametrize('never_visible,category', [(True, 'outcome'), (False, 'control')])
def test_result_label_does_not_excuse_missing_scene_or_disappearing_control(never_visible, category):
    html, checks = game_and_checks(never_visible=never_visible, category=category)
    result = validate(html, checks, artifact_hash=sha256(html))
    final = next(f for f in result['facts'] if f['id'] == 'finish')
    assert result['status'] == 'failed' and final['status'] == 'failed', result
    assert any(f['code'] == 'canvas_missing' and f.get('check_id') == 'finish' for f in result['findings'])
    if never_visible:
        assert not result['gates']['surface']


@pytest.mark.browser
def test_outcome_only_route_can_expose_scene_in_uncovered_viewports():
    html, checks = game_and_checks()
    result = validate(html, [checks[-1]], artifact_hash=sha256(html))
    assert result['status'] == 'unverified', result  # Other required scenarios are still missing.
    assert all(result['gates'].values())
    assert not any(f['code'] == 'canvas_missing' for f in result['findings'])


@pytest.mark.browser
def test_early_scene_capture_does_not_lock_the_game_into_a_context():
    html, checks = game_and_checks()
    html = html.replace('<section id="play" hidden>', '<section id="play">')
    # The game creates its rendering context only after the user's gesture.
    html = html.replace("const ctx=document.querySelector('canvas').getContext('2d');\n    ctx.fillStyle='#28a';ctx.fillRect(20,20,40,40);", '')
    html = html.replace('start.hidden=true;play.hidden=false;', '''
      const board=document.querySelector('canvas');
      // bitmaprenderer would fail if early inspection had already created 2D.
      const ctx=board.getContext('bitmaprenderer');
      if(!ctx) throw new Error('Inspection created the wrong rendering context');
      start.hidden=true;play.hidden=false;
    ''')
    result = validate(html, checks, artifact_hash=sha256(html))
    assert result['gates']['runtime'], result
    assert not any(f['code'] == 'runtime_or_network' for f in result['findings'])


@pytest.mark.browser
def test_hidden_result_text_is_absent_in_counterfactual_not_a_broken_observer():
    html, checks = game_and_checks()
    checks[-1]['expect'] = {'operator': 'eq', 'value': 'Победа'}
    result = validate(html, checks, artifact_hash=sha256(html))
    final = next(f for f in result['facts'] if f['id'] == 'finish')
    assert result['status'] == 'passed', result
    assert final['counterfactual']['observation_absent']
    assert final['counterfactual']['comparison'] is False


@pytest.mark.browser
def test_hidden_final_text_cannot_excuse_a_failed_intermediate_assertion():
    html, checks = game_and_checks()
    checks[-1]['expect'] = {'operator': 'eq', 'value': 'Победа'}
    checks[-1]['steps'].insert(-1, {'action': 'assert', 'ms': 0,
        'observation': {'source': 'text', 'selector': '#count'},
        'expect': {'operator': 'eq', 'value': '999'}})
    result = validate(html, checks, artifact_hash=sha256(html))
    final = next(f for f in result['facts'] if f['id'] == 'finish')
    assert final['status'] != 'passed'
    assert not final.get('counterfactual', {}).get('observation_absent')


@pytest.mark.browser
def test_post_action_assertion_mismatch_still_measures_counterfactual_final_effect():
    html, checks = game_and_checks()
    control = checks[1]
    control['steps'].append({'action': 'assert', 'ms': 0,
        'observation': deepcopy(control['observation']), 'expect': {'operator': 'eq', 'value': 1}})
    original = deepcopy(checks)
    result = validate(html, checks, artifact_hash=sha256(html))
    fact = next(f for f in result['facts'] if f['id'] == 'count')
    assert result['status'] == 'passed', result
    assert fact['counterfactual']['comparison'] is False
    trace = fact['counterfactual']['trace'][-1]
    assert trace['counterfactual_assertion_failed'] and trace['assertion']['comparison'] is False
    assert checks == original


@pytest.mark.browser
def test_failed_timed_condition_cannot_shift_control_clock_and_claim_causality():
    html, checks = game_and_checks()
    control = checks[1]
    control['steps'].append({'action': 'await_condition', 'ms': 100,
        'observation': deepcopy(control['observation']), 'expect': {'operator': 'eq', 'value': 1}})
    result = validate(html, checks, artifact_hash=sha256(html))
    fact = next(f for f in result['facts'] if f['id'] == 'count')
    assert fact['status'] == 'unverified'
    assert fact['counterfactual']['comparison'] is None


@pytest.mark.browser
def test_counterfactual_assertion_cannot_replace_an_unrelated_always_passing_final_oracle():
    html, checks = game_and_checks()
    control = checks[1]
    control['steps'].append({'action': 'assert', 'ms': 0,
        'observation': deepcopy(control['observation']), 'expect': {'operator': 'eq', 'value': 1}})
    control.update(observation={'source': 'text', 'selector': '#play'},
                   expect={'operator': 'visible', 'value': None})
    result = validate(html, checks, artifact_hash=sha256(html))
    fact = next(f for f in result['facts'] if f['id'] == 'count')
    assert fact['status'] == 'unverified'
    assert fact['counterfactual']['comparison'] is True
    assert any(f['code'] == 'effect_not_causal' for f in result['findings'])


@pytest.mark.parametrize('operator', ['changed', 'unchanged', 'increased', 'decreased'])
def test_generation_schema_excludes_relative_intermediate_assertions(operator):
    from jsonschema import Draft202012Validator

    from generation.schema import CHECK_SCHEMA
    check = numeric_check(1)
    check['steps'].append({'action': 'assert', 'ms': 0,
        'observation': deepcopy(check['observation']), 'expect': {'operator': operator, 'value': None}})
    assert not Draft202012Validator(CHECK_SCHEMA).is_valid(check)
    assert compile_check(check).issue.field == 'steps.expect'


@pytest.mark.browser
@pytest.mark.parametrize('fake_console_error', [False, True])
def test_browser_blocked_autofocus_is_not_game_failure_but_console_errors_remain_hard(fake_console_error):
    html, checks = game_and_checks()
    html = html.replace('<button id="start">', '<button id="start" autofocus>')
    if fake_console_error:
        html += '<script>console.error("Blocked autofocusing on a <button> element in a cross-origin subframe.")</script>'
    result = validate(html, checks, artifact_hash=sha256(html))
    assert any(f['browser_warnings'] == [{'code': 'autofocus_blocked'}] for f in result['facts'])
    assert result['gates']['runtime'] is (not fake_console_error)
    if fake_console_error:
        assert result['status'] == 'failed'
        assert any(f['code'] == 'runtime_or_network' for f in result['findings'])
    else:
        assert result['status'] == 'passed', result
        assert not any(f['code'] == 'runtime_or_network' for f in result['findings'])
