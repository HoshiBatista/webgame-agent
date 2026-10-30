import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from generation import check_repair, lite, lite_baseline, patch_repair
from generation.artifacts import apply_patches, materialize, sha256
from generation.errors import ContractError
from generation.helpers import catalog
from generation.prompts import build_messages, system_prompt
from generation.providers.fake import fixture_response
from generation.providers.fake import generate as fake_generate
from generation.requirements import coverage
from generation.schema import response_schema, validate_checks, validate_response


def request_for(operation='plan', **overrides):
    return {'provider': 'relay', 'model': 'qwen38', 'generation_profile': 'full',
            'generation_strategy': 'lite', 'lite_policy': 1, 'operation': operation,
            'plan_provenance': 1, 'prompt': 'Собери три звезды', 'game_request': 'Собери три звезды',
            'helper_catalog': catalog(), **overrides}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


PRO_BASELINES = json.loads((Path(__file__).parent / 'fixtures/pro-generation-before-lite.json').read_text())


@pytest.mark.parametrize('baseline', PRO_BASELINES,
                         ids=lambda b: '-'.join(b['request'][k] for k in ['provider', 'generation_profile', 'operation']))
def test_pro_messages_and_schemas_are_byte_identical_to_before_fix(baseline):
    request = baseline['request']
    for version in [None, 1]:
        candidate = {**request, **({'lite_policy': version} if version else {})}
        assert digest(build_messages(candidate)) == baseline['messages_sha256']
        assert digest(response_schema(candidate)) == baseline['schema_sha256']


@pytest.mark.parametrize('operation', ['create', 'edit', 'repair', 'check_repair'])
def test_recovered_lite_core_is_exactly_the_pre_planning_version(operation):
    provenance = json.loads((Path(__file__).parent / 'fixtures/lite-baseline-provenance.json').read_text())
    base = lite_baseline.system_prompt({'operation': operation})
    assert hashlib.sha256(base.encode()).hexdigest() == provenance['prompt_sha256'][operation]
    assert system_prompt(request_for(operation)).startswith(base)


def test_saved_lite_plan_receipts_keep_original_schema():
    request = request_for()
    previous = {k: v for k, v in request.items() if k != 'lite_policy'}
    assert response_schema(request) == response_schema(previous)
    assert system_prompt(request) == system_prompt(previous)
    response = fake_generate(previous, on_event=lambda _: None, is_cancelled=lambda: False)['response']
    validate_response(response, operation='plan', schema=response_schema(request))


def test_lite_module_repair_keeps_complete_source_for_layout_patches():
    from generation.artifacts import sha256

    files = {'index.html': '<canvas id="board"></canvas>',
             'game.js': 'window.state = {score: 0};', 'styles.css': 'canvas {width: 900px}'}
    request = request_for('repair', files=files, checks=fixture_response()['checks'],
                          module_repair={'files': {'game.js': sha256(files['game.js'])}})
    current = json.loads(build_messages(request)[1]['content'])
    assert current['files'] == files
    assert current['file_hashes'] == {p: sha256(s) for p, s in files.items()}
    assert current['checks'] == request['checks']
    # Old receipts and Pro retain the previously issued, narrowed contract.
    for previous in [{k: v for k, v in request.items() if k != 'lite_policy'},
                     {**request, 'provider': 'codex_api', 'generation_strategy': 'pro'}]:
        context = json.loads(build_messages(previous)[1]['content'])
        assert context['files'] == {'game.js': files['game.js']}
        assert context['checks'] == []


def test_direct_lite_has_preferences_without_instructions_to_fill_a_plan():
    request = request_for('create', preferences=['Крупные кнопки'],
                          requirement_manifest={'requirements': [], 'require_keyboard': True})
    system, user = build_messages(request)
    assert 'request_reference' not in system['content'] and 'origin=' not in system['content']
    assert 'current request takes priority' in system['content']
    context = json.loads(user['content'])
    assert context['preferences'] == request['preferences']
    assert not {'game_plan', 'requirement_manifest', 'generation_strategy'} & context.keys()
    request['game_plan'] = {'summary': 'Сохранённый замысел'}
    request['requirement_manifest']['requirements'] = [{'id': 'kept', 'requirement': 'Собрать три звезды'}]
    system, user = build_messages(request)
    context = json.loads(user['content'])
    assert context['game_plan'] == request['game_plan']
    assert context['requirement_manifest'] == request['requirement_manifest']
    assert 'Preserve every application-issued requirement ID' in system['content']


