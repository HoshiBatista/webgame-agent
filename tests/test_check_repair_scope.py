"""A bad proposal cannot rewrite a passing check while repairing another one."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from generation.artifacts import materialize
from generation.check_repair import permission, scoped_response
from generation.errors import ContractError
from generation.providers.fake import fixture_response
from generation.service import generate
from studio.check_repair import protected_ids
from tests.test_check_repair import apply, proposal
from validation.contracts import implementation_hash


def scenario():
    base = materialize(fixture_response(), operation='create')
    fixed, _ = proposal(base)
    protected = [c['id'] for c in base['checks'][:2]]
    policy = permission(base['artifact_hash'], base['checks'], base['design'], protected_ids=protected)
    fixed['checks'][1]['expect'] = {'operator': 'unchanged', 'value': None}
    fixed['checks'][-1]['steps'].append({'action': 'wait', 'ms': 100})
    return base, fixed, policy


def test_unrelated_invalid_proposal_retains_verified_original_and_requires_review():
    base, fixed, policy = scenario()
    original = deepcopy((base, fixed, policy))
    effective, retained = scoped_response(fixed, previous_checks=base['checks'], policy=policy)
    result = apply(fixed, policy, base)
    assert retained == [base['checks'][1]['id']]
    assert effective['checks'][:2] == base['checks'][:2] == result['checks'][:2]
    assert result['checks'][-1] == fixed['checks'][-1]
    assert result['checks_review_required'] is True
    assert result['files'] == base['files'] and result['html'] == base['html']
    assert (base, fixed, policy) == original


@pytest.mark.parametrize('mutation', ['identity', 'duplicate', 'missing', 'hash', 'protected', 'wire', 'failed'])
def test_scope_does_not_hide_changed_requirements_or_invalid_targeted_repair(mutation):
    base, fixed, policy = scenario()
    if mutation == 'identity':
        fixed['checks'][1]['requirement'] = 'Easier condition'
    elif mutation == 'duplicate':
        fixed['checks'].append(deepcopy(fixed['checks'][1]))
    elif mutation == 'missing':
        fixed['checks'].pop(0)
    elif mutation == 'hash':
        fixed['checks_hash'] = '0' * 64
    elif mutation == 'protected':
        policy['protected_checks'][1]['expect']['value'] = 999
    elif mutation == 'wire':
        fixed['checks'][1]['steps'] = [{'action': 'execute_arbitrary_code'}]
    else:
        fixed['checks'][-1]['expect'] = {'operator': 'unchanged', 'value': None}
    with pytest.raises(ContractError):
        apply(fixed, policy, base)


def test_provider_keeps_raw_reply_and_records_scope_before_semantic_validation():
    base, fixed, policy = scenario()
    before = deepcopy(fixed)
    request = {'provider': 'fake', 'operation': 'check_repair', 'base_revision': 'base',
               'generation_contract': {'pipeline_version': 9}, 'checks': base['checks'], 'check_repair': policy}
    with patch('generation.providers.fake.generate', return_value={'response': fixed, 'usage': {}}):
        result = generate(request, on_event=lambda *args: None, is_cancelled=lambda: False)
    assert result['raw_response'] == before == fixed
    assert result['response']['checks'][:2] == base['checks'][:2]
    assert result['provider_metadata']['check_repair_scope'] == {
        'retained_passed_checks': [base['checks'][1]['id']]}
    assert apply(result['response'], policy, base)['checks_review_required']


@pytest.mark.parametrize('stale', [None, 'identity', 'validator', 'coverage', 'gates', 'checks', 'compact'])
def test_protection_requires_current_complete_browser_evidence(stale):
    base, _, _ = scenario()
    assessment = {'validator_hash': implementation_hash(), 'gates_passed': True,
                  'requirement_coverage': {'uncovered': []}}
    report = SimpleNamespace(identity='current', environment='fixture', assessment=assessment,
        checks=deepcopy(base['checks']), facts=[{'id': c['id'], 'status': 'passed' if i < 2 else 'failed'}
        for i, c in enumerate(base['checks'])], findings=[{'code': 'effect_mismatch', 'check_id': base['checks'][-1]['id']}])
    revision = SimpleNamespace(generation_profile='full', checks=base['checks'],
        reports=SimpleNamespace(order_by=lambda *args: SimpleNamespace(first=lambda: report)))
    if stale == 'identity':
        report.identity = 'old'
    elif stale == 'validator':
        assessment['validator_hash'] = 'old'
    elif stale == 'coverage':
        assessment['requirement_coverage']['uncovered'] = ['missing']
    elif stale == 'gates':
        assessment['gates_passed'] = False
    elif stale == 'checks':
        report.checks[0]['steps'].append({'action': 'wait', 'ms': 100})
    elif stale == 'compact':
        revision.generation_profile = 'compact'
    with patch('studio.tasks.check_identity', return_value='current'):
        assert protected_ids(revision) == ([] if stale else [c['id'] for c in base['checks'][:2]])
