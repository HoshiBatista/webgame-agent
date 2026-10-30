from copy import deepcopy

import pytest

from validation.checks import gates_verified
from validation.contracts import implementation_hash
from validation.evidence import gates, receipt
from validation.service import _validated_report


def valid_report():
    evidence = receipt('hash', 'mini-browser-v1:' + implementation_hash() + ':test',
        {'status': 'passed', 'scripts': 1}, [
        {'viewport': viewport, 'loaded': True, 'errors': [], 'requests': [],
         'surface': {'canvases': [{'visible': True, 'width': 300, 'height': 200}], 'overflow': False}}
        for viewport in ['mobile', 'landscape', 'desktop']])
    return {'status': 'unverified', 'artifact_hash': 'hash', 'environment': evidence['environment'],
            'artifact_evidence': evidence, 'gates': gates(evidence), 'facts': [], 'findings': [],
            'stages': [{'stage': 'syntax', 'status': 'passed'}]}


@pytest.mark.parametrize('mutation', ['hash', 'environment', 'missing_view', 'load', 'geometry', 'syntax', 'flag'])
def test_false_gate_flags_or_incomplete_receipts_cannot_enable_confirmation(mutation):
    report = deepcopy(valid_report())
    evidence = report['artifact_evidence']
    if mutation == 'hash':
        evidence['artifact_hash'] = 'other'
    elif mutation == 'environment':
        evidence['environment'] = 'stale'
    elif mutation == 'missing_view':
        evidence['viewports'].pop()
    elif mutation == 'load':
        evidence['viewports'][0]['loaded'] = False
    elif mutation == 'geometry':
        evidence['viewports'][0]['surfaces'] = []
    elif mutation == 'syntax':
        evidence['syntax']['status'] = 'failed'
    else:
        report.pop('artifact_evidence')
    assert not gates_verified(report, [])
    with pytest.raises(ValueError):
        _validated_report(report, [], 'hash', 0)


def test_passed_scenarios_cannot_override_failed_artifact_receipt():
    from generation.providers.fake import fixture_response

    report = valid_report()
    checks = fixture_response()['checks']
    report.update(status='passed', facts=[{**{k: c[k] for k in ('id', 'category', 'requirement', 'viewport')},
        'status': 'passed', 'actions': c['steps']} for c in checks])
    report['artifact_evidence']['viewports'][0]['errors'] = ['runtime fault']
    report['gates'] = gates(report['artifact_evidence'])
    with pytest.raises(ValueError, match='artifact evidence'):
        _validated_report(report, checks, 'hash', 0)
