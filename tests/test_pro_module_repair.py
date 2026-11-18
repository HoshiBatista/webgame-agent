import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from generation.artifacts import materialize, sha256
from generation.errors import ContractError
from generation.experience import PATH as MEDIA
from generation.helpers import catalog
from generation.pro_module_repair import permission
from generation.prompts import build_messages
from generation.providers.fake import fixture_response
from generation.schema import response_schema
from generation.source_policy import MAX_MODULE_BYTES


@pytest.fixture
def split_game():
    reply = fixture_response(with_assets=True)
    for entry in reply['files']:
        if entry['path'] == 'index.html':
            entry['content'] = entry['content'].replace('<script src="game.js"',
                '<script src="mechanics.js"></script><script src="game.js"')
    reply['files'].append({'path': 'mechanics.js', 'content':
        'window.GameForgeMechanics = () => ({snapshot:()=>({hits:0}),dispatch:()=>[],step:()=>[]});'})
    return materialize(reply, operation='create', helper_catalog=catalog())


PLAN = {'gameplay_partition': {'mode': 'split', 'interface': {
    'state_fields': [{'name': 'hits', 'meaning': 'Number of hits to date'}]}},
    'resource_contract': {'sounds': [{'id': 'hit', 'event': 'Contact'}]}}


def mapped(files, path='mechanics.js', code='javascript_syntax'):
    return {'code': code, 'location': 'source', 'path': path, 'file_hash': sha256(files[path])}


def exact(files, path, old, new):
    return {'path': path, 'file_hash': sha256(files[path]), 'old_text': old, 'new_text': new}


def complete(game, policy, patches, **fields):
    response = fixture_response(with_assets=True)
    response.update(operation='repair', base_revision='original', patches=patches, checks=[], files=[], assets=None)
    response.update(fields)
    return materialize(response, operation='repair', base_revision='original', files=game['files'],
                       helper_catalog=catalog(), previous_checks=game['checks'], module_repair=policy)


def test_mapped_rules_failure_keeps_interface_and_validation_evidence_in_prompt(split_game):
    files = split_game['files']
    policy = permission(files, [mapped(files)], PLAN)
    request = {'operation': 'repair', 'generation_strategy': 'pro', 'pro_parallel': 4,
               'files': files, 'game_plan': PLAN, 'helper_catalog': catalog(), 'checks': split_game['checks'],
               'validation_evidence': {'facts': [{'id': 'tap', 'status': 'failed'}]}, 'module_repair': policy}
    assert policy['targets'] == policy['files'] == {'mechanics.js': sha256(files['mechanics.js'])}
    context = json.loads(build_messages(request)[1]['content'])
    assert context['game_plan'] == PLAN
    assert context['validation_evidence'] == request['validation_evidence']
    assert set(context['files']) == {'mechanics.js'}
    schema = response_schema(request)
    assert schema['properties']['assets'] == {'type': 'null'}
    patches = Draft202012Validator(schema['properties']['patches'])
    correct = exact(files, 'mechanics.js', 'hits:0', 'hits:1')
    assert patches.is_valid([correct])
    assert not patches.is_valid([{**correct, 'path': 'game.js'}])
    whole = {'action': 'replace_module', 'path': 'mechanics.js', 'file_hash': correct['file_hash'],
             'content': files['mechanics.js'].replace('hits:0', 'hits:1')}
    assert patches.is_valid([whole])
    new = complete(split_game, policy, [whole])
    assert new['checks'] == split_game['checks']
    assert set(files) == set(new['files'])
    assert [k for k in files if files[k] != new['files'][k]] == ['mechanics.js']


def test_large_mapped_source_allows_only_exact_patch_to_that_source():
    files = {'game.js': 'const state = 2;\n' + ' ' * MAX_MODULE_BYTES, 'mechanics.js': 'const z=1;'}
    policy = permission(files, [mapped(files, 'game.js')], PLAN)
    assert policy['targets'] == {'game.js': sha256(files['game.js'])} and not policy['files']
    schema = Draft202012Validator(response_schema({'operation': 'repair', 'module_repair': policy})
                                  ['properties']['patches'])
    assert schema.is_valid([exact(files, 'game.js', 'state = 2', 'state = 3')])
    assert not schema.is_valid([{'action': 'replace_module', 'path': 'game.js',
        'file_hash': sha256(files['game.js']), 'content': 'other'}])


def test_geometry_filters_owners_and_rejects_cross_file_changes(split_game):
    files = split_game['files']
    policy = permission(files, [{'code': 'mobile_overflow'}], PLAN)
    assert set(policy['targets']) == {'game.js', 'index.html', 'styles.css'}
    assert policy['reason'] == 'scene_layout' and not policy['files']
    css = exact(files, 'styles.css', 'margin:0', 'margin:1px')
    game_js = exact(files, 'game.js', 'hits>=3', 'hits>=4')
    for patches in ([css, game_js], [exact(files, 'mechanics.js', 'hits:0', 'hits:1')]):
        with pytest.raises(ContractError) as error:
            complete(split_game, policy, patches)
        assert error.value.code == 'module_scope'
    for fields, code in [({'assets': fixture_response(with_assets=True)['assets']}, 'assets_locked'),
                         ({'checks': split_game['checks']}, 'module_scope')]:
        with pytest.raises(ContractError) as error:
            complete(split_game, policy, [css], **fields)
        assert error.value.code == code
    html = exact(files, 'index.html', '<script src="mechanics.js"></script>', '')
    with pytest.raises(ContractError, match='mechanics.js'):
        complete(split_game, policy, [html])
    # A media helper cannot be inserted through a path selection.
    assert MEDIA not in policy['targets']


