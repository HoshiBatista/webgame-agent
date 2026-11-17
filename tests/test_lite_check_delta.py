from copy import deepcopy

import pytest

from generation import lite_check_delta, service
from generation.artifacts import materialize
from generation.check_repair import permission
from generation.errors import ContractError
from generation.prompts import build_messages
from generation.providers.fake import fixture_response
from generation.schema import response_schema
from tests.test_check_repair import apply, proposal
from tests.test_lite_policy import PRO_BASELINES, digest
from tests.test_lite_wire import request


def example():
    original = fixture_response()
    base = materialize(original, operation='create')
    response, policy = proposal(base)
    response['checks'] = [deepcopy(response['checks'][-1])]
    response['checks'][0]['steps'].append({'action': 'wait', 'ms': 100})
    req = request('check_repair', lite_check_delta=1, lite_wait_budget=1,
                  base_revision='base', checks=base['checks'], check_repair=policy)
    return base, response, req


def test_delta_uses_immutable_originals_and_retains_complete_suite(monkeypatch):
    base, response, req = example()
    before = deepcopy((base, response, req))
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {
        'response': response, 'raw_response': 'original model receipt', 'usage': {'output_tokens': 100}})
    result = service.generate(req, on_event=lambda _: None, is_cancelled=lambda: False)
    actual = result['response']
    assert actual['checks'][:-1] == base['checks'][:-1]
    assert actual['checks'][-1] == {**response['checks'][0], 'wait_budget_ms': 30000}
    assert result['provider_metadata']['lite_check_delta']['retained_check_ids'] == [c['id'] for c in base['checks'][:-1]]
    assert result['raw_response'] == 'original model receipt' and result['usage']['output_tokens'] == 100
    artifact = apply(actual, req['check_repair'], base)
    assert artifact['checks_review_required'] and artifact['files'] == base['files']
    assert (base, response, req) == before


@pytest.mark.parametrize('mutation', ['id', 'category', 'viewport', 'requirement', 'duplicate',
                                     'checks_hash', 'artifact_hash', 'base_revision'])
def test_delta_cannot_change_permissions_or_target(mutation):
    _, response, req = example()
    if mutation in {'checks_hash', 'artifact_hash', 'base_revision'}:
        response[mutation] = 'wrong'
    elif mutation == 'duplicate':
        response['checks'].append(deepcopy(response['checks'][0]))
    else:
        response['checks'][0][mutation] = 'wrong'
    with pytest.raises(ContractError):
        lite_check_delta.assemble(response, req)


def test_missing_new_requirement_and_omitted_broken_scenario_are_not_success(monkeypatch):
    _, response, req = example()
    req['check_repair']['requirements'].append({**req['check_repair']['requirements'][0], 'id': 'new'})
    with pytest.raises(ContractError, match='Не указан'):
        lite_check_delta.assemble(response, req)
    base, response, req = example()
    req['checks'][0]['steps'] = [{'action': 'wait', 'ms': 10001}]
    req['check_repair'] = permission(base['artifact_hash'], req['checks'], base.get('design', {}))
    response['checks_hash'] = req['check_repair']['checks_hash']
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {'response': response})
    with pytest.raises(ContractError):
        service.generate(req, on_event=lambda _: None, is_cancelled=lambda: False)


def test_protected_scenario_is_restored_and_source_fields_still_rejected(monkeypatch):
    base, response, req = example()
    req['check_repair'] = permission(base['artifact_hash'], base['checks'], {},
                                    protected_ids=[base['checks'][0]['id']])
    changed = deepcopy(base['checks'][0])
    changed['expect']['value'] = 'wrong'
    response['checks'].append(changed)
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {'response': response})
    result = service.generate(req, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result['response']['checks'][0] == base['checks'][0]
    response['files'] = []
    with pytest.raises(ContractError):
        service.generate(req, on_event=lambda _: None, is_cancelled=lambda: False)


@pytest.mark.parametrize('baseline', PRO_BASELINES)
def test_pro_contracts_do_not_enable_delta(baseline):
    req = {**baseline['request'], 'lite_check_delta': 1}
    assert digest(build_messages(req)) == baseline['messages_sha256']
    assert digest(response_schema(req)) == baseline['schema_sha256']
    assert not lite_check_delta.enabled(req)


@pytest.mark.parametrize('extra', [{'lite_check_delta': 0}, {'lite_check_delta': True},
                                 {'generation_profile': 'compact'}, {'lite_policy': 1},
                                 {'operation': 'edit'}, {'provider': 'fake'}])
def test_only_explicit_new_lite_check_repair_enables_delta(extra):
    _, response, req = example()
    req.update(extra)
    assert lite_check_delta.assemble(response, req) == (response, [])
    assert not lite_check_delta.guidance(req)
