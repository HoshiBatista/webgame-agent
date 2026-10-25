import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from generation.artifacts import materialize, sha256
from generation.providers.fake import generate as fake_generate
from studio.models import Chat, Publication, User
from studio.services import create_run
from studio.tasks import process_run, recover_expired, request_for

PASS = {"status": "passed", "findings": [], "facts": []}
FAIL = {"status": "failed", "findings": [{"code": "effect_mismatch", "check_id": "tap",
         "before": 0, "after": 0}], "facts": []}


@pytest.fixture
def chat(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3
    settings.GAMEFORGE_LEASE_SECONDS = 100
    with patch("studio.services.schedule"), patch("studio.tasks.dispatch_outbox"), patch("studio.tasks.dispatch_run"):
        yield Chat.objects.create(owner=User.objects.create_user(username="source-maker"))


def start(chat, key="create", **kwargs):
    chat.refresh_from_db()
    data = {"prompt": "Небольшая игра", "idempotency_key": key, **kwargs}
    if chat.current_revision:
        data.update(source_revision_id=str(chat.current_revision_id),
                    source_artifact_hash=chat.current_revision.artifact_hash)
    return create_run(chat, data)


def stub(request, **kwargs):
    result = fake_generate(request, **kwargs)
    result["response"]["files"] = [{"path": "index.html", "content": "<!DOCTYPE html> <!-- line -->"}]
    result["raw_response"] = json.dumps(result["response"])
    result["usage"] = {"input_tokens": 20, "output_tokens": 30, "cached_input_tokens": 0}
    return result


def module_model(request, **kwargs):
    result = fake_generate(request, **kwargs)
    if request["operation"] == "repair":
        result["response"]["patches"] = [{"action": "replace_module", "path": "game.js",
            "file_hash": sha256(request["files"]["game.js"]),
            "content": request["files"]["game.js"] + "\n// focused module fix\n"}]
    return result


@pytest.mark.django_db
def test_stub_then_complete_create_preserves_raw_reply_and_shared_budget(chat):
    run = start(chat)
    calls = []

    def model(request, **kwargs):
        calls.append(deepcopy(request))
        return stub(request, **kwargs) if len(calls) == 1 else fake_generate(request, **kwargs)

    with patch("generation.service.generate", side_effect=model), patch("validation.service.validate", return_value=PASS) as browser:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded" and run.attempts == 2 and run.max_model_calls == 4
    assert [c["operation"] for c in calls] == ["create", "create"]
    assert calls[1]["base_revision"] is None and not calls[1]["files"]
    assert calls[1]["last_attempt_error"]["code"] == "incomplete_sources"
    assert run.revisions.count() == browser.call_count == 1
    inv = run.invocations.order_by("attempt").first()
    assert inv.error["code"] == "incomplete_sources" and inv.revision_id is None
    assert json.loads(inv.raw_response) == inv.response and inv.usage["output_tokens"] == 30
    assert inv.cost_usd is not None and inv.finished_at and inv.state == "settled"
    assert run.events.filter(kind="incomplete_sources").exists()


@pytest.mark.django_db
def test_repeated_stubs_stop_without_a_candidate_or_browser_call(chat):
    run = start(chat, model_call_limit=2)
    with patch("generation.service.generate", side_effect=stub) as model, patch("validation.service.validate") as browser:
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.error["code"] == "incomplete_sources"
    assert model.call_count == run.attempts == run.invocations.count() == 2
    assert not run.candidate_revision_id and not run.revisions.exists()
    browser.assert_not_called()


@pytest.mark.django_db
def test_module_repair_uses_saved_permission_and_inherits_all_checks(chat):
    run = start(chat)
    with patch("generation.service.generate", side_effect=module_model) as model, \
            patch("validation.service.validate", side_effect=[FAIL, PASS]):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded" and run.attempts == 2
    request = model.call_args_list[1].args[0]
    first, second = run.revisions.all()
    assert request["module_repair"]["files"] == {"game.js": first.file_hashes["game.js"]}
    assert second.parent_id == first.id and second.checks == first.checks
    for path in ("index.html", "styles.css"):
        assert second.files[path] == first.files[path]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("boundary", ["stub", "module"])
def test_crash_after_receipt_recovers_exact_reply_without_duplicate_inference(chat, boundary):
    from studio.tasks import store_candidate

    run = start(chat)
    real_materialize = materialize

    def crash_pack(response, **kwargs):
        if boundary == "stub":
            raise KeyboardInterrupt
        return real_materialize(response, **kwargs)

    def crash_store(current, artifact, base):
        if boundary == "module" and base:
            raise KeyboardInterrupt
        return store_candidate(current, artifact, base)

    with patch("generation.service.generate", side_effect=stub if boundary == "stub" else module_model) as model, \
            patch("generation.artifacts.materialize", side_effect=crash_pack), \
            patch("studio.tasks.store_candidate", side_effect=crash_store), \
            patch("validation.service.validate", return_value=FAIL):
        with pytest.raises(KeyboardInterrupt):
            process_run(str(run.id))
    run.refresh_from_db()
    assert model.call_count == (1 if boundary == "stub" else 2)
    ids = list(run.invocations.values_list("id", flat=True))
    run.lease_until = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["lease_until"])
    recover_expired()
    with patch("generation.service.generate", side_effect=fake_generate) as resumed, \
            patch("validation.service.validate", return_value=PASS):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert resumed.call_count == (1 if boundary == "stub" else 0)
    assert run.attempts == 2 and run.invocations.filter(pk__in=ids).count() == len(ids)


