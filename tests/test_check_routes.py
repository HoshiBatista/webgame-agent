from copy import deepcopy

import pytest

from generation.check_routes import TIMING, guidance
from generation.prompts import build_messages
from generation.schema import response_schema
from tests.test_lite_policy import PRO_BASELINES, digest, request_for


@pytest.mark.parametrize('baseline', PRO_BASELINES)
def test_saved_pro_requests_keep_exact_messages_and_schema(baseline):
    request = baseline['request']
    assert digest(build_messages(request)) == baseline['messages_sha256']
    assert digest(response_schema(request)) == baseline['schema_sha256']


@pytest.mark.parametrize('strategy', ['lite', 'pro'])
@pytest.mark.parametrize('operation', ['create', 'edit', 'repair', 'check_repair'])
def test_new_guidance_keeps_source_and_response_permissions(strategy, operation):
    old = request_for(operation, lite_policy=2, generation_strategy=strategy,
                      provider='relay' if strategy == 'lite' else 'codex_api')
    if operation == 'check_repair':
        old['check_repair'] = {'artifact_hash': 'a', 'checks_hash': 'b', 'requirements': []}
    new = {**old, 'check_routes_policy': 1}
    snapshot = deepcopy(new)
    before, after = build_messages(old), build_messages(new)
    assert 'SCENARIO TIME AND ROUTE' not in before[0]['content']
    assert TIMING in after[0]['content']
    assert ('LITE PLAYABLE ROUTES' in after[0]['content']) == (strategy == 'lite')
    assert before[1:] == after[1:]
    assert response_schema(new) == response_schema(old)
    assert new == snapshot


@pytest.mark.parametrize('override', [
    {'check_routes_policy': 0}, {'check_routes_policy': 2},
    {'generation_profile': 'compact'}, {'operation': 'plan'}, {'operation': 'music'},
    {'operation': 'visual_patch'}, {'provider': 'fake'}, {'lite_policy': 1},
])
def test_guidance_does_not_leak_into_other_pipelines(override):
    request = request_for('create', lite_policy=2, check_routes_policy=1)
    assert guidance({**request, **override}) == ''


@pytest.mark.browser
@pytest.mark.native_browser
def test_repeated_short_awaits_fail_but_real_elapsed_setup_allows_restart(monkeypatch):
    from generation.artifacts import sha256
    from validation.service import validate

    monkeypatch.setenv('VALIDATOR_BACKEND', 'native')
    html = '''<canvas width="300" height="180"></canvas><script>
    const ctx=document.querySelector('canvas').getContext('2d');
    window.state={phase:'idle'};
    function paint(){ctx.fillStyle=state.phase==='over'?'green':'orange';ctx.fillRect(20,20,80,60);}
    window.addEventListener('keydown',e=>{if(e.key==='Enter'&&state.phase!=='playing'){
      state.phase='playing';paint();setTimeout(()=>{state.phase='over';paint();},4500);
    }});paint();</script>'''
    observation = {'source': 'state', 'path': 'state.phase'}
    terminal = {'action': 'await_condition', 'ms': 600,
                'observation': observation, 'expect': {'operator': 'eq', 'value': 'over'}}
    enter = {'action': 'press', 'key': 'Enter'}
    tail = [{'action': 'checkpoint'}, enter]
    bad = {'id': 'too-early', 'category': 'restart', 'viewport': 'desktop',
           'requirement': 'После исхода Enter начинает новый раунд',
           'steps': [enter, *[deepcopy(terminal) for _ in range(8)], *tail],
           'observation': observation, 'expect': {'operator': 'eq', 'value': 'playing'}}
    good = {**bad, 'id': 'elapsed-setup',
            'steps': [enter, {'action': 'wait', 'ms': 3500}, {**terminal, 'ms': 2000}, *tail]}
    report = validate(html, [bad, good], artifact_hash=sha256(html),
                      test_profile={'seed': 1337, 'clock': True})
    facts = {f['id']: f for f in report['facts']}
    assert facts['too-early']['status'] == 'unverified', report['findings']
    assert facts['elapsed-setup']['status'] == 'passed', report['findings']
    assert any(f['code'] == 'invalid_check' and f.get('check_id') == 'too-early'
               for f in report['findings'])
