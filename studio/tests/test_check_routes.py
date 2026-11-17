import hashlib

import pytest

from generation.prompts import system_prompt
from generation.requirements import policy_snapshot
from studio.services import create_run
from studio.tasks import request_for
from studio.tests.test_draft_editing import workspace as draft_workspace

workspace = draft_workspace


@pytest.mark.django_db
@pytest.mark.parametrize('strategy,provider', [('lite', 'relay'), ('pro', 'codex_api')])
def test_route_guidance_is_pinned_before_dispatch_without_new_pipeline_steps(workspace, strategy, provider):
    chat, _ = workspace
    run = create_run(chat, {'prompt': 'Собери три звезды', 'idempotency_key': 'routes'})
    run.provider, run.generation_strategy = provider, strategy
    run.planning_required = False
    req = request_for(run, None, [])
    assert req['operation'] == 'create' and req['check_routes_policy'] == 1
    assert (req.get('lite_wait_budget') == 1) == (strategy == 'lite')
    assert req['generation_contract']['system_prompt_sha256'] == hashlib.sha256(system_prompt(req).encode()).hexdigest()
    assert 'check_routes.py' in policy_snapshot()['source_hashes']
    assert req['generation_contract']['max_repair_attempts'] == run.max_repair_attempts
    run.planning_required = True
    plan = request_for(run, None, [])
    assert plan['operation'] == 'plan' and 'check_routes_policy' not in plan
    assert 'lite_wait_budget' not in plan
    run.planning_required = False
    run.generation_profile = 'compact'
    compact = request_for(run, None, [])
    assert 'check_routes_policy' not in compact
    assert 'lite_wait_budget' not in compact
