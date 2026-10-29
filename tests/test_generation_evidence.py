"""Independent negative and positive requirements; no inference or model-authored oracle."""
from copy import deepcopy

import pytest

from generation.artifacts import sha256
from tests.test_check_semantics import game, game_checks
from validation.check_program import compile_check
from validation.criteria import OperatorCriterion, bindings
from validation.service import validate


def test_compiled_program_is_immutable_and_owns_control_boundary():
    source = game_checks()[1]
    program = compile_check(source)
    source['steps'].clear()
    decoded = program.check()
    decoded['steps'].clear()
    assert program.measured_from == 2 and len(program.check()['steps']) == 4
    control = program.without_last_input()
    assert control['_omitted'] == [2]
    assert control['steps'] == program.check()['steps'][:2] + program.check()['steps'][3:]


@pytest.mark.parametrize('field,value', [('observation', None), ('expect', []), ('category', []), ('id', 2)])
def test_malformed_bounded_fields_become_structured_scenario_errors(field, value):
    check = game_checks()[1]
    check[field] = value
    assert compile_check(check).issue.code == 'invalid_check'


def test_operator_binding_includes_expectation_actions_and_requirement():
    check = game_checks()[2]
    criterion = OperatorCriterion.for_check(check).payload()
    assert bindings([check], [criterion])
    for key, value in [('expect', {'operator': 'eq', 'value': 11}), ('steps', []), ('requirement', 'Early goal')]:
        other = {**check, key: value}
        assert not bindings([other], [criterion])
    with pytest.raises(ValueError):
        bindings([check], [{**criterion, 'source': 'model'}])


def relative_checks():
    checks = game_checks()
    checks[2].update(steps=deepcopy(checks[1]['steps']), expect={'operator': 'increased', 'value': None})
    # Preserve the desktop profile: it has a mouse, not a touchscreen.
    for step in checks[2]['steps']:
        if step['action'] == 'tap':
            step['action'] = 'click'
    return checks


@pytest.mark.browser
def test_seeded_pair_preserves_random_setup_and_real_input():
    html = game().replace("s.count=10;score.textContent='10'", "s.count=Math.floor(Math.random()*10000);score.textContent=String(s.count)")
    checks = relative_checks()
    checks[0]['observation'] = {'source': 'state', 'path': 's.active'}
    checks[0]['expect'] = {'operator': 'eq', 'value': True}
    report = validate(html, checks, artifact_hash=sha256(html))
    assert report['status'] == 'passed', report
    for fact in report['facts'][1:]:
        causal = fact['causal_evidence']
        assert causal['matched_setup']
        assert causal['action']['comparison'] is True and causal['control']['comparison'] is False
        assert causal['action']['profile'] == causal['control']['profile']
        assert causal['action']['isolation']['clock_matched']
    assert report['coverage']['scope'] == 'model_proposals_only'
    assert report['coverage']['natural_language_request_verified'] is False


@pytest.mark.browser
def test_timer_progress_without_control_input_does_not_prove_causality():
    html = game(broken=True).replace("score.textContent='10';", "score.textContent='10';setTimeout(()=>{s.count++;score.textContent=String(s.count)},120);")
    report = validate(html, relative_checks(), artifact_hash=sha256(html))
    assert report['status'] == 'unverified', report
    assert {f['check_id'] for f in report['findings'] if f['code'] == 'effect_not_causal'} == {'control', 'outcome'}
    assert report['facts'][1]['causal_evidence']['control']['comparison'] is True


@pytest.mark.browser
@pytest.mark.parametrize('script', [
    pytest.param('Math.random=()=>0.5;', id='rng'),
    pytest.param('crypto.getRandomValues(new Uint8Array(1));', id='entropy'),
    pytest.param('Date.now=()=>0;', id='clock'),
])
def test_lost_environment_isolation_is_uncertainty_not_a_game_defect(script):
    html = game().replace('window.s=', script + 'window.s=')
    report = validate(html, game_checks(), artifact_hash=sha256(html))
    assert report['status'] == 'unverified', report
    assert 'effect_not_causal' in {f['code'] for f in report['findings']}
    assert all(report['gates'].values())


