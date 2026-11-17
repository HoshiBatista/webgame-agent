from copy import deepcopy

import pytest

from generation.artifacts import materialize
from generation.errors import ContractError
from generation.planning import schema as plan_schema
from generation.pro_parallel import assemble, branches, validate_reply
from generation.pro_partition import interface_hash, validate_partition
from generation.prompts import system_prompt
from generation.service import generate
from tests.test_pro_parallel import replies, request


def partition():
    return {'mode': 'split', 'reason': 'Правила счёта отделены от сцены и управления.',
            'interface': {'coordinates': 'Цель находится в логическом поле 300 на 300.',
                'state_fields': [{'name': 'score', 'shape': 'integer from 0 to 3'},
                                 {'name': 'won', 'shape': 'boolean, true at score 3'}],
                'commands': [{'name': 'hit', 'payload': 'null', 'effect': 'Увеличить счёт до трёх.'},
                             {'name': 'restart', 'payload': 'null', 'effect': 'Обнулить счёт и победу.'}],
                'events': [{'name': 'hit', 'meaning': 'Засчитано настоящее попадание.'}]}}


def split_request(role):
    req = request(role)
    req.update(pro_parallel=2, operation='create' if role == 'scene' else 'pro_' + role)
    req['game_plan']['gameplay_partition'] = partition()
    req['mechanics_interface_hash'] = interface_hash(req['game_plan'])
    return req


def split_replies():
    values = replies()
    values['scene'] = values.pop('gameplay')
    html = next(f for f in values['scene']['files'] if f['path'] == 'index.html')
    html['content'] = html['content'].replace('<script src="game.js">',
        '<script src="mechanics.js"></script><script src="game.js">')
    values['mechanics'] = {'operation': 'pro_mechanics',
        'interface_hash': interface_hash(split_request('scene')['game_plan']),
        'content': '''window.GameForgeMechanics = function(seed) {
  let score = 0;
  return {snapshot: () => ({score, won: score === 3}), step: dt => [],
    dispatch: (command, payload) => { if (command === 'restart') score = 0;
      if (command === 'hit' && score < 3) { score++; return [{type:'hit', data:null}]; }
      return []; }};
};'''}
    return values


@pytest.mark.parametrize('mode', ['single', 'split'])
def test_planner_choice_changes_only_experimental_schema_and_branch_graph(mode):
    part = partition() if mode == 'split' else {'mode': mode, 'reason': 'Короткая связанная игра.', 'interface': None}
    validate_partition(part)
    req = split_request('scene')
    req['game_plan']['gameplay_partition'] = part
    assert branches(req['game_plan'], 2) == (('mechanics', 'scene', 'graphics', 'audio') if mode == 'split'
                                             else ('gameplay', 'graphics', 'audio'))
    assert branches(req['game_plan'], 1) == ('gameplay', 'graphics', 'audio')
    assert 'gameplay_partition' in plan_schema(req)['properties']['plan']['anyOf'][0]['properties']
    assert 'window.GameForgeMechanics(seed)' in system_prompt({**req, 'operation': 'plan'})
    for version in [None, 1]:
        old = {**req, 'pro_parallel': version}
        assert 'gameplay_partition' not in plan_schema(old)['properties']['plan']['anyOf'][0]['properties']
        assert 'window.GameForgeMechanics(seed)' not in system_prompt({**old, 'operation': 'plan'})


@pytest.mark.parametrize('role', ['scene', 'mechanics'])
def test_real_service_contract_validates_disjoint_source_authors(role, monkeypatch):
    req, reply = split_request(role), split_replies()[role]
    validate_reply(reply, req)
    monkeypatch.setattr('generation.providers.codex_api.generate', lambda *a, **kw: {'response': reply, 'usage': {}})
    result = generate(req, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result['response'] == result['raw_response'] == reply
    assert 'window.GameForgeMechanics' in system_prompt(req)


def test_split_assembly_preserves_every_source_and_check_without_an_integrator():
    values = split_replies()
    original = deepcopy(values)
    req = split_request('scene')
    response = assemble(values, req['game_plan'], 2)
    assert values == original and response['checks'] == original['scene']['checks']
    assert response['files'][:-1] == original['scene']['files']
    assert response['files'][-1] == {'path': 'mechanics.js', 'content': original['mechanics']['content']}
    artifact = materialize(response, operation='create', generation_strategy='pro')
    assert artifact['files']['mechanics.js'] == original['mechanics']['content']
    assert artifact['html'].index('window.GameForgeMechanics') < artifact['html'].index('getContext')


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(mode='single'),
    lambda p: p.update(interface=None),
    lambda p: p['interface']['commands'].append(deepcopy(p['interface']['commands'][0])),
    lambda p: p['interface']['state_fields'][0].update(name='constructor'),
])
def test_invalid_or_ambiguous_contract_is_rejected_before_fanout(mutate):
    part = partition()
    mutate(part)
    with pytest.raises(ContractError):
        validate_partition(part)


@pytest.mark.parametrize('role,mutate', [
    ('mechanics', lambda r: r.update(interface_hash='0' * 64)),
    ('mechanics', lambda r: r.update(content='// TODO')),
    ('mechanics', lambda r: r.update(content='/* ' + 'я' * 7000 + ' */x=1;')),
    ('scene', lambda r: r['files'].append({'path': 'mechanics.js', 'content': 'window.GameForgeMechanics=()=>null;'})),
    ('scene', lambda r: r['files'][0].update(content=r['files'][0]['content'].replace('src="mechanics.js"', 'async src="mechanics.js"'))),
    ('scene', lambda r: r['files'][0].update(content=r['files'][0]['content'].replace('<script src="mechanics.js"></script>', ''))),
])
def test_contract_identity_file_ownership_and_script_order_are_enforced(role, mutate):
    response = split_replies()[role]
    mutate(response)
    with pytest.raises(ContractError):
        validate_reply(response, split_request(role))
