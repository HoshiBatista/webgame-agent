from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connections
from django.test import Client

from generation.artifacts import sha256
from studio.models import Chat, Feedback, Invocation, Publication, Revision, User
from studio.serialization import revision_data


@pytest.fixture
def versions(client):
    owner = User.objects.create_user(username="version-owner")
    other = User.objects.create_user(username="version-other")
    client.force_login(owner)
    chat = Chat.objects.create(owner=owner)
    items = []
    for number in (1, 2):
        html = f"<canvas>Version {number}</canvas>"
        items.append(Revision.objects.create(
            files={}, chat=chat, number=number, title=f"Игра {number}", html=html, artifact_hash=sha256(html),
            accepted=number == 1, verification="automatic" if number == 1 else "none",
        ))
    chat.current_revision = items[0]
    chat.save(update_fields=["current_revision"])
    return owner, other, chat, items


def publish(client, chat, revision, **fields):
    return client.post("/api/publications/", {
        "chat_id": str(chat.pk), "revision_id": str(revision.pk), **fields,
    }, content_type="application/json")


@pytest.mark.django_db
def test_each_selected_version_has_its_own_publication_and_repeat_is_idempotent(client, versions):
    owner, _, chat, (first, draft) = versions
    created = publish(client, chat, draft, title="Мой черновик")
    assert created.status_code == 201
    assert created.json()["revision_id"] == str(draft.pk)
    assert created.json()["artifact_hash"] == draft.artifact_hash
    duplicate = publish(client, chat, draft, title="Повторный запрос")
    assert duplicate.status_code == 200 and duplicate.json()["id"] == created.json()["id"]
    assert duplicate.json()["title"] == "Мой черновик"
    second = publish(client, chat, first)
    assert second.status_code == 201 and second.json()["id"] != created.json()["id"]
    assert Publication.objects.filter(owner=owner).count() == 2
    data = client.get(f"/api/chats/{chat.pk}/").json()
    assert {r["id"]: r["publication"]["id"] for r in data["revisions"]} == {
        str(first.pk): second.json()["id"], str(draft.pk): created.json()["id"],
    }
    draft.refresh_from_db()
    chat.refresh_from_db()
    assert not draft.accepted and draft.verification == "none" and chat.current_revision_id == first.pk
    assert not Invocation.objects.exists()


@pytest.mark.django_db
def test_publishing_requires_owned_saved_supported_version_and_keeps_snapshots(client, versions):
    owner, other, chat, (first, draft) = versions
    foreign = Chat.objects.create(owner=other)
    alien = Revision.objects.create(files={}, chat=foreign, number=1, html="<canvas></canvas>")
    assert publish(client, chat, alien).status_code == 404
    assert publish(client, foreign, draft).status_code == 404
    empty = Revision.objects.create(files={}, chat=chat, number=3)
    assert publish(client, chat, empty).status_code == 400
    old = Revision.objects.create(files={}, chat=chat, number=4, html="old", pipeline_version=8)
    assert publish(client, chat, old).status_code == 404
    game = publish(client, chat, draft).json()
    source_html = draft.html
    Revision.objects.create(files={}, chat=chat, number=5, html="different game")
    publication = Publication.objects.get(pk=game["id"])
    assert publication.revision.html == source_html
    anonymous = Client()
    assert publish(anonymous, chat, draft).status_code == 403
    client.force_login(other)
    assert client.patch(f'/api/publications/{game["id"]}/', {"title": "X"}, content_type="application/json").status_code == 403
    remix = client.post(f'/api/publications/{game["id"]}/remix/', {}, content_type="application/json")
    assert remix.status_code == 201
    assert not remix.json()["current_revision"]["accepted"]
    assert remix.json()["current_revision"]["verification"] == "none"


@pytest.mark.django_db
def test_rename_preserves_version_and_patch_cannot_duplicate_another_publication(client, versions):
    _, _, chat, (first, draft) = versions
    a, b = publish(client, chat, first).json(), publish(client, chat, draft).json()
    url = f'/api/publications/{a["id"]}/'
    renamed = client.patch(url, {"title": "Другое имя"}, content_type="application/json")
    assert renamed.status_code == 200 and renamed.json()["revision_id"] == str(first.pk)
    collision = client.patch(url, {"title": "Не сохранять", "revision_id": str(draft.pk)}, content_type="application/json")
    assert collision.status_code == 409
    assert client.get(url).json()["title"] == "Другое имя"
    filtered = client.get(f'/api/publications/?mine=1&revision_id={draft.pk}').json()["results"]
    assert [p["id"] for p in filtered] == [b["id"]]
    assert client.delete(f'/api/publications/{b["id"]}/').status_code == 204
    assert revision_data(draft)["publication"] is None
    assert publish(client, chat, draft).status_code == 201


@pytest.mark.django_db
def test_feedback_is_bound_to_selected_draft_and_survives_reload(client, versions):
    _, other, chat, (first, draft) = versions
    with patch("studio.services.schedule") as schedule:
        result = client.post(f"/api/chats/{chat.pk}/feedback/", {
            "revision_id": str(draft.pk), "rating": 3, "reasons": ["Крупнее кнопки"],
        }, content_type="application/json")
    assert result.status_code == 201 and result.json()["revision_id"] == str(draft.pk)
    assert Feedback.objects.get().revision_id == draft.pk
    assert not schedule.called and not Invocation.objects.exists()
    assert revision_data(draft)["feedback_rating"] == 3
    assert revision_data(first)["feedback_rating"] is None
    assert client.get('/api/preferences/').json()["notes"] == []
    assert revision_data(draft)["feedback"]["custom_reason"] == "Крупнее кнопки"
    client.force_login(other)
    assert client.post(f"/api/chats/{chat.pk}/feedback/", {
        "revision_id": str(draft.pk), "rating": 5,
    }, content_type="application/json").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_simultaneous_publish_requests_cannot_create_duplicate_versions(client, versions):
    owner, _, chat, (_, draft) = versions
    barrier = Barrier(2)

    def submit(_):
        close_old_connections()
        try:
            browser = Client()
            browser.force_login(User.objects.get(pk=owner.pk))
            barrier.wait(timeout=10)
            result = publish(browser, chat, draft)
            return result.status_code, result.json()["id"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(submit, range(2)))
    assert sorted(status for status, _ in results) == [200, 201]
    assert len({ident for _, ident in results}) == 1
    assert Publication.objects.filter(owner=owner, revision=draft).count() == 1