@pytest.mark.django_db
def test_cancellation_after_module_reply_preserves_receipt_without_applying_it(chat):
    run = start(chat)

    def cancel(request, **kwargs):
        result = module_model(request, **kwargs)
        if request["operation"] == "repair":
            type(run).objects.filter(pk=run.id).update(status="cancelled", cancel_requested=True)
        return result

    with patch("generation.service.generate", side_effect=cancel), patch("validation.service.validate", return_value=FAIL):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "cancelled" and run.revisions.count() == 1
    inv = run.invocations.get(attempt=2)
    assert inv.state == "returned" and inv.response["patches"][0]["action"] == "replace_module"
    assert not inv.revision_id and not run.result_revision_id


@pytest.mark.django_db
def test_cosmetic_edit_does_not_authorize_replacing_untouched_working_js(chat):
    run = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate), patch("validation.service.validate", return_value=PASS):
        process_run(str(run.id))
    chat.refresh_from_db()
    working = chat.current_revision
    publication = Publication.objects.create(owner=chat.owner, source_chat=chat, revision=working, title="Saved")
    edit = start(chat, "edit", prompt="Перекрась фон")
    edit.max_repair_attempts = 0
    edit.save(update_fields=["max_repair_attempts"])
    with patch("generation.service.generate", side_effect=fake_generate), patch("validation.service.validate", return_value=FAIL):
        process_run(str(edit.id))
    edit.refresh_from_db()
    req = request_for(edit, edit.candidate_revision, FAIL["findings"])
    assert not req["module_repair"]["files"]
    chat.refresh_from_db()
    publication.refresh_from_db()
    assert chat.current_revision_id == publication.revision_id == working.id
    assert working.files["game.js"] == edit.candidate_revision.files["game.js"]


