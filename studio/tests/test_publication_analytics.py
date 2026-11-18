import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections, connections
from django.test import Client
from django.utils import timezone

from studio.models import (
    Chat,
    Feedback,
    FeedbackProcessing,
    Invocation,
    Like,
    PlaySession,
    Publication,
    PublicationRating,
    PublicationStats,
    Revision,
    Run,
    User,
)
from studio.publication_analytics import MAX_SESSION_MS, analytics_data


@pytest.fixture
def public_game(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    owner = User.objects.create_user(username="analytics-maker", password="test-password")
    chat = Chat.objects.create(owner=owner)
    html = "<!doctype html><canvas></canvas><script>const localRules = true;</script>"
    revision = Revision.objects.create(chat=chat, number=1, title="Local game", html=html,
        artifact_hash=hashlib.sha256(html.encode()).hexdigest(), files={"index.html": html})
    return Publication.objects.create(owner=owner, source_chat=chat, revision=revision, title="Published game")


def body(publication, **values):
    return {"session_id": str(uuid.uuid4()), "token": "ab" * 32,
            "revision_id": str(publication.revision_id), "artifact_hash": publication.revision.artifact_hash,
            **values}


def opened(publication, client=None):
    client = client or Client()
    data = body(publication)
    response = client.post(f"/api/publications/{publication.pk}/sessions/", data, content_type="application/json")
    assert response.status_code == 201, response.content
    return data, PlaySession.objects.get(pk=data["session_id"])


def send_time(publication, data, milliseconds, client=None):
    return (client or Client()).put(
        f"/api/publications/{publication.pk}/sessions/{data['session_id']}/",
        {"token": data["token"], "visible_ms": milliseconds}, content_type="application/json")


@pytest.mark.django_db
def test_existing_games_start_without_invented_stats_or_ratings(public_game):
    original = public_game.revision
    response = Client().get(f"/api/publications/{public_game.pk}/")
    assert response.status_code == 200
    assert response.json()["analytics"] == {
        "opens": 0, "average_duration_seconds": None, "successful_completions": None}
    assert response.json()["average_rating"] is None and response.json()["rating_count"] == 0
    assert response.json()["user_rating"] is None
    assert not PublicationStats.objects.exists() and not PlaySession.objects.exists()
    original.refresh_from_db()
    assert original.files == {"index.html": original.html}
    assert User.objects.filter(pk=public_game.owner_id).exists()


@pytest.mark.django_db
def test_repeat_open_is_new_session_but_network_retry_is_not(public_game):
    client = Client()
    data, session = opened(public_game, client)
    retry = client.post(f"/api/publications/{public_game.pk}/sessions/", data, content_type="application/json")
    assert retry.status_code == 200 and retry.json()["session_id"] == str(session.pk)
    assert "token" not in retry.json() and "token_hash" not in retry.json()
    assert session.token_hash != data["token"]
    opened(public_game, client)
    assert PlaySession.objects.count() == 2 and PublicationStats.objects.get().opens == 2


@pytest.mark.django_db
def test_session_binds_token_publication_and_exact_initial_version(public_game):
    client = Client()
    data, _ = opened(public_game)
    url = f"/api/publications/{public_game.pk}/sessions/"
    for changed in [{"token": "cd" * 32}, {"artifact_hash": "0" * 64}, {"revision_id": str(uuid.uuid4())}]:
        assert client.post(url, {**data, **changed}, content_type="application/json").status_code == 409
    second = Publication.objects.create(owner=public_game.owner, revision=public_game.revision, title="Other")
    assert client.post(f"/api/publications/{second.pk}/sessions/", data,
                       content_type="application/json").status_code == 409
    assert send_time(public_game, {**data, "token": "cd" * 32}, 10).status_code == 403
    assert PlaySession.objects.count() == 1 and PublicationStats.objects.get().opens == 1


@pytest.mark.django_db
def test_stale_first_open_rejected_but_old_session_keeps_version_snapshot(public_game, monkeypatch):
    data, session = opened(public_game)
    old_revision = public_game.revision
    new = Revision.objects.create(chat=public_game.source_chat, number=2, title="New", html="new game",
        artifact_hash="f" * 64, files={"index.html": "new game"})
    public_game.revision = new
    public_game.save(update_fields=["revision"])
    stale = {**data, "session_id": str(uuid.uuid4())}
    assert Client().post(f"/api/publications/{public_game.pk}/sessions/", stale,
                         content_type="application/json").status_code == 409
    monkeypatch.setattr("studio.publication_analytics.timezone.now", lambda: session.created_at + timedelta(seconds=5))
    assert send_time(public_game, data, 5000).status_code == 200
    session.refresh_from_db()
    assert session.revision_id_snapshot == old_revision.pk and session.artifact_hash == old_revision.artifact_hash
    assert session.visible_ms == 5000
    assert Client().post(f"/api/publications/{public_game.pk}/sessions/", data,
                         content_type="application/json").status_code == 200


@pytest.mark.django_db
def test_cumulative_duration_ignores_retries_and_stale_updates(public_game, monkeypatch):
    data, session = opened(public_game)
    current = session.created_at
    monkeypatch.setattr("studio.publication_analytics.timezone.now", lambda: current)
    current += timedelta(seconds=5)
    assert send_time(public_game, data, 5000).json()["visible_ms"] == 5000
    current += timedelta(seconds=5)
    assert send_time(public_game, data, 5000).json()["visible_ms"] == 5000
    assert send_time(public_game, data, 4000).json()["visible_ms"] == 5000
    assert send_time(public_game, data, 10000).json()["visible_ms"] == 10000
    assert analytics_data(Publication.objects.get(pk=public_game.pk))["average_duration_seconds"] == 10
    opened(public_game)
    assert analytics_data(Publication.objects.get(pk=public_game.pk))["average_duration_seconds"] == 5


@pytest.mark.django_db
def test_suspended_tabs_cannot_credit_hours_or_replay_discarded_time(public_game, monkeypatch):
    data, session = opened(public_game)
    current = session.created_at + timedelta(seconds=60)
    monkeypatch.setattr("studio.publication_analytics.timezone.now", lambda: current)
    assert send_time(public_game, data, 60000).json()["visible_ms"] == 15000
    current += timedelta(seconds=5)
    assert send_time(public_game, data, 65000).json()["visible_ms"] == 20000
    assert send_time(public_game, data, 1_000_000).json()["visible_ms"] == 20000
    current = session.created_at + timedelta(milliseconds=MAX_SESSION_MS + 1)
    assert send_time(public_game, data, 1_000_001).status_code == 410
    assert PublicationStats.objects.get().visible_ms == 20000


@pytest.mark.django_db
@pytest.mark.parametrize("duration", [True, -1, 1.5, "1000", None, MAX_SESSION_MS + 1])
def test_invalid_duration_does_not_change_counters(public_game, duration):
    data, _ = opened(public_game)
    assert send_time(public_game, data, duration).status_code == 400
    assert PublicationStats.objects.get().visible_ms == 0


@pytest.mark.django_db
def test_guest_writes_enforce_csrf_and_same_origin(public_game):
    client = Client(enforce_csrf_checks=True)
    data = body(public_game)
    url = f"/api/publications/{public_game.pk}/sessions/"
    assert client.post(url, data, content_type="application/json").status_code == 403
    token = client.get("/api/session/").json()["csrfToken"]
    assert client.post(url, data, content_type="application/json", HTTP_X_CSRFTOKEN=token,
                       HTTP_ORIGIN="https://foreign.example").status_code == 403
    assert client.post(url, data, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code == 201
    update = f"/api/publications/{public_game.pk}/sessions/{data['session_id']}/"
    assert client.put(update, {"token": data["token"], "visible_ms": 0},
                      content_type="application/json").status_code == 403
    assert client.put(update, {"token": data["token"], "visible_ms": 0},
                      content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code == 200


@pytest.mark.django_db
def test_ratings_are_per_user_editable_and_do_not_process_creator_feedback(public_game):
    client = Client()
    url = f"/api/publications/{public_game.pk}/rating/"
    assert client.put(url, {"rating": 5}, content_type="application/json").status_code == 403
    client.force_login(public_game.owner)
    Like.objects.create(publication=public_game, user=public_game.owner)
    assert client.put(url, {"rating": 5}, content_type="application/json").json() == {
        "average_rating": 5, "rating_count": 1, "user_rating": 5}
    client.put(url, {"rating": 3}, content_type="application/json")
    assert PublicationRating.objects.count() == 1
    other = User.objects.create_user(username="other-viewer")
    client.force_login(other)
    assert client.put(url, {"rating": 5}, content_type="application/json").json() == {
        "average_rating": 4, "rating_count": 2, "user_rating": 5}
    for invalid in [True, 0, 6, 4.5, "5"]:
        assert client.put(url, {"rating": invalid}, content_type="application/json").status_code == 400
    assert not Feedback.objects.exists() and not FeedbackProcessing.objects.exists()
    assert Like.objects.count() == 1 and PublicationRating.objects.count() == 2
    assert Client().get(f"/api/publications/{public_game.pk}/").json()["user_rating"] is None


@pytest.mark.django_db
def test_authenticated_rating_requires_csrf_and_same_origin(public_game):
    client = Client(enforce_csrf_checks=True)
    client.force_login(public_game.owner)
    url = f"/api/publications/{public_game.pk}/rating/"
    vote = {"rating": 5}
    assert client.put(url, vote, content_type="application/json").status_code == 403
    token = client.get("/api/session/").json()["csrfToken"]
    assert client.put(url, vote, content_type="application/json", HTTP_X_CSRFTOKEN=token,
                      HTTP_ORIGIN="https://foreign.example").status_code == 403
    assert not PublicationRating.objects.exists()
    assert client.put(url, vote, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code == 200
    assert PublicationRating.objects.get().rating == 5


@pytest.mark.django_db
def test_public_activity_preserves_offline_export_and_does_not_start_generation(public_game, monkeypatch):
    client = Client()
    client.force_login(public_game.owner)
    revision = public_game.revision
    export_url = f"/api/revisions/{revision.pk}/export/"
    source_url = f"/api/revisions/{revision.pk}/source/"
    before_export, before_source = client.get(export_url), client.get(source_url)
    assert before_export.status_code == before_source.status_code == 200
    assert before_export.content == revision.html.encode()
    data, session = opened(public_game)
    monkeypatch.setattr("studio.publication_analytics.timezone.now", lambda: session.created_at + timedelta(seconds=5))
    assert send_time(public_game, data, 5000).status_code == 200
    assert client.put(f"/api/publications/{public_game.pk}/rating/", {"rating": 5},
                      content_type="application/json").status_code == 200
    assert client.get(export_url).content == before_export.content
    assert client.get(source_url).json() == before_source.json()
    assert Revision.objects.count() == 1
    assert not Run.objects.exists() and not Invocation.objects.exists()
    assert not Feedback.objects.exists() and not FeedbackProcessing.objects.exists()


@pytest.mark.django_db
def test_popular_sort_uses_rating_then_count_without_like_join_multiplication(public_game):
    client = Client()
    client.force_login(public_game.owner)
    high = Publication.objects.create(owner=public_game.owner, revision=public_game.revision, title="High")
    empty = Publication.objects.create(owner=public_game.owner, revision=public_game.revision, title="Empty")
    users = [public_game.owner, User.objects.create_user(username="second-rater")]
    for user in users:
        PublicationRating.objects.create(publication=public_game, user=user, rating=4)
        Like.objects.create(publication=public_game, user=user)
    PublicationRating.objects.create(publication=high, user=users[0], rating=5)
    rows = client.get("/api/publications/?sort=popular").json()["results"]
    assert [r["id"] for r in rows] == [str(high.pk), str(public_game.pk), str(empty.pk)]
    assert rows[1]["average_rating"] == 4 and rows[1]["rating_count"] == 2
    assert rows[1]["likes"] == 2 and rows[1]["user_rating"] == 4


@pytest.mark.django_db
def test_unavailable_publications_reject_collection(public_game):
    data, _ = opened(public_game)
    public_game.unavailable_at = timezone.now()
    public_game.save(update_fields=["unavailable_at"])
    assert send_time(public_game, data, 5000).status_code == 410
    assert Client().post(f"/api/publications/{public_game.pk}/sessions/", body(public_game),
                         content_type="application/json").status_code == 410
    assert PublicationStats.objects.get().opens == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_retries_increment_one_open(public_game):
    gate = Barrier(2)
    data = body(public_game)
    def submit():
        close_old_connections()
        try:
            gate.wait(timeout=5)
            return Client().post(f"/api/publications/{public_game.pk}/sessions/", data,
                                 content_type="application/json").status_code
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: submit(), range(2)))
    assert statuses == [200, 201]
    assert PlaySession.objects.count() == 1 and PublicationStats.objects.get().opens == 1
