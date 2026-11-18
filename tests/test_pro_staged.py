import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from generation.errors import ContractError
from generation.pro_parallel import assemble, branches, validate_reply
from generation.pro_staged import source_context
from generation.prompts import build_messages, system_prompt
from generation.schema import response_schema
from tests.test_pro_creative import creative_request
from tests.test_pro_partition import split_replies


def staged():
    req = creative_request('scene')
    req['pro_parallel'] = 4
    values = split_replies()
    checks = values['scene']['checks']
    values['scene']['checks'] = []
    context = source_context(values, req['game_plan'])
    values['checks'] = {'operation': 'pro_checks', 'source_hash': context['source_hash'], 'checks': checks}
    return req, values, context


def test_source_only_reply_and_checks_derived_from_exact_frozen_source():
    req, values, context = staged()
    validate_reply(values['scene'], req)
    assert 'SOURCE ONLY' in system_prompt(req)
    assert response_schema(req)['properties']['checks']['maxItems'] == 0
    check_req = {**req, **context, 'operation': 'pro_checks', 'pro_parallel_branch': 'checks',
                 'requirement_manifest': {'requirements': []}}
    validate_reply(values['checks'], check_req)
    assert context['files']['mechanics.js'] in build_messages(check_req)[1]['content'].replace('\\n', '\n')
    assert 'hold_key' in system_prompt(check_req)
    before = deepcopy(values)
    game = assemble(values, req['game_plan'], 4)
    assert game['checks'] == values['checks']['checks'] and values == before
    assert game['files'][-1]['content'] == context['files']['mechanics.js']
    values['scene']['files'][0]['content'] += ' '
    with pytest.raises(ContractError, match='Исходники'):
        assemble(values, req['game_plan'], 4)


def test_staged_checks_cannot_replace_source_or_drop_frozen_promises():
    req, values, context = staged()
    req.update(context, operation='pro_checks', pro_parallel_branch='checks',
               requirement_manifest={'requirements': [{'id': 'missing', 'category': 'control',
                   'requirement': 'Исходное обещание', 'viewport': 'desktop'}]})
    with pytest.raises(ContractError, match='обещания'):
        validate_reply(values['checks'], req)
    req['requirement_manifest'] = {'requirements': []}
    values['checks']['source_hash'] = '0' * 64
    with pytest.raises(ContractError, match='исходникам'):
        validate_reply(values['checks'], req)


def test_saved_versions_keep_combined_source_and_check_roles():
    req, _, _ = staged()
    for version in (1, 2, 3):
        assert 'checks' not in branches(req['game_plan'], version)
        assert response_schema({**req, 'pro_parallel': version})['properties']['checks']['maxItems'] == 12


def test_known_truncation_completes_only_missing_files_and_preserves_receipts(monkeypatch):
    from generation.pro_staged import completion_policy
    from generation.service import generate

    req, values, _ = staged()
    source = values['scene']
    fields = {k: source[k] for k in ('assets', 'base_revision', 'checks', 'design')}
    raw = json.dumps(fields)[:-1] + ', "files": [' + ','.join(
        json.dumps(f) for f in source['files'][:-1]) + ',' + json.dumps(source['files'][-1])[:-7]
    previous = SimpleNamespace(id='known-invocation', state='failed', request=req, raw_response=raw,
        error={'code': 'response_output_limit'},
        provider_metadata={'provider_error': {'incomplete_reason': 'max_output_tokens'}})
    policy = completion_policy(previous)
    assert policy and policy['retained_files'] == source['files'][:-1]
    req = {**req, 'response_completion': policy}
    reply = {'source_sha256': policy['source_sha256'],
             'completion': {k: source[k] for k in policy['missing_fields']}}
    reply['completion']['files'] = source['files'][-1:]
    monkeypatch.setattr('generation.providers.codex_api.generate', lambda *a, **kw: {'response': reply, 'usage': {}})
    result = generate(req, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result['response'] == source and result['raw_response'] == reply
    assert result['provider_metadata']['response_completion']['source_invocation'] == 'known-invocation'
    validate_reply(result['response'], req)  # durable consumption validates canonical, not wire envelope
    assert 'FINISH AN INTERRUPTED' in system_prompt(req)
    assert 'Create requires non-null assets' not in system_prompt(req)
    previous.request = req
    assert completion_policy(previous) is None
    previous.state = 'unknown'
    assert completion_policy(previous) is None
