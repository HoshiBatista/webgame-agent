import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from generation import music
from generation.artifacts import apply_patches, materialize
from generation.errors import ContractError
from generation.experience import PATH, RECIPE, read
from generation.helpers import catalog
from generation.providers.fake import fixture_response


def music_response(request):
    return {'operation': 'music', 'base_revision': request['base_revision'],
            'artifact_hash': request['artifact_hash'],
            'instruments': [{'id': 'bell', 'wave': 'sine', 'attack': .01, 'release': .1, 'brightness': 2000}],
            'music': {'bpm': 90, 'beats': 8, 'notes': [
                {'instrument': 'bell', 'beat': i, 'note': 60 + i, 'duration': .5, 'gain': .05}
                for i in range(4)]}, 'silence_reason': ''}


def base_and_request():
    response = fixture_response(with_assets=True)
    response.pop('assets')
    base = SimpleNamespace(id='music-base', checks_review_required=False,
                           **materialize(response, operation='create'))
    return base, {'base_revision': str(base.id), 'artifact_hash': base.artifact_hash, 'helper_catalog': catalog()}


def test_music_is_bundled_with_pinned_player_and_preserves_gameplay():
    base, request = base_and_request()
    original = deepcopy(base.files)
    artifact = music.materialize(music_response(request), request, base)
    assert base.files == original
    assert artifact['checks'] == base.checks
    assert all(artifact['files'][p] == c for p, c in original.items() if p != 'index.html')
    assert PATH in artifact['files'] and 'GameForgeExperience' in artifact['html']
    assert read(artifact['files'])['kind'] == 'music'
    assert artifact['artifact_hash'] != base.artifact_hash
    with pytest.raises(ContractError, match='Ресурсы'):
        apply_patches(artifact['files'], [{'path': RECIPE}])


@pytest.mark.parametrize('defect', ['instrument', 'duration', 'code', 'binding'])
def test_invalid_music_cannot_change_the_game(defect):
    base, request = base_and_request()
    reply = music_response(request)
    if defect == 'instrument':
        reply['music']['notes'][0]['instrument'] = 'missing'
    elif defect == 'duration':
        reply['music']['notes'][0]['beat'] = 8
    elif defect == 'code':
        reply['files'] = [{'path': 'game.js', 'content': 'changed'}]
    else:
        reply['artifact_hash'] = 'f' * 64
    with pytest.raises(ContractError):
        music.materialize(reply, request, base)
    assert RECIPE not in base.files


def test_silence_request_and_score_prompt_have_no_code_edit_surface():
    base, request = base_and_request()
    reply = {**music_response(request), 'music': None, 'instruments': [], 'silence_reason': 'Игрок просит тишину.'}
    result = music.materialize(reply, request, base)
    assert read(result['files'])['music'] is None
    context = json.loads(music.messages({**request, 'files': base.files})[-1]['content'])
    assert 'files' not in context
