from pathlib import Path

import pytest

from generation.artifacts import sha256
from validation.service import validate

FIXTURES = Path(__file__).parent / 'fixtures/game_validation'


def tap(x, y):
    return {'action': 'tap_fraction', 'selector': 'canvas', 'x': x, 'y': y}


def click(selector):
    return {'action': 'click', 'selector': selector}


def scenario(ident, category, steps, path, value, operator='eq', viewport='mobile'):
    return {'id': ident, 'category': category, 'requirement': 'Независимое условие ' + ident,
            'viewport': viewport, 'steps': steps, 'observation': {'source': 'state', 'path': path},
            'expect': {'operator': operator, 'value': value}}


def run_game(name, checks, edits=()):
    html = (FIXTURES / (name + '.html')).read_text()
    for before, after in edits:
        assert before in html
        html = html.replace(before, after)
    return validate(html, checks, artifact_hash=sha256(html))


def grid_checks():
    def cell(i):
        return tap((i % 3 + .5) / 3, (i // 3 + .5) / 3)
    return [scenario('start', 'start', [], 'grid.phase', 'ready'),
            scenario('move', 'control', [cell(0)], 'grid.turn', 'O'),
            scenario('occupied', 'regression', [cell(0), cell(0)], 'grid.turn', 'O'),
            scenario('win', 'outcome', [cell(i) for i in [0, 3, 1, 4, 2]], 'grid.phase', 'win'),
            scenario('draw', 'outcome', [cell(i) for i in [0, 1, 2, 4, 3, 5, 7, 6, 8]], 'grid.phase', 'draw'),
            scenario('reset', 'regression', [cell(0), click('#reset')], 'grid.phase', 'ready', viewport='desktop')]


@pytest.mark.browser
def test_grid_real_win_draw_occupied_and_reset():
    report = run_game('grid', grid_checks())
    assert report['status'] == 'passed', report['findings']


@pytest.mark.browser
@pytest.mark.parametrize('wrong_winner', [False, True])
def test_grid_actual_winner_is_checked_separately_from_a_win_flag(wrong_winner):
    def cell(i):
        return tap((i % 3 + .5) / 3, (i // 3 + .5) / 3)

    checks = grid_checks()[:2] + [
        scenario('x-wins', 'outcome', [cell(i) for i in [0, 3, 1, 4, 2]], 'grid.winner', 'X'),
        scenario('o-wins', 'outcome', [cell(i) for i in [0, 3, 1, 4, 8, 5]], 'grid.winner', 'O'),
    ]
    mutation = [('grid.winner=grid.turn;', "grid.winner=grid.turn==='X'?'O':'X';")] if wrong_winner else []
    report = run_game('grid', checks, mutation)
    assert report['status'] == ('failed' if wrong_winner else 'passed'), report['findings']
    assert all(f['status'] == ('failed' if wrong_winner else 'passed')
               for f in report['facts'] if f['category'] == 'outcome')


def memory_checks():
    start = click('#start')
    a, b, c, d = [tap(.25, .25), tap(.75, .25), tap(.25, .75), tap(.75, .75)]
    return [scenario('start', 'start', [start], 'memory.active', True),
            scenario('mismatch', 'control', [start, a, b, {'action': 'wait', 'ms': 180}], 'memory.face.0', False),
            scenario('hit', 'control', [start, c], 'memory.face.2', True),
            scenario('win', 'outcome', [start, a, c, b, d], 'memory.matches.length', 4),
            scenario('reset', 'regression', [start, a, click('#reset')], 'memory.face.0', False, viewport='desktop')]


@pytest.mark.browser
@pytest.mark.parametrize('mutation', ['none', 'stale_start', 'face_down', 'hit_test'])
def test_memory_real_input_distinguishes_broken_programs(mutation):
    edits = {
        'none': [],
        'stale_start': [('/* START_REPLACEMENT */', "document.querySelector('#overlay').innerHTML='<button id=start>Start</button>'; ")],
        'face_down': [('memory.face[a]=false;memory.face[b]=false;', 'memory.face[a]=true;memory.face[b]=true;')],
        'hit_test': [('Math.floor(x*2)+Math.floor(y*2)*2', 'Math.floor(x*2)')],
    }
    report = run_game('memory', memory_checks(), edits[mutation])
    if mutation == 'none':
        assert report['status'] == 'passed', report['findings']
    else:
        assert report['status'] != 'passed'
        ident = {'stale_start': 'start', 'face_down': 'mismatch', 'hit_test': 'hit'}[mutation]
        assert next(f for f in report['facts'] if f['id'] == ident)['status'] == 'failed'


def snake_checks():
    start = click('#start')
    return [scenario('start', 'start', [start], 'snake.active', True),
            scenario('turn', 'control', [start, click('#up'), {'action': 'wait', 'ms': 250},
                {'action': 'checkpoint'}, click('#left'), {'action': 'wait', 'ms': 250}],
                'snake.x', None, operator='decreased'),
            {**scenario('loss', 'outcome', [start, {'action': 'wait', 'ms': 1300}], 'snake.active', False),
             'observation':{'source':'text','selector':'#status'},'expect':{'operator':'eq','value':'lost'}},
            scenario('pause', 'regression', [start, click('#pause'), {'action':'checkpoint'}, {'action': 'wait', 'ms': 500}],
                'snake.x', None, operator='unchanged', viewport='desktop'),
            scenario('weak-motion', 'regression', [start, {'action': 'wait', 'ms': 250}],
                'snake.x', None, operator='increased')]


@pytest.mark.browser
@pytest.mark.parametrize('mutation', ['none', 'ignored_turn', 'broken_pause'])
def test_snake_turn_and_pause_require_real_motion_effect(mutation):
    edits = {
        'none': [],
        'ignored_turn': [('snake.dx=0;snake.dy=-1;', ''), ('snake.dx=-1;snake.dy=0;', '')],
        'broken_pause': [('!snake.active||snake.paused', '!snake.active')],
    }
    report = run_game('snake', snake_checks(), edits[mutation])
    if mutation == 'none':
        assert report['status'] == 'passed', report['findings']
    else:
        if mutation == 'ignored_turn':
            assert next(f for f in report['facts'] if f['id'] == 'weak-motion')['status'] == 'passed'
        ident = 'turn' if mutation == 'ignored_turn' else 'pause'
        assert next(f for f in report['facts'] if f['id'] == ident)['status'] == 'failed'
