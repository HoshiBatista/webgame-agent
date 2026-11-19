from copy import deepcopy

import pytest

from generation.errors import ContractError
from generation.pro_parallel import assemble, messages, schema, validate_reply
from generation.pro_staged import source_context
from generation.requirements import policy_snapshot
from tests.test_pro_parallel import replies, request

# Same authored timbre, effect and pitches as the fixture's canonical recipe.
SCORE = """voice soft sine 10 80 1800
fx hit soft 440 660 100 12
loop 90 8
note soft 0 60 8 4
note soft 16 64 8 4
note soft 32 67 8 4
note soft 48 64 8 4"""


def test_compact_score_preserves_authored_sound_and_frozen_source_hash():
    assert 'pro_audio.py' in policy_snapshot()['source_hashes']
    req = {**request('audio'), 'pro_parallel': 5}
    packet = {'score': SCORE}
    validate_reply(packet, req)
    original = replies()
    compact = {**original, 'audio': packet}
    context = source_context(compact, req['game_plan'], 5)
    assert context['assets'] == source_context(original, req['game_plan'], 4)['assets']
    checks = {'source_hash': context['source_hash'], 'checks': []}
    assert assemble({**compact, 'checks': checks}, req['game_plan'], 5)['assets'] == context['assets']
    assert compact['audio'] == packet
    with pytest.raises(ContractError, match='Исходники'):
        changed = {'score': SCORE.replace('48 64', '48 65')}
        assemble({**compact, 'audio': changed, 'checks': checks}, req['game_plan'], 5)
    old = {**req, 'pro_parallel': 4}
    assert schema(old)['properties'].keys() == original['audio'].keys()
    validate_reply(original['audio'], old)
    with pytest.raises(ContractError):
        validate_reply(packet, old)
    with pytest.raises(ContractError):
        validate_reply(original['audio'], req)


@pytest.mark.parametrize('old,new', [
    ('voice soft', 'voice another'), ('fx hit', 'fx other'), ('0 60 8 4', '0 33 8 4'),
    ('48 64 8 4', '60 64 8 4'), ('sine 10', 'sine 2'), ('sine 10', 'sine NaN'),
    ('loop 90 8', 'loop 90 8\nloop 90 8'), ('fx hit', '   fx hit'), ('loop 90 8', 'rest 250'),
    ('fx hit soft', 'fx hit  soft'), ('\nloop', '\nfx hit soft 160 170 50 12\nloop'),
])
def test_malformed_scores_or_references_do_not_create_assets(old, new):
    with pytest.raises(ContractError):
        validate_reply({'score': SCORE.replace(old, new)}, {**request('audio'), 'pro_parallel': 5})


def test_explicit_silence_and_model_context_follow_the_frozen_contract():
    req = {**request('audio'), 'pro_parallel': 5}
    req['game_plan'] = {**deepcopy(req['game_plan']), 'summary': 'Ночные маяки',
                        'experience_direction': {'music': {'structure': 'pulse and return'}},
                        'gameplay_partition': {'details': 'irrelevant gameplay internals'}}
    assert 'pulse and return' in messages(req)[1]['content']
    assert 'irrelevant gameplay internals' not in messages(req)[1]['content']
    with pytest.raises(ContractError):
        validate_reply({'score': 'silence'}, req)
    req['game_plan']['resource_contract'].update(silence_reason='Игрок попросил полную тишину.', sounds=[])
    validate_reply({'score': 'silence'}, req)
    with pytest.raises(ContractError):
        validate_reply({'score': SCORE}, req)
    result = {**replies(), 'audio': {'score': 'silence'}}
    assets = source_context(result, req['game_plan'], 5)['assets']
    assert not assets['sounds'] and not assets['instruments'] and assets['music'] is None
    assert assets['silence_reason'] == req['game_plan']['resource_contract']['silence_reason']
