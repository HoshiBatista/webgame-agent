from copy import deepcopy

import pytest

from generation.errors import ContractError
from generation.experience import validate
from generation.pro_parallel import assemble, messages, schema, validate_contract, validate_reply
from generation.prompts import build_messages, system_prompt
from generation.providers.fake import fixture_assets, fixture_response
from generation.service import generate


def contract():
    return {'graphics': [{'id': 'target', 'purpose': 'Крупная цель для попадания', 'width': 100, 'height': 100}],
            'sounds': [{'id': 'hit', 'event': 'Настоящее попадание в цель'}],
            'audience_adaptations': fixture_assets()['audience_adaptations'], 'silence_reason': ''}


def request(role):
    return {'pro_parallel': 1, 'pro_parallel_branch': role, 'provider': 'codex_api', 'model': 'gpt-6-sol',
            'generation_strategy': 'pro', 'generation_profile': 'full',
            'operation': 'create' if role == 'gameplay' else 'pro_' + role,
            'game_plan': {'resource_contract': contract()}, 'helper_catalog': {'gf-experience-v1.js': 'test'}}


def replies():
    recipe = fixture_assets()
    gameplay = fixture_response(with_assets=True)
    gameplay['assets'] = None
    return {'gameplay': gameplay,
            'graphics': {'operation': 'pro_graphics', 'graphics': recipe['graphics']},
            'audio': {'operation': 'pro_audio', **{k: recipe[k] for k in ('instruments', 'sounds', 'music', 'silence_reason')}}}


@pytest.mark.parametrize('role', ['gameplay', 'graphics', 'audio'])
def test_roles_obey_disjoint_contracts_and_preserve_raw_receipt(role, monkeypatch):
    reply = replies()[role]
    validate_reply(reply, request(role))
    monkeypatch.setattr('generation.providers.codex_api.generate', lambda *a, **kw: {'response': reply, 'usage': {}})
    result = generate(request(role), on_event=lambda _: None, is_cancelled=lambda: False)
    assert result['response'] == result['raw_response'] == reply
    if role != 'gameplay':
        assert 'files' not in schema(request(role))['properties']
        assert build_messages(request(role)) == messages(request(role))
    else:
        assert schema(request(role))['properties']['assets'] == {'type': 'null'}
        assert 'Return assets=null' in system_prompt(request(role))
        assert 'Create requires non-null assets' not in system_prompt(request(role))


def test_assembly_preserves_code_checks_and_each_authors_resource_bytes():
    values = replies()
    original = deepcopy(values)
    result = assemble(values, {'resource_contract': contract()})
    validate(result['assets'])
    assert values == original
    assert {k: v for k, v in result.items() if k != 'assets'} == {
        k: v for k, v in original['gameplay'].items() if k != 'assets'}
    assert result['assets'] == fixture_assets()


@pytest.mark.parametrize('role,change', [
    ('graphics', lambda r: r['graphics'][0].update(id='invented')),
    ('graphics', lambda r: r['graphics'].append(deepcopy(r['graphics'][0]))),
    ('graphics', lambda r: r['graphics'][0].update(svg=r['graphics'][0]['svg'].replace('100 100', '120 100'))),
    ('graphics', lambda r: r['graphics'][0].update(svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><script/></svg>')),
    ('audio', lambda r: r['sounds'][0].update(instrument='missing')),
    ('audio', lambda r: r['music']['notes'][0].update(beat=8)),
    ('audio', lambda r: r.update(silence_reason='Не хотелось писать музыку')),
    ('audio', lambda r: r.update(music=None)),
    ('gameplay', lambda r: r.update(assets=fixture_assets())),
])
def test_no_silent_resource_renaming_unsafe_svg_or_audio_drift(role, change):
    value = replies()[role]
    change(value)
    with pytest.raises(ContractError):
        validate_reply(value, request(role))


def test_explicit_silence_and_small_immutable_contract():
    req = request('audio')
    req['game_plan']['resource_contract'].update(sounds=[], silence_reason='Игрок попросил игру без звука.')
    value = {'operation': 'pro_audio', 'sounds': [], 'instruments': [], 'music': None,
             'silence_reason': req['game_plan']['resource_contract']['silence_reason']}
    validate_contract(req['game_plan']['resource_contract'])
    validate_reply(value, req)
    bad = contract()
    bad['sounds'] = []
    with pytest.raises(ContractError):
        validate_contract(bad)
