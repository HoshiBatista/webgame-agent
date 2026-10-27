from unittest.mock import patch

import pytest

from studio.models import Revision
from studio.services import create_run
from studio.tasks import process_run
from studio.tests.test_draft_editing import workspace as draft_workspace
from studio.tests.test_relay import environment as relay_environment
from tests.test_compact_generation import compact_response
from tests.test_generation_providers import codex_rpc as rpc_fixture

workspace = draft_workspace
environment = relay_environment
codex_rpc = rpc_fixture


@pytest.mark.django_db(transaction=True)
def test_compact_profile_survives_real_relay_pending_and_receipt_reentry(environment, monkeypatch):
    run, store, executor, calls = environment
    run.generation_profile = "compact"
    run.source_format = "lines"
    run.save(update_fields=["generation_profile", "source_format"])
    reply = compact_response()
    reply["source_lines"] = reply.pop("source").split("\n")
    monkeypatch.setattr("studio.tests.test_relay.fixture_response", lambda: reply)
    process_run(str(run.id))
    run.refresh_from_db()
    invocation = run.invocations.get()
    payload = invocation.request["relay"]["payload"]
    assert run.status in run.ACTIVE and invocation.state == "sent"
    assert "source_lines" in payload["response_format"]["json_schema"]["schema"]["properties"]
    process_run(str(run.id))
    assert run.invocations.count() == 1
    executor.step()
    executor.step()
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert calls == [1] and run.result_revision.generation_profile == "compact"
    assert run.result_revision.runtime_version == 2 and run.result_revision.compact_manifest["probes"]
    assert Revision.objects.filter(run=run).count() == 1
    process_run(str(run.id))
    assert calls == [1]


@pytest.mark.django_db
def test_compact_reply_receipt_creates_version_and_validation_receives_frozen_contract(workspace):
    chat, _ = workspace
    run = create_run(
        chat, {"prompt": "Компактная игра", "idempotency_key": "compact", "generation_profile": "compact"}
    )

    def model(request, **kwargs):
        return {
            "response": compact_response(),
            "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0},
        }

    with (
        patch("generation.providers.fake.generate", side_effect=model),
        patch(
            "validation.service.validate", return_value={"status": "passed", "findings": [], "facts": []}
        ) as browser,
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert browser.call_args.kwargs["contract"]["runtime_version"] == 2
    assert browser.call_args.kwargs["contract"]["source_hash"] == run.result_revision.file_hashes["game.js"]


def test_codex_rpc_accepts_compact_profile_without_changing_tool_permissions(codex_rpc):
    import json

    from generation.service import generate

    codex_rpc["events"][1]["params"]["item"]["text"] = json.dumps(compact_response())
    request = {
        "provider": "codex",
        "model": "gpt-6-luna",
        "operation": "create",
        "generation_profile": "compact",
    }
    result = generate(request, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result["response"]["source"] == compact_response()["source"]
    params = next(params for method, params in codex_rpc["calls"] if method == "turn/start")
    assert "source" in params["outputSchema"]["properties"]


@pytest.mark.django_db(transaction=True)
def test_flag_change_cannot_retarget_a_previously_created_full_run(environment, settings):
    run, _, executor, calls = environment
    settings.GAMEFORGE_COMPACT_LITE_ENABLED = True
    process_run(str(run.id))
    saved = run.invocations.get().request
    assert saved['generation_profile'] == 'full'
    assert 'files' in saved['relay']['payload']['response_format']['json_schema']['schema']['properties']
    settings.GAMEFORGE_COMPACT_LITE_ENABLED = False
    executor.step()
    executor.step()
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == 'succeeded' and run.result_revision.generation_profile == 'full'
    assert run.invocations.get().request == saved and calls == [1]


@pytest.mark.django_db
@pytest.mark.browser
def test_factory_interface_error_repairs_game_module_despite_runtime_stack_frame(workspace):
    from copy import deepcopy

    from tests.test_compact_generation import SOURCE

    chat, _ = workspace
    run = create_run(chat, {
        'prompt': 'Три попадания', 'idempotency_key': 'bad-factory', 'generation_profile': 'compact',
    })
    requests = []

    def model(request, **kwargs):
        requests.append(deepcopy(request))
        if len(requests) == 1:
            response = compact_response(SOURCE.replace('input(e)', 'onInput(e)'))
        else:
            response = {'status': 'ok', 'message': 'Исправлен интерфейс', 'source': SOURCE}
        return {'response': response, 'usage': {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}}

    with patch('generation.providers.fake.generate', side_effect=model):
        process_run(str(run.id))
    run.refresh_from_db()
    first = run.revisions.first()
    assert requests[1]['operation'] == 'repair'
    assert requests[1]['module_repair']['files'] == {'game.js': first.file_hashes['game.js']}
    assert run.status == 'succeeded', run.error
    first, repaired = run.revisions.all()
    findings = first.reports.get().findings
    runtime = next(f for f in findings if f['code'] == 'runtime_or_network')
    missing = next(f for f in findings if f['code'] == 'module_not_registered')
    assert runtime['path'] == 'runtime.js' and missing['path'] == 'game.js'
    assert findings.index(runtime) < findings.index(missing)
    assert first.checks == repaired.checks and repaired.files['game.js'] == SOURCE
    assert all(repaired.files[p] == value for p, value in first.files.items() if p != 'game.js')


@pytest.mark.django_db(transaction=True)
def test_split_checks_stage_uses_durable_relay_uuid_and_never_regenerates_code(environment, monkeypatch):
    from studio.tests.test_planning_v2_workflow import browser, response_for

    run, _, executor, calls = environment
    run.generation_profile='compact'
    run.generation_strategy='lite_code_then_checks'
    run.save(update_fields=['generation_profile','generation_strategy'])
    def reply():
        request=run.invocations.order_by('-attempt').first().request
        return response_for(request)['response']
    monkeypatch.setattr('studio.tests.test_relay.fixture_response', reply)
    with patch('validation.service.validate', side_effect=browser):
        process_run(str(run.id))
        executor.step()
        executor.step()
        process_run(str(run.id))
        create, checks=run.invocations.order_by('attempt')
        assert create.state=='settled' and checks.state=='sent' and checks.request['operation']=='checks_create'
        process_run(str(run.id))
        assert run.revisions.count()==1 and run.invocations.count()==2
        executor.step()
        executor.step()
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status=='unverified',run.error
    first, second=run.revisions.order_by('number')
    assert first.files==second.files and first.artifact_hash==second.artifact_hash
    assert calls==[1,1] and run.invocations.count()==2
