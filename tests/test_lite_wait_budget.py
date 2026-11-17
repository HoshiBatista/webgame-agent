from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from generation import lite_wait_budget
from generation.errors import ContractError
from generation.prompts import build_messages
from generation.schema import response_schema, validate_checks
from tests.test_lite_checks import outcome
from tests.test_lite_policy import PRO_BASELINES, digest
from tests.test_lite_wire import block_reply, request
from validation.check_program import compile_check, envelope
from validation.contracts import browser_watchdog_seconds


def long_check():
    from generation.lite_wire import check_from_lines

    check = check_from_lines(outcome(['press Enter', 'wait 10000', 'wait 3500', 'wait_for 2000']), timed=True)
    return check


def test_explicit_budget_keeps_the_old_limit_and_every_other_guard():
    original = long_check()
    assert compile_check(original).issue.code == 'long_check'
    check = {**original, 'wait_budget_ms': 30000}
    program = compile_check(check)
    assert program.issue is None
    negative = program.without_last_input()
    assert negative['wait_budget_ms'] == 30000
    assert negative['steps'] == check['steps'][1:]
    assert negative['observation'] == check['observation'] and negative['expect'] == check['expect']
    validate_checks([check], require_complete=False)
    assert browser_watchdog_seconds([check]) > browser_watchdog_seconds([original])
    for value in [True, 30000.0, '30000', -1, 30001, None]:
        assert compile_check({**check, 'wait_budget_ms': value}).issue.code == 'invalid_check'
    too_long = {**check, 'steps': [check['steps'][0], *[{'action': 'wait', 'ms': 10000}] * 3,
                                 {'action': 'wait_for', 'ms': 1}]}
    assert compile_check(too_long).issue.code == 'long_check'
    with pytest.raises(ValueError):
        envelope([{**check, 'steps': [{'action': 'wait', 'ms': 10001}]}])
    for action in ['wait_for', 'await_condition', 'hold_touch']:
        step = {'action': action, 'ms': 3001}
        if action == 'await_condition':
            step.update(observation=check['observation'], expect=check['expect'])
        elif action == 'hold_touch':
            step.update(selector='#right', x=None, y=None)
        with pytest.raises(ContractError):
            validate_checks([{**check, 'steps': [check['steps'][0], step]}], require_complete=False)


def test_budget_is_recorded_without_mutating_goals_source_or_protected_checks():
    check = long_check()
    protected = {**check, 'id': 'kept', 'steps': [{'action': 'press', 'key': 'Enter'}]}
    reply = {'checks': [check, protected], 'files': [{'path': 'game.js', 'content': 'unchanged source'}]}
    before = deepcopy(reply)
    req = request('check_repair', lite_wait_budget=1, check_repair={'protected_checks': [protected]})
    actual, ids = lite_wait_budget.prepare(reply, req)
    assert reply == before and ids == ['end']
    assert actual['checks'][0] == {**check, 'wait_budget_ms': 30000}
    assert actual['checks'][1] == protected and actual['files'] == reply['files']
    for overrides in ({'lite_wait_budget': 0}, {'generation_strategy': 'pro'},
                      {'generation_profile': 'compact'}, {'operation': 'music'}):
        assert lite_wait_budget.prepare(reply, {**req, **overrides}) == (reply, [])


def test_long_suite_watchdog_accounts_for_all_matched_runs_and_keeps_old_ceiling():
    ordinary = {**long_check(), 'steps': [{'action': 'press', 'key': 'Enter'},
                                         {'action': 'wait', 'ms': 10000}]}
    suite = [{**ordinary, 'id': f'case-{i}'} for i in range(12)]
    assert browser_watchdog_seconds(suite) <= 600
    extended = [{**c, 'wait_budget_ms': 30000,
                 'steps': [c['steps'][0], *[{'action': 'wait', 'ms': 10000}] * 3]} for c in suite]
    assert 1080 < browser_watchdog_seconds(extended) <= 1500
    assert browser_watchdog_seconds(extended, capture_visual=True) == browser_watchdog_seconds(extended) + 45


