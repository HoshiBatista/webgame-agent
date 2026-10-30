"""Playback evidence is a bounded trusted observation, not a model's audio verdict."""
from copy import deepcopy

import pytest

from generation.artifacts import materialize, sha256
from generation.experience import SOURCE
from generation.helpers import catalog
from generation.providers.fake import fixture_response
from generation.schema import validate_checks
from validation.check_program import compile_check
from validation.checks import TRUSTED_EXPERIENCE_HASHES
from validation.contracts import suite_findings
from validation.service import validate
from validation.syntax import Scripts


def player_check(field='effectsPlayed', value=1):
    return {'id': 'audio', 'category': 'control', 'viewport': 'mobile',
            'requirement': 'Действие запускает звуковой эффект',
            'steps': [{'action': 'tap', 'selector': '#arena', 'x': 150, 'y': 150}],
            'observation': {'source': 'experience', 'field': field},
            'expect': {'operator': 'eq', 'value': value}}


def game(*, sounds=True):
    response = fixture_response(with_assets=True)
    if sounds:
        script = next(f for f in response['files'] if f['path'] == 'game.js')
        script['content'] = script['content'].replace('gameState.hits++;',
            'gameState.hits++;GameForgeExperience.sound("hit");')
    return materialize(response, operation='create', helper_catalog=catalog())


def test_exact_trusted_player_is_first_executable_script_and_is_pinned():
    assert sha256(SOURCE.read_text()) in TRUSTED_EXPERIENCE_HASHES
    scripts = Scripts()
    scripts.feed(game()['html'])
    assert sha256(scripts.scripts[0]['content']) in TRUSTED_EXPERIENCE_HASHES


@pytest.mark.parametrize('field,value', [('effectsPlayed', 1), ('effectsPlayed', '1'), ('musicPlaying', True), ('state', 'running'), ('graphicsReady', 3)])
def test_player_observation_schema_and_compiler_agree(field, value):
    check = player_check(field, value)
    validate_checks([check], require_complete=False)
    assert compile_check(check).issue is None


@pytest.mark.parametrize('field,value', [('unknown', 1), ('inspect', 1), ('__proto__', 1),
                                         ('effectsPlayed', '1px'), ('musicPlaying', 1), ('state', True), ('graphicsReady', True)])
def test_player_field_and_expected_types_are_bounded(field, value):
    assert compile_check(player_check(field, value)).issue is not None


@pytest.mark.parametrize('action', ['assert', 'await_condition'])
def test_graphics_count_diagnostic_identifies_the_nested_type_error_without_reinterpreting_it(action):
    check = player_check()
    check['steps'].append({'action': action, 'ms': 0 if action == 'assert' else 100,
                          'observation': {'source': 'experience', 'field': 'graphicsReady'},
                          'expect': {'operator': 'eq', 'value': True}})
    original = deepcopy(check)
    issue = compile_check(check).issue
    assert issue and issue.field == 'steps.expect' and issue.code == 'invalid_check'
    assert 'graphicsReady' in issue.message and 'количество' in issue.message
    assert check == original


def test_audio_cannot_replace_gameplay_or_outcome_coverage():
    check = player_check()
    desktop = deepcopy(check)
    desktop.update(id='keyboard', viewport='desktop')
    desktop['steps'] = [{'action': 'press', 'key': 'Space'}]
    codes = {f['code'] for f in suite_findings([check, desktop], require_keyboard=True)}
    assert {'missing_mobile_control', 'missing_keyboard_control'} <= codes
    check['category'] = 'outcome'
    assert compile_check(check).issue is not None


@pytest.mark.browser
@pytest.mark.parametrize('sounds', [True, False])
def test_real_effects_are_separate_from_automatic_music(sounds):
    artifact = game(sounds=sounds)
    music = player_check('musicPlaying', True)
    music.update(id='music', category='regression')
    music['steps'].append({'action': 'await_condition', 'ms': 1500,
        'observation': {'source': 'experience', 'field': 'state'},
        'expect': {'operator': 'eq', 'value': 'running'}})
    checks = artifact['checks'] + [player_check(), music]
    result = validate(artifact['html'], checks, artifact_hash=artifact['artifact_hash'])
    audio = next(f for f in result['facts'] if f['id'] == 'audio')
    assert next(f for f in result['facts'] if f['id'] == 'music')['status'] == 'passed', result
    assert audio['after'] == (1 if sounds else 0), result
    if sounds:
        assert result['status'] == 'passed', result
        assert audio['counterfactual']['comparison'] is False
    else:
        assert audio['status'] == 'failed' and result['status'] == 'failed'


@pytest.mark.browser
def test_untrusted_game_inspector_is_never_called():
    response = fixture_response()
    script = next(f for f in response['files'] if f['path'] == 'game.js')
    script['content'] += '''
    Object.defineProperty(window, 'GameForgeExperience', {value:Object.freeze({
      inspect(){ throw new Error('UNTRUSTED INSPECTOR CALLED'); }
    }), writable:false, configurable:false});
    '''
    artifact = materialize(response, operation='create')
    result = validate(artifact['html'], artifact['checks'] + [player_check()], artifact_hash=artifact['artifact_hash'])
    audio = next(f for f in result['facts'] if f['id'] == 'audio')
    assert audio['status'] == 'unverified', result
    assert any(f['code'] == 'invalid_check' and f.get('check_id') == 'audio' for f in result['findings'])
    assert not any(f['code'] in {'runtime_or_network', 'browser_error'} for f in result['findings'])
