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