def test_create_schema_keeps_existing_check_format_and_separates_gameplay_from_audio():
    requirement = {'id': 'frozen_control', 'category': 'control', 'viewport': 'mobile',
                   'requirement': 'Стрелка вправо передвигает игрока вправо.'}
    request = request_for('create', requirement_manifest={'requirements': [requirement]})
    check = deepcopy(requirement)
    check.update(steps=[{'action': 'press', 'key': 'ArrowRight'}],
                 observation={'source': 'attribute_number', 'selector': '#board', 'attribute': 'data-x'},
                 expect={'operator': 'increased', 'value': 0})
    schema = response_schema(request)
    validator = Draft202012Validator({'$defs': schema['$defs'], **schema['properties']['checks']['items']})
    assert validator.is_valid(check)
    assert validator.is_valid({**check, 'id': 'keyboard_control', 'viewport': 'desktop'})
    assert not validator.is_valid({**check, 'observation': {'source': 'experience', 'field': 'state'}})
    assert validator.is_valid({**check, 'id': 'extra_audio', 'category': 'regression',
                               'observation': {'source': 'experience', 'field': 'musicPlaying'},
                               'expect': {'operator': 'eq', 'value': True}})


def test_full_lite_instructions_have_one_runtime_interface_and_are_smaller():
    request = request_for('create', game_plan={'summary': 'Одна игра'})
    current = system_prompt(request)
    previous = system_prompt({k: v for k, v in request.items() if k != 'lite_policy'})
    assert 'api.experience' not in current and 'Compact uses' not in current
    assert 'window.GameForgeExperience' in current and 'NO injected api variable' in current
    assert len(current) < len(previous) * .8
    repair = system_prompt({**request, 'operation': 'repair'})
    assert 'checks=[] and assets=null' in repair and 'byte-identical' in repair


@pytest.mark.parametrize('operation', ['create', 'edit', 'repair', 'check_repair'])
def test_simple_lite_has_no_media_recipe_or_audio_observations(operation):
    from generation.experience import PATH

    helpers = {k: v for k, v in catalog().items() if k != PATH}
    request = request_for(operation, helper_catalog=helpers)
    if operation == 'check_repair':
        response = fixture_response()
        request['check_repair'] = check_repair.permission('a' * 64, response['checks'], response['design'])
    schema = response_schema(request)
    assert 'assets' not in schema['properties']
    if operation != 'repair':
        assert '"experience"' not in json.dumps(schema['properties']['checks'])
    prompt = system_prompt(request)
    assert 'GENERATED MEDIA' not in prompt and 'assets=null' not in prompt
    assert 'Emit minified JSON' not in prompt
    if operation == 'create':
        response = fixture_response()
        validate_response(response, operation='create', schema=schema)
        candidate = materialize(response, operation='create', helper_catalog=helpers)
        assert PATH not in candidate['files'] and 'game-assets.json' not in candidate['files']


def rejected_edit():
    files = {'index.html': '<html><body><canvas id="board"></canvas><script src="game.js"></script></body></html>',
             'game.js': 'let score=0;\n'}
    response = {'status': 'ok', 'operation': 'edit', 'base_revision': 'base', 'checks': [],
                'patches': [{'path': 'index.html', 'file_hash': sha256(files['index.html']),
                             'old_text': "<script src='game.js'></script>",
                             'new_text': "<script>const media=GameForgeExperience;</script><script src='game.js'></script>"}]}
    return files, patch_repair.permission(response, files=files, base_revision='base')


def test_quote_error_repair_selects_original_bytes_and_keeps_atomic_hash_checks():
    files, policy = rejected_edit()
    request = request_for('edit', files=files, patch_repair=policy)
    old_text = '<script src="game.js"></script>'
    context = json.loads(build_messages(request)[1]['content'])
    assert context['exact_old_text_candidates']['0'] == [old_text]
    correction = {'status': 'ok', 'operation': 'edit', 'base_revision': 'base',
                  'response_hash': policy['response_hash'], 'message': 'Исправлен запуск.',
                  'corrections': [{'index': 0, 'patches': [{**policy['response']['patches'][0], 'old_text': old_text}]}]}
    validator = Draft202012Validator(response_schema(request))
    assert validator.is_valid(correction)
    old_quotes = deepcopy(correction)
    old_quotes['corrections'][0]['patches'][0]['old_text'] = "<script src='game.js'></script>"
    assert not validator.is_valid(old_quotes)
    restored = patch_repair.restore(correction, policy, files=files, base_revision='base', profile='full')
    changed = apply_patches(files, restored['patches'])
    assert 'const media=GameForgeExperience' in changed['index.html']
    assert changed['game.js'] == files['game.js']
    with pytest.raises(ContractError, match='версия|правки'):
        patch_repair.restore(correction, policy, files={**files, 'game.js': 'changed'}, base_revision='base', profile='full')


