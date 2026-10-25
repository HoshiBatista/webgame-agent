from copy import deepcopy

import pytest

from generation.check_repair import checks_hash
from generation.errors import ContractError
from generation.schema import response_schema
from generation.source_policy import module_policy
from tests.test_source_repair import base_game, repair, replacement


def basis_for(base):
    return {'base_revision': 'base', 'artifact_hash': base['artifact_hash'],
            'checks_hash': checks_hash(base['checks']), 'report_id': 1,
            'report_identity': 'verified-report', 'defects': ['javascript_syntax']}


@pytest.mark.parametrize('defect', ['empty', 'category', 'duplicate'])
def test_v7_code_repair_preserves_incomplete_check_list(defect):
    base = base_game()
    if defect == 'empty':
        base['checks'] = []
    elif defect == 'category':
        base['checks'] = base['checks'][:2]
    else:
        base['checks'].append(deepcopy(base['checks'][0]))
    frozen = deepcopy(base['checks'])
    result = repair(replacement(base), base, generation_contract={'pipeline_version': 8},
                    code_repair_basis=basis_for(base), module_repair=module_policy(base['files'], [{'code': 'javascript_syntax', 'path': 'game.js'}]))
    assert result['checks'] == frozen
    assert result['files']['game.js'] != base['files']['game.js']


@pytest.mark.parametrize('field,value', [
    ('artifact_hash', 'other'), ('checks_hash', 'other'), ('base_revision', 'other'),
    ('defects', ['effect_mismatch']), ('defects', ['surface_unverified']), ('report_id', 0),
    ('report_identity', ''),
])
def test_v7_rejects_unbound_code_permission(field, value):
    base = base_game()
    base['checks'] = []
    basis = {**basis_for(base), field: value}
    with pytest.raises(ContractError, match='разрешения'):
        repair(replacement(base), base, generation_contract={'pipeline_version': 8}, code_repair_basis=basis)


def test_legacy_and_unpermitted_incomplete_repairs_still_fail_closed():
    base = base_game()
    base['checks'] = []
    for version in [8]:
        with pytest.raises(ContractError) as caught:
            repair(replacement(base), base, generation_contract={'pipeline_version': version})
        assert caught.value.code == 'invalid_baseline_checks'


@pytest.mark.parametrize('version', [2, 3, 4, 5, 6, 7])
def test_retired_versions_are_rejected(version):
    with pytest.raises(ContractError) as error:
        response_schema({'operation':'repair','generation_contract':{'pipeline_version':version}})
    assert error.value.code == 'unknown_contract'