def test_materialization_preserves_issued_budget_for_repaired_scenarios():
    from generation.artifacts import materialize
    from generation.providers.fake import fixture_response
    from tests.test_check_repair import apply, proposal

    base = materialize(fixture_response(), operation='create')
    response, policy = proposal(base)
    response['checks'] = [{**c, 'wait_budget_ms': 30000} for c in response['checks']]
    result = apply(response, policy, base)
    assert result['checks'] == response['checks']
    assert result['html'] == base['html'] and result['checks_review_required']


@pytest.mark.parametrize('baseline', PRO_BASELINES)
def test_pro_saved_contracts_ignore_lite_wait_marker(baseline):
    req = {**baseline['request'], 'lite_wait_budget': 1}
    assert digest(build_messages(req)) == baseline['messages_sha256']
    assert digest(response_schema(req)) == baseline['schema_sha256']


def test_pro_can_edit_inherited_long_checks_without_changing_ordinary_pro_schema():
    req = {'operation': 'edit', 'generation_profile': 'full', 'provider': 'codex_api',
           'generation_strategy': 'pro'}
    check = {**long_check(), 'wait_budget_ms': 30000}
    ordinary = response_schema(req)['properties']['checks']['items']
    inherited = response_schema({**req, 'checks': [check]})['properties']['checks']['items']
    assert not Draft202012Validator(ordinary).is_valid(check)
    assert Draft202012Validator(inherited).is_valid(check)
    assert 'Preserve wait_budget_ms=30000' in build_messages({**req, 'checks': [check]})[0]['content']
    assert '30000ms total supersedes' in build_messages({**req, 'checks': [check]})[0]['content']


def test_lite_wire_round_trip_retains_real_waits_and_accounts_the_policy(monkeypatch):
    from generation import service
    from generation.providers.fake import fixture_response

    response = fixture_response()
    target = next(c for c in response['checks'] if c['category'] == 'outcome')
    target['steps'] = long_check()['steps'][:-1]  # v3 adds the final bounded poll.
    raw = block_reply(response, simple=True)
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {
        'response': {'lite_source_text': raw}, 'raw_response': raw, 'usage': {'output_tokens': 400}})
    req = request(lite_code_blocks=3, lite_wait_budget=1)
    result = service.generate(req, on_event=lambda _: None, is_cancelled=lambda: False)
    actual = next(c for c in result['response']['checks'] if c['category'] == 'outcome')
    assert actual['wait_budget_ms'] == 30000
    assert actual['steps'] == [*target['steps'], {'action': 'wait_for', 'ms': 3000}]
    assert actual['expect'] == target['expect'] and actual['observation'] == target['observation']
    assert result['raw_response'] == raw and result['usage'] == {'output_tokens': 400}
    assert result['provider_metadata']['lite_wait_budget']['milliseconds'] == 30000
    assert 'CURRENT LITE SCENARIO TIME LIMIT: 30000ms' in build_messages(req)[0]['content']


@pytest.mark.browser
@pytest.mark.native_browser
@pytest.mark.parametrize('automatic', [False, True])
def test_long_round_uses_real_elapsed_time_and_still_requires_decisive_input(monkeypatch, automatic):
    from generation.artifacts import sha256
    from validation.service import validate

    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    html = '''<canvas width="300" height="180"></canvas><script>
    const ctx=document.querySelector('canvas').getContext('2d');window.state={phase:'idle'};
    function paint(){ctx.fillStyle=state.phase==='over'?'green':'orange';ctx.fillRect(20,20,80,60);}
    function end(){state.phase='over';paint();}
    window.addEventListener('keydown',e=>{if(e.key==='Enter'){state.phase='playing';paint();SCHEDULE}});
    INITIAL
    paint();</script>'''.replace('SCHEDULE', '' if automatic else 'setTimeout(end,14000);').replace(
        'INITIAL', 'setTimeout(end,14000);' if automatic else '')
    check = {**long_check(), 'wait_budget_ms': 30000}
    report = validate(html, [check], artifact_hash=sha256(html), test_profile={'seed': 1337, 'clock': True})
    fact = report['facts'][0]
    assert fact['status'] == ('unverified' if automatic else 'passed'), report['findings']
    assert fact['causal_evidence']['action']['comparison'] is True
    assert fact['causal_evidence']['control']['comparison'] is automatic
