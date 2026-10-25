from unittest.mock import patch

import pytest
from django.test import Client

from generation.artifacts import materialize
from generation.providers.fake import fixture_response, generate
from studio.models import Chat, Revision, User
from studio.services import DomainError, create_run
from studio.tasks import process_run


@pytest.fixture
def workspace(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    settings.GAMEFORGE_RUN_INLINE = False
    user = User.objects.create_user(username="draft-maker")
    chat = Chat.objects.create(owner=user)
    client = Client()
    client.force_login(user)
    with (
        patch("studio.services.schedule"),
        patch("studio.tasks.dispatch_outbox"),
        patch("studio.tasks.dispatch_run"),
        patch("validation.service.environment_identity", return_value="draft-tests"),
    ):
        yield chat, client


def saved(chat, number=1, accepted=False):
    artifact = materialize(fixture_response(), operation="create")
    return Revision.objects.create(
        chat=chat,
        number=number,
        title="Сохранённая игра",
        accepted=accepted,
        **{k: artifact[k] for k in ["files", "html", "artifact_hash", "file_hashes", "design", "checks"]},
    )


def edit_data(source, key="edit"):
    return {
        "prompt": "Сделай фон тёплым",
        "idempotency_key": key,
        "source_revision_id": str(source.id),
        "source_artifact_hash": source.artifact_hash,
    }


@pytest.mark.django_db
@pytest.mark.parametrize('has_accepted_base', [False, True])
def test_draft_cosmetic_edit_cannot_replace_module_untouched_since_selected_source(workspace, has_accepted_base):
    from generation.artifacts import bundle, sha256
    from studio.tasks import request_for

    chat, _ = workspace
    accepted = saved(chat, accepted=True) if has_accepted_base else None
    if accepted:
        chat.current_revision = accepted
        chat.save(update_fields=['current_revision'])
    source = saved(chat, number=2 if accepted else 1)
    source.files['game.js'] += '\n// Earlier draft modification\n'
    source.html = bundle(source.files)
    source.artifact_hash = sha256(source.html)
    source.file_hashes = {p: sha256(c) for p, c in source.files.items()}
    source.save()
    run = create_run(chat, edit_data(source))
    candidate = saved(chat, number=source.number + 1)
    candidate.files = dict(source.files)
    candidate.files['styles.css'] += '\nbody{background:coral}\n'
    candidate.html = bundle(candidate.files)
    candidate.artifact_hash = sha256(candidate.html)
    candidate.file_hashes = {p: sha256(c) for p, c in candidate.files.items()}
    candidate.save()
    run.candidate_revision = candidate
    run.save(update_fields=['candidate_revision'])
    request = request_for(run, candidate, [{'code': 'runtime_or_network', 'path': 'game.js',
                                           'file_hash': candidate.file_hashes['game.js']}])
    assert request['operation'] == 'repair'
    assert request['module_repair']['files'] == {}


@pytest.mark.django_db
@pytest.mark.parametrize("accepted_base", [False, True])
def test_form_request_edits_exact_unaccepted_source_and_preserves_accepted_pointer(workspace, accepted_base):
    chat, client = workspace
    if accepted_base:
        accepted = saved(chat, accepted=True)
        chat.current_revision = accepted
        chat.save(update_fields=["current_revision"])
    draft = saved(chat, number=2 if accepted_base else 1)
    response = client.post(f"/api/chats/{chat.id}/runs/", edit_data(draft), content_type="application/json")
    assert response.status_code == 202, response.json()
    run = chat.runs.get()
    assert run.operation == "edit"
    assert run.source_revision_id == draft.id
    assert run.base_revision_id == (accepted.id if accepted_base else None)
    chat.refresh_from_db()
    assert chat.current_revision_id == run.base_revision_id
    with (
        patch("generation.service.generate", side_effect=generate) as model,
        patch("validation.service.validate", return_value={"status": "passed", "findings": [], "facts": []}),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    request = model.call_args.args[0]
    assert request["operation"] == "edit" and request["base_revision"] == str(draft.id)
    assert request["files"] == draft.files
    assert run.result_revision.parent_id == draft.id


@pytest.mark.django_db
def test_existing_game_requires_a_source_and_wrong_hash_or_owner_never_falls_back_to_create(workspace):
    chat, _ = workspace
    draft = saved(chat)
    for data, code in [
        ({"prompt": "Исправь", "idempotency_key": "missing"}, "source_required"),
        ({**edit_data(draft), "source_artifact_hash": "0" * 64}, "source_changed"),
    ]:
        with pytest.raises(DomainError) as error:
            create_run(chat, data)
        assert error.value.code == code
    other = Chat.objects.create(owner=User.objects.create_user(username="another-maker"))
    foreign = saved(other)
    with pytest.raises(DomainError) as error:
        create_run(chat, edit_data(foreign))
    assert error.value.code == "source_changed" and chat.runs.count() == 0


@pytest.mark.django_db
def test_historical_source_is_explicit_and_lost_response_reuses_exact_request(workspace):
    chat, _ = workspace
    first, second = saved(chat), saved(chat, number=2)
    with pytest.raises(DomainError) as error:
        create_run(chat, edit_data(first))
    assert error.value.code == "source_changed"
    payload = {**edit_data(first), "source_is_historical": True}
    run = create_run(chat, payload)
    assert create_run(chat, payload).id == run.id
    with pytest.raises(DomainError) as error:
        create_run(chat, edit_data(second))
    assert error.value.code == "idempotency_conflict"