@pytest.mark.django_db
def test_failed_module_repair_after_edit_keeps_accepted_game_and_publication(chat):
    original = start(chat)
    with patch("generation.service.generate", side_effect=fake_generate), patch("validation.service.validate", return_value=PASS):
        process_run(str(original.id))
    chat.refresh_from_db()
    working = chat.current_revision
    publication = Publication.objects.create(owner=chat.owner, source_chat=chat, revision=working, title="Published")
    run = start(chat, "edit")

    def model(request, **kwargs):
        result = module_model(request, **kwargs)
        if request["operation"] == "edit":
            result["response"]["patches"] = [{"path": "game.js", "file_hash": working.file_hashes["game.js"],
                "old_text": "#5879e8", "new_text": "#c05050"}]
        return result

    with patch("generation.service.generate", side_effect=model) as generate, \
            patch("validation.service.validate", return_value=FAIL):
        process_run(str(run.id))
    run.refresh_from_db()
    chat.refresh_from_db()
    publication.refresh_from_db()
    assert generate.call_count == 2 and run.status == "needs_attention"
    repair_request = generate.call_args.args[0]
    assert repair_request["module_repair"]["files"] == {"game.js": sha256(repair_request["files"]["game.js"])}
    assert repair_request["files"]["game.js"] != working.files["game.js"]
    assert chat.current_revision_id == publication.revision_id == working.id
    assert not run.candidate_revision.accepted and run.result_revision_id is None


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
def test_two_modules_with_identical_syntax_errors_are_repaired_in_order_in_real_browser(chat):
    run = start(chat)
    repaired = []

    def model(request, **kwargs):
        result = fake_generate(request, **kwargs)
        response = result["response"]
        if request["operation"] == "create":
            for item in response["files"]:
                if item["path"] == "index.html":
                    item["content"] = item["content"].replace("<script", '<script src="helper.js"></script><script', 1)
                elif item["path"] == "game.js":
                    item["content"] = "const second = ;\n" + item["content"]
            response["files"].append({"path": "helper.js", "content": "const first = ;\n"})
        else:
            name = next(iter(request["module_repair"]["files"]))
            repaired.append(name)
            response["patches"] = [{"action": "replace_module", "path": name,
                "file_hash": request["module_repair"]["files"][name],
                "content": request["files"][name].replace("= ;", "= 1;")}]
        return result

    with patch("generation.providers.fake.generate", side_effect=model):
        process_run(str(run.id))
    run.refresh_from_db()
    reports = list(run.check_reports.order_by("id"))
    assert [report.status for report in reports] == ["failed", "failed", "passed"]
    assert [report.findings[0]["path"] for report in reports[:2]] == ["helper.js", "game.js"]
    assert repaired == ["helper.js", "game.js"]
    assert run.status == "succeeded" and run.attempts == 3 and run.result_revision.accepted


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("flow", ["incomplete_create", "module_repair"])
def test_new_source_paths_reach_real_isolated_browser_acceptance(chat, flow):
    run = start(chat)
    count = 0

    def model(request, **kwargs):
        nonlocal count
        count += 1
        if flow == "incomplete_create":
            return stub(request, **kwargs) if count == 1 else fake_generate(request, **kwargs)
        result = fake_generate(request, **kwargs)
        if request["operation"] == "create":
            for entry in result["response"]["files"]:
                if entry["path"] == "game.js":
                    # A proven source fault retains code repair in v6; ambiguous
                    # gameplay mismatches use the separate scenario-review path.
                    entry["content"] = entry["content"].replace("gameState.hits++;", "gameState.hits+=0;") + "\nfunction broken("
        else:
            content = request["files"]["game.js"].replace("gameState.hits+=0;", "gameState.hits++;").replace("\nfunction broken(", "")
            result["response"]["patches"] = [{"action": "replace_module", "path": "game.js",
                "file_hash": request["module_repair"]["files"]["game.js"], "content": content}]
        return result

    # Exercise the real generation service, its provider schema, packaging and sandbox.
    with patch("generation.providers.fake.generate", side_effect=model):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert run.attempts == count == 2
    assert run.result_revision.accepted and run.result_revision.verification == "automatic"
    assert run.result_revision.reports.latest("id").status == "passed"
    assert run.revisions.count() == (1 if flow == "incomplete_create" else 2)