@pytest.mark.browser
def test_independent_timer_outcome_needs_no_last_moment_input_but_control_still_does():
    html = game().replace("window.s={count:0,active:false}", "window.s={count:0,active:false,done:false}")
    html = html.replace("score.textContent='10';", "score.textContent='10';setTimeout(()=>s.done=true,150);")
    checks = game_checks()
    checks[2].update(steps=[checks[1]['steps'][0], {'action': 'checkpoint'}, {'action': 'wait_for', 'ms': 300}],
                     observation={'source': 'state', 'path': 's.done'}, expect={'operator': 'eq', 'value': True})
    criterion = OperatorCriterion.for_check(checks[2], mode='timer')
    report = validate(html, checks, artifact_hash=sha256(html), operator_criteria=(criterion,))
    assert report['status'] == 'passed', report
    assert report['facts'][1]['causal_evidence']['matched_setup']
    assert 'causal_evidence' not in report['facts'][2]
    assert report['coverage']['scenarios'][2]['source'] == 'operator_fixture'
    untrusted = validate(html, checks, artifact_hash=sha256(html))
    assert untrusted['status'] == 'unverified'
    assert untrusted['facts'][2]['compile_issue']['code'] == 'no_real_input'


@pytest.mark.browser
def test_intermediate_outcome_cannot_cover_an_independent_final_requirement():
    html, checks = game(), game_checks()
    criterion = OperatorCriterion.for_check(checks[2])
    # A model replaces the expected two hits by an easier, intermediate one.
    checks[2]['steps'].pop(2)
    checks[2]['expect']['value'] = 11
    report = validate(html, checks, artifact_hash=sha256(html), operator_criteria=(criterion,))
    assert report['status'] == 'unverified', report
    assert report['coverage']['uncovered'] == [criterion.requirement]
    assert any(f['code'] == 'uncovered_requirements' for f in report['findings'])


@pytest.mark.browser
def test_fake_state_cannot_satisfy_independent_visible_effect():
    html = game().replace('score.textContent=String(s.count);draw()', 'draw()')
    checks = game_checks()
    checks[2]['observation'] = {'source': 'text_number', 'selector': '#score'}
    criterion = OperatorCriterion.for_check(checks[2])
    report = validate(html, checks, artifact_hash=sha256(html), operator_criteria=(criterion,))
    assert report['status'] == 'failed', report
    assert report['facts'][2]['comparison'] is False
    assert report['coverage']['scenarios'][2]['source'] == 'operator_fixture'
    assert report['facts'][1]['trace'][2]['input_probe']['status'] == 'reachable'


def test_missing_or_model_authored_evidence_never_grants_code_repair():
    from studio.acceptance import assess
    for code in ('effect_mismatch', 'uncovered_requirements', 'an_unknown_error'):
        report = {'status': 'failed', 'findings': [{'code': code}], 'facts': []}
        assert assess(report, game_checks(), [])['action'] == 'review'
    # A real independent browser crash still permits code repair.
    report['findings'].append({'code': 'runtime_or_network', 'errors': ['TypeError: input handler']})
    assert assess(report, game_checks(), [])['action'] == 'repair'


def test_controller_rejects_coverage_that_lost_its_independent_binding():
    from tests.test_validation import fixture_checks, fixture_html, fixture_report
    from validation.criteria import coverage
    from validation.service import _validated_report
    html, checks = fixture_html(), fixture_checks()
    criterion = OperatorCriterion.for_check(checks[2]).payload()
    report = fixture_report(html, checks)
    report['coverage'] = coverage(checks, [criterion], report['facts'])
    _validated_report(deepcopy(report), checks, sha256(html), 0, operator_criteria=[criterion])
    with pytest.raises(ValueError, match='coverage'):
        _validated_report(report, checks, sha256(html), 0)
