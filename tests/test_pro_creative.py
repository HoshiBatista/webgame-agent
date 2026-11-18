from copy import deepcopy

import pytest

from generation.errors import ContractError
from generation.planning import schema as plan_schema
from generation.pro_creative import validate_brief
from generation.pro_parallel import assemble, validate_reply
from generation.prompts import system_prompt
from tests.test_pro_parallel import replies, request
from tests.test_pro_partition import split_replies, split_request


def creative_brief():
    return {'scope': 'faithful', 'reason': 'Сохраняем точные простые правила игрока.',
            'signature': 'Три попадания в цель дают настоящую победу.',
            'arc': ['Первое попадание объясняет игру, третье завершает раунд.'],
            'motion': [{'event': 'Попадание', 'choreography': 'Короткая вспышка и плавное затухание кольца.',
                        'duration_ms': 200}],
            'music': {'structure': 'Две короткие фразы в до мажоре.',
                      'voices': 'Мелодия и тихий бас отвечают друг другу.',
                      'development': 'Вторая фраза варьирует ритм, затем возвращается к первой.'}}


def creative_request(role):
    req = split_request(role) if role in {'scene', 'mechanics'} else request(role)
    req['pro_parallel'] = 3
    req['game_plan']['experience_direction'] = creative_brief()
    return req


def test_only_new_experiment_requires_a_concrete_creative_brief():
    req = creative_request('gameplay')
    props = plan_schema(req)['properties']['plan']['anyOf'][0]
    assert 'experience_direction' in props['required']
    validate_brief(req['game_plan'])
    for version in [None, 1, 2]:
        old = {**req, 'pro_parallel': version}
        assert 'experience_direction' not in plan_schema(old)['properties']['plan']['anyOf'][0]['properties']
        assert 'AUTHOR A RICH' not in system_prompt({**old, 'operation': 'plan'})


@pytest.mark.parametrize('role', ['gameplay', 'scene', 'mechanics', 'graphics', 'audio'])
def test_v3_roles_keep_source_ownership_and_receive_the_shared_brief(role):
    req = creative_request(role)
    reply = split_replies()[role] if role in {'scene', 'mechanics'} else replies()[role]
    validate_reply(reply, req)
    prompt = system_prompt(req)
    assert 'RICH EXPERIMENTAL' in prompt
    if role in {'gameplay', 'scene'}:
        assert '<=22,000 characters' in prompt and '<=24,000 characters' not in prompt
        assert 'CHECK ROUTES' in prompt and 'assets=null' in prompt
    if role == 'audio':
        assert '<=6 KiB total' not in prompt
    legacy = system_prompt({**req, 'pro_parallel': 2})
    assert 'RICH EXPERIMENTAL' not in legacy


def test_silence_and_static_brief_do_not_force_extra_media_or_motion():
    req = creative_request('audio')
    plan = req['game_plan']
    plan['resource_contract'].update(sounds=[], silence_reason='Пользователь попросил без звука.')
    with pytest.raises(ContractError, match='тишину'):
        validate_brief(plan)
    plan['experience_direction'].update(music=None, motion=[])
    validate_brief(plan)
    validate_reply({'operation': 'pro_audio', 'sounds': [], 'instruments': [], 'music': None,
                    'silence_reason': plan['resource_contract']['silence_reason']}, req)
    plan['resource_contract']['silence_reason'] = ''
    with pytest.raises(ContractError):
        validate_brief(plan)


def test_invalid_or_excessive_brief_is_rejected():
    req = creative_request('gameplay')
    for mutate in [lambda b: b.update(scope='maximal'), lambda b: b.update(arc=[]),
                   lambda b: b.update(motion=b['motion'] * 5), lambda b: b.update(music={})]:
        plan = deepcopy(req['game_plan'])
        mutate(plan['experience_direction'])
        with pytest.raises(ContractError):
            validate_brief(plan)


def test_richer_score_fits_new_branch_and_combined_budget_without_changing_v2():
    req, values = creative_request('audio'), replies()
    audio = values['audio']
    note = audio['music']['notes'][0]
    audio['music'].update(beats=64, notes=[{**note, 'beat': i * .5, 'duration': .25} for i in range(84)])
    validate_reply(audio, req)
    with pytest.raises(ContractError, match='6144'):
        validate_reply(audio, {**req, 'pro_parallel': 2})
    assembled = assemble(values, req['game_plan'], 3)
    assert assembled['assets']['music'] == audio['music']