def test_conflicting_stale_and_unmapped_findings_never_authorize_whole_module(split_game):
    files = split_game['files']
    policy = permission(files, [mapped(files), mapped(files, 'game.js')], PLAN)
    assert set(policy['targets']) == {'mechanics.js', 'game.js'} and not policy['files']
    for finding in ({**mapped(files), 'file_hash': '0' * 64}, {'code': 'effect_mismatch'}):
        ambiguous = permission(files, [finding], PLAN)
        assert not ambiguous['files'] and ambiguous['reason'] == 'choose_one_file'
    runtime = permission(files, [mapped(files, code='runtime_or_network')], PLAN)
    assert set(runtime['targets']) == {'mechanics.js'} and not runtime['files']
    edit_source = deepcopy(files)
    edit_source['styles.css'] = 'old rules'
    assert set(permission(files, [{'code': 'mobile_overflow'}], PLAN, edit_source=edit_source)['targets']) == {'styles.css'}


def test_saved_permission_cannot_widen_after_draft_acceptance(split_game):
    from generation.pro_module_repair import saved_permission

    files = split_game['files']
    policy = permission(files, [{'code': 'mobile_overflow'}], PLAN)
    request = {'module_repair': policy}
    assert saved_permission(request, draft=True) == policy
    with pytest.raises(ContractError) as error:
        saved_permission(request, draft=False)
    assert error.value.code == 'stale_file'
    whole_css = exact(files, 'styles.css', files['styles.css'], '.other { margin: 0 }')
    with pytest.raises(ContractError) as error:
        complete(split_game, policy, [whole_css])
    assert error.value.code == 'whole_file_patch'


@pytest.mark.browser
@pytest.mark.native_browser
def test_chromium_repairs_split_mechanics_and_replays_the_original_game_checks(monkeypatch):
    from generation.pro_parallel import assemble
    from generation.pro_staged import source_context
    from generation.source_map import locate_findings
    from tests.test_pro_staged import staged
    from validation.service import validate

    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    request, replies, _ = staged()
    plan = request['game_plan']
    helpers = catalog(include_scene=True)
    scene = next(f for f in replies['scene']['files'] if f['path'] == 'game.js')
    # Keep the fixture's drawing and input handlers, but let the rules own all scoring.
    scene['content'] = scene['content'].replace('window.gameState={hits:0};',
        'const rules = window.GameForgeMechanics(1); window.gameState={hits:rules.snapshot().score};'
    ).replace('gameState.hits++;', 'rules.dispatch("hit", null); gameState.hits=rules.snapshot().score;')
    assert 'rules.dispatch("hit", null)' in scene['content']
    good_rules = replies['mechanics']['content']
    replies['mechanics']['content'] = good_rules.replace('let score = 0;', 'let score = ;')
    replies['checks']['source_hash'] = source_context(replies, plan)['source_hash']
    candidate = materialize(assemble(replies, plan, 4), operation='create',
                            generation_strategy='pro', helper_catalog=helpers)

    broken = validate(candidate['html'], candidate['checks'], artifact_hash=candidate['artifact_hash'])
    assert broken['status'] == 'failed', broken['findings']
    files = candidate['files']
    findings = locate_findings(broken['findings'], files=files, html=candidate['html'])
    syntax = next(item for item in findings if item['code'] == 'javascript_syntax')
    assert (syntax['path'], syntax['line'], syntax['location']) == ('mechanics.js', 2, 'source')
    policy = permission(files, findings, plan)
    assert policy['targets'] == policy['files'] == {'mechanics.js': sha256(files['mechanics.js'])}

    reply = fixture_response(with_assets=True)
    reply.update(operation='repair', base_revision='original', checks=[], assets=None, files=[],
                 patches=[{'action': 'replace_module', 'path': 'mechanics.js',
                           'file_hash': syntax['file_hash'], 'content': good_rules}])
    repaired = materialize(reply, operation='repair', base_revision='original', files=files,
                           previous_checks=candidate['checks'], generation_strategy='pro',
                           helper_catalog=helpers, module_repair=policy)
    assert repaired['files'] == {**files, 'mechanics.js': good_rules}
    assert repaired['checks'] == candidate['checks']
    result = validate(repaired['html'], repaired['checks'], artifact_hash=repaired['artifact_hash'])
    assert result['status'] == 'passed', result['findings']
    assert {fact['id'] for fact in result['facts'] if fact['status'] == 'passed'} == {
        'start', 'tap', 'keyboard', 'outcome'}