def test_whole_html_suggestion_is_excluded_but_script_fragment_can_be_selected():
    files, policy = rejected_edit()
    policy['response']['patches'][0]['old_text'] = files['index.html'].replace('"', "'")
    candidates = lite.literal_candidates(policy, files)[0]
    assert files['index.html'] not in candidates
    assert '<script src="game.js"></script>' in candidates


def test_lite_check_repair_retains_all_promises_above_twelve_and_pro_limit_is_unchanged():
    from validation.suites import MAX_SAVED_CHECKS

    old = fake_generate({'operation': 'create'}, on_event=lambda _: None, is_cancelled=lambda: False)['response']['checks']
    checks = [deepcopy(old[0]) for _ in range(8)]
    for i, check in enumerate(checks):
        check.update(id=f'original_{i}', category='regression')
    requirements = [{'id': f'frozen_{i}', 'category': category, 'viewport': 'mobile',
                     'requirement': f'Неизменное игровое условие номер {i}'}
                    for i, category in enumerate(['start', 'control', 'outcome', 'regression', 'regression', 'regression'])]
    frozen = {'requirements': requirements}
    with pytest.raises(ContractError, match='недостаточно места'):
        check_repair.permission('a'*64, checks, {}, frozen)
    policy = check_repair.permission('a'*64, checks, {}, frozen, max_requirements=MAX_SAVED_CHECKS)
    assert len(policy['requirements']) == 14
    assert policy['requirements'][:6] == requirements
    request = request_for('check_repair', check_repair=policy)
    assert response_schema(request)['properties']['checks']['maxItems'] == MAX_SAVED_CHECKS
    assert {r['id'] for r in policy['requirements']} == {r['id'] for r in requirements + checks}
    # The saved-suite validator already supports batches of twelve; no limit is weakened globally.
    assert validate_checks(checks, require_complete=False) is None


def test_fourteen_repaired_checks_materialize_without_touching_source_or_bypassing_review():
    from tests.test_check_repair import apply
    from validation.suites import MAX_SAVED_CHECKS
    from validation.suites import plan as batches

    response = fixture_response()
    seeds = deepcopy(response['checks'])
    response['checks'] = [deepcopy(seeds[i % len(seeds)]) for i in range(8)]
    for i, check in enumerate(response['checks']):
        check['id'] = f'original_{i}'
    base = materialize(response, operation='create')
    frozen = {'requirements': [{**{k: seeds[i % len(seeds)][k] for k in check_repair.IDENTITY},
                                'id': f'frozen_{i}'} for i in range(6)]}
    policy = check_repair.permission(base['artifact_hash'], base['checks'], base['design'], frozen,
                                     max_requirements=MAX_SAVED_CHECKS)
    checks = []
    for entry in policy['requirements']:
        source = next(c for c in seeds if c['category'] == entry['category'])
        checks.append({**deepcopy(source), **entry})
    fixed = {'status': 'ok', 'operation': 'check_repair', 'base_revision': 'base',
             'artifact_hash': base['artifact_hash'], 'checks_hash': policy['checks_hash'],
             'message': 'Сценарии дополнены без изменения игры.', 'checks': checks}
    request = request_for('check_repair', check_repair=policy)
    validate_response(fixed, operation='check_repair', schema=response_schema(request))
    result = apply(fixed, policy, base)
    assert result['files'] == base['files'] and result['artifact_hash'] == base['artifact_hash']
    assert result['checks_review_required'] is True
    assert [len(batch) for batch in batches(result['checks'])] == [12, 2]
    assert not coverage(result['checks'], frozen)['uncovered']
    fixed['checks'].pop()
    with pytest.raises(ContractError, match='удалять|условия'):
        apply(fixed, policy, base)