def test_check_repair_keeps_its_old_permissions_and_extends_only_total_time():
    req = creative_request('gameplay')
    req.pop('pro_parallel_branch')
    req['operation'] = 'check_repair'
    from generation.pro_creative import check_prompt

    legacy = system_prompt({**req, 'pro_parallel': 2})
    assert system_prompt(req) == check_prompt(legacy, req)
    assert 'each wait <=10000ms' in system_prompt(req)
    assert 'protected checks remain byte-for-byte unchanged' in system_prompt(req)


def test_creative_wait_budget_preserves_protected_checks_source_and_goals():
    from generation.pro_creative import prepare_checks
    from tests.test_lite_wait_budget import long_check
    from validation.check_program import compile_check

    req = creative_request('gameplay')
    check = long_check()
    protected = {**check, 'id': 'kept', 'steps': [{'action': 'press', 'key': 'Enter'}]}
    req.update(operation='check_repair', check_repair={'protected_checks': [protected]})
    reply = {'checks': [check, protected], 'files': [{'path': 'game.js', 'content': 'unchanged'}]}
    before = deepcopy(reply)
    result, ids = prepare_checks(reply, req)
    assert reply == before and ids == ['end']
    assert result['files'] == reply['files'] and result['checks'][1] == protected
    assert result['checks'][0] == {**check, 'wait_budget_ms': 30000}
    program = compile_check(result['checks'][0])
    assert program.issue is None
    assert program.without_last_input()['expect'] == check['expect']
    assert program.without_last_input()['wait_budget_ms'] == 30000
    for overrides in ({'pro_parallel': 2}, {'pro_parallel': None}, {'generation_profile': 'compact'},
                      {'operation': 'pro_audio'}, {'patch_repair': True}, {'response_completion': True}):
        assert prepare_checks(reply, {**req, **overrides}) == (reply, [])
    for invalid in [True, 30000.0, 10000, '30000', None]:
        with pytest.raises(ContractError):
            prepare_checks({'checks': [{**check, 'wait_budget_ms': invalid}]}, req)


def test_only_v3_schema_accepts_long_scenarios_and_keeps_action_limits():
    from jsonschema import Draft202012Validator

    from generation.pro_creative import check_prompt
    from generation.schema import response_schema
    from tests.test_lite_wait_budget import long_check

    req = creative_request('gameplay')
    check = {**long_check(), 'wait_budget_ms': 30000}
    req.pop('pro_parallel_branch')
    req['check_repair'] = {'max_checks': 12}
    for operation in ['create', 'edit', 'repair', 'check_repair']:
        req['operation'] = operation
        current = response_schema(req)['properties']['checks']['items']
        legacy = response_schema({**req, 'pro_parallel': 2})['properties']['checks']['items']
        assert Draft202012Validator(current).is_valid(check)
        assert not Draft202012Validator(legacy).is_valid(check)
    text = 'Total waits<=10000ms; wait: 10000ms; 10000ms total waits; total waits remain <=10000ms'
    actual = check_prompt(text, req)
    assert 'Total waits<=30000ms; wait: 10000ms; 30000ms total waits; total waits remain <=30000ms' in actual


def test_new_budget_is_recorded_without_rewriting_provider_receipt(monkeypatch):
    from generation import service

    raw = replies()['gameplay']
    original = deepcopy(raw)
    monkeypatch.setattr(service.codex_api, 'generate', lambda *a, **kw: {
        'response': raw, 'usage': {'output_tokens': 123}})
    result = service.generate(creative_request('gameplay'), on_event=lambda _: None, is_cancelled=lambda: False)
    assert result['raw_response'] == original and raw == original
    assert result['usage'] == {'output_tokens': 123}
    assert all(c['wait_budget_ms'] == 30000 for c in result['response']['checks'])
    assert result['provider_metadata']['pro_creative_wait_budget']['check_ids'] == [
        c['id'] for c in original['checks']]


@pytest.mark.parametrize('operation', ['create', 'edit', 'repair', 'check_repair'])
def test_v3_output_schema_requires_every_declared_property_without_changing_old_checks(operation):
    from jsonschema import Draft202012Validator

    from generation.schema import response_schema
    from tests.test_lite_wait_budget import long_check

    old = long_check()
    timed = {**old, 'wait_budget_ms': 30000}
    req = creative_request('gameplay')
    req.pop('pro_parallel_branch')
    req.update(operation=operation, checks=[old, timed], check_repair={'protected_checks': [old]})
    schema = response_schema(req)

    def inspect(node):
        if isinstance(node, dict):
            if 'properties' in node:
                assert set(node['required']) == set(node['properties'])
                assert node['additionalProperties'] is False
            for value in node.values():
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)

    inspect(schema)
    validator = Draft202012Validator(schema['properties']['checks']['items'])
    assert validator.is_valid(old) and validator.is_valid(timed)
    assert not validator.is_valid({**old, 'wait_budget_ms': 10000})
