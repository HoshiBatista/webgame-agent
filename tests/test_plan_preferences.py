"""Source attribution uses the frozen settings, never an invented user quote."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from generation.errors import ContractError
from generation.planning import normalize_plan_sources, validate_plan
from generation.schema import response_schema, validate_response
from generation.service import generate
from tests.test_planning_v2 import proposed

WISH = 'Делать уровни сложнее, делать несколько уровней'


def example():
    request, response = proposed()
    request.update(plan_provenance=1, preferences=[WISH], provider='fake')
    response['plan']['requirements'][0].update(origin='preference', quote=WISH)
    return request, response


def check(response, request):
    validate_response(response, operation='plan', schema=response_schema(request))
    validate_plan(response, request)


def test_verbatim_preference_has_its_own_source_without_changing_the_request():
    request, response = example()
    before = deepcopy((request, response))
    check(response, request)
    assert (request, response) == before
    assert WISH not in request['prompt']


@pytest.mark.parametrize('fault', ['invented', 'empty', 'paraphrase', 'metadata', 'joined_entries', 'wrong_source'])
def test_preference_provenance_does_not_accept_unattributed_text(fault):
    request, response = example()
    requirement = response['plan']['requirements'][0]
    if fault == 'invented':
        requirement['quote'] = 'Нужны сто уровней'
    elif fault == 'empty':
        requirement['quote'] = ' '
    elif fault == 'paraphrase':
        requirement['quote'] = 'Создавать много сложных уровней'
    elif fault == 'metadata':
        request['preferences'] = {'untrusted_metadata': WISH}
    elif fault == 'joined_entries':
        request['preferences'] = ['Делать уровни сложнее,', 'делать несколько уровней']
    else:
        requirement['quote'] = request['prompt']
    with pytest.raises(ContractError):
        check(response, request)


def test_mislabeled_saved_wish_is_reclassified_once_with_raw_receipt_preserved():
    request, original = example()
    original['plan']['requirements'][0]['origin'] = 'user'
    before = deepcopy(original)
    with patch('generation.providers.fake.generate', return_value={'response': original, 'usage': {'output_tokens': 42}}):
        result = generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    assert original == before == result['raw_response']
    expected = deepcopy(before)
    expected['plan']['requirements'][0]['origin'] = 'preference'
    assert result['response'] == expected
    assert result['usage']['output_tokens'] == 42
    assert result['provider_metadata']['plan_provenance']['changes'] == [
        {'path': 'plan.requirements.0.origin', 'from': 'user', 'to': 'preference'}]
    canonical, changes = normalize_plan_sources(expected, request)
    assert canonical == expected and not changes


@pytest.mark.parametrize('origin,quote', [('design', WISH), ('user', 'Нужны сто уровней')])
def test_normalization_never_invents_provenance_or_changes_requirements(origin, quote):
    request, response = example()
    response['plan']['requirements'][0].update(origin=origin, quote=quote)
    canonical, changes = normalize_plan_sources(response, request)
    assert canonical == response and not changes
    with pytest.raises(ContractError):
        check(canonical, request)


def test_original_request_wins_when_quote_is_present_in_both_sources():
    request, response = example()
    request['preferences'] = [request['prompt']]
    response['plan']['requirements'][0].update(origin='user', quote=request['prompt'])
    canonical, changes = normalize_plan_sources(response, request)
    assert canonical == response and not changes
    check(canonical, request)


def test_previous_receipt_contract_is_not_reinterpreted():
    request, response = example()
    request.pop('plan_provenance')
    with pytest.raises(ContractError):
        check(response, request)
    response['plan']['requirements'][0]['origin'] = 'user'
    canonical, changes = normalize_plan_sources(response, request)
    assert canonical == response and not changes
    with pytest.raises(ContractError):
        check(canonical, request)
