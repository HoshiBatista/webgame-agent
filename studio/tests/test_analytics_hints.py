import uuid
from datetime import timedelta

import pytest

from studio.analytics_hints import HINTS, choose_analytics_hints
from studio.models import Chat, PlaySession, Publication, PublicationRating, Revision, Run, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def publication():
    user = User.objects.create(username="designer")
    chat = Chat.objects.create(owner=user)
    run = Run.objects.create(
        chat=chat, operation="create", status="succeeded", audience="everyone",
        prompt="private brief", game_plan={"summary": "Космический шутер.", "progression": "Волны врагов."},
    )
    revision = Revision.objects.create(
        chat=chat, run=run, number=1, title="Игра", artifact_hash="a" * 64, files={}, html="<canvas></canvas>",
    )
    return Publication.objects.create(owner=user, source_chat=chat, revision=revision, title="secret-text")


def play(publication, durations, **snapshot):
    identity = {"revision_id_snapshot": publication.revision_id, "artifact_hash": publication.revision.artifact_hash}
    PlaySession.objects.bulk_create([
        PlaySession(id=uuid.uuid4(), publication=publication, visible_ms=ms, **(identity | snapshot))
        for ms in durations
    ])


def rate(publication, stars):
    for n, value in enumerate(stars):
        user, _ = User.objects.get_or_create(username=f"rater{n}")
        PublicationRating.objects.create(publication=publication, user=user, rating=value)


def signals():
    return choose_analytics_hints(prompt="Сделай космический шутер", audience="everyone")


def test_exact_public_version_has_sufficient_evidence_without_copying_authored_text(publication, django_assert_num_queries):
    play(publication, [30_000] * 4 + [29_999] * 4)
    rate(publication, [4, 4, 4])
    with django_assert_num_queries(3):
        [hint] = signals()
    assert hint == {
        "hint_key": "enemy_waves", "text": HINTS["enemy_waves"][1], "source_publication_id": str(publication.pk),
        "source_revision_id": str(publication.revision_id), "source_artifact_hash": "a" * 64,
        "match_basis": "genre", "genre": "shooter", "theme": None,
        "ratings_count": 3, "rating_mean": 4.0, "sessions_count": 8, "engaged_sessions": 4,
    }
    assert "secret-text" not in str(hint) and "private brief" not in str(hint)


def test_open_space_game_can_match_the_actual_setting_without_assuming_a_genre(publication):
    play(publication, [35_000] * 8)
    rate(publication, [5] * 3)
    prompt = "Сделай игру про космос!"
    [hint] = choose_analytics_hints(prompt=prompt, audience="everyone")
    assert (hint["match_basis"], hint["theme"], hint["genre"]) == ("theme", "space", None)
    for precise in ("Сделай научную викторину про космос", "Сделай игру про космос без волн"):
        assert choose_analytics_hints(prompt=precise, audience="everyone") == []
    Publication.objects.filter(pk=publication.pk).update(title="Космическая игра")
    run = publication.revision.run
    run.game_plan = {"summary": "A forest game; press Space to jump.", "progression": "Волны врагов."}
    run.save(update_fields=["game_plan"])
    assert choose_analytics_hints(prompt=prompt, audience="everyone") == []


def test_explicit_constraints_genre_and_audience_are_respected(publication):
    play(publication, [35_000] * 8)
    rate(publication, [5] * 3)
    for prompt in ("космическая головоломка", "космос", "Шутер без волн", "Shooter without waves"):
        assert choose_analytics_hints(prompt=prompt, audience="everyone") == []
    assert choose_analytics_hints(prompt="шутер", audience="children") == []
    run = publication.revision.run
    run.game_plan = {"summary": "Космический шутер.", "mechanics": ["Без волн врагов."],
                     "request_reference": "Предусмотреть волны врагов"}
    run.save(update_fields=["game_plan"])
    assert signals() == []


def test_only_sessions_from_the_current_public_revision_and_artifact_count(publication):
    rate(publication, [5] * 4)
    play(publication, [40_000] * 7)
    play(publication, [40_000], revision_id_snapshot=uuid.uuid4())
    play(publication, [40_000], artifact_hash="0" * 64)
    assert signals() == []
    play(publication, [0] * 8)
    assert signals() == []
    play(publication, [30_000])
    assert signals()[0]["sessions_count"] == 16


def test_old_votes_weak_support_and_removed_publications_are_skipped(publication):
    play(publication, [30_000] * 8)
    rate(publication, [5, 5])
    assert signals() == []
    rate_row = PublicationRating.objects.create(publication=publication, user=publication.owner, rating=1)
    assert signals() == []  # Two five-star and one one-star rating shrink below 3.5.
    rate_row.rating = 5
    rate_row.save()
    assert signals()
    PublicationRating.objects.filter(pk=rate_row.pk).update(updated_at=publication.updated_at - timedelta(seconds=1))
    assert signals() == []
    rate_row.save()
    publication.unavailable_at = publication.updated_at
    publication.save(update_fields=["unavailable_at"])
    assert signals() == []
    publication.unavailable_at = None
    publication.save(update_fields=["unavailable_at"])
    Revision.objects.filter(pk=publication.revision_id).update(pipeline_version=1)
    assert signals() == []


def test_shrunk_rating_prefers_supported_four_and_a_half_stars_over_three_perfect_votes(publication):
    other = Publication.objects.create(owner=publication.owner, revision=publication.revision, title="Другой пример")
    for item in (publication, other):
        play(item, [35_000] * 8)
    rate(publication, [5] * 3)
    rate(other, [4, 5] * 4)
    [hint] = signals()
    assert hint["source_publication_id"] == str(other.pk)


def test_one_publication_can_support_three_distinct_mechanics(publication, django_assert_num_queries):
    run = publication.revision.run
    run.game_plan = {
        "summary": "Космический шутер.",
        "mechanics": ["Волны врагов.", "Монеты на улучшения корабля.", "Выбор маршрута."],
        "progression": "Следующие волны врагов сложнее.",
    }
    run.save(update_fields=["game_plan"])
    play(publication, [30_000] * 8)
    rate(publication, [4] * 3)
    with django_assert_num_queries(3):
        hints = signals()
    assert [h["hint_key"] for h in hints] == ["enemy_waves", "resource_upgrade", "route_choice"]
    assert {h["source_publication_id"] for h in hints} == {str(publication.pk)}
    assert all(h["text"] == HINTS[h["hint_key"]][1] for h in hints)


def test_a_mechanic_already_requested_is_not_an_experimental_suggestion(publication):
    run = publication.revision.run
    run.game_plan = {"summary": "Шутер.", "mechanics": ["Волны врагов.", "Развилки маршрута."]}
    run.save(update_fields=["game_plan"])
    play(publication, [30_000] * 8)
    rate(publication, [4] * 3)
    for prompt, expected in [
        ("Шутер", ["enemy_waves", "route_choice"]),
        ("Шутер с волнами врагов", ["route_choice"]),
        ("Шутер с волнами врагов и развилками", []),
    ]:
        hints = choose_analytics_hints(prompt=prompt, audience="everyone")
        assert [hint["hint_key"] for hint in hints] == expected


def test_mechanics_from_different_sources_rank_by_their_best_evidence(publication, django_assert_num_queries):
    # The first game supplies a weaker example of waves and two unrelated mechanics.
    run = publication.revision.run
    run.game_plan = {"summary": "Космический шутер.", "mechanics": ["Волны врагов.", "Подсказки.", "Развилки."]}
    run.save(update_fields=["game_plan"])
    other_run = Run.objects.create(
        chat=run.chat, idempotency_key="second", operation="create", status="succeeded", audience="everyone",
        game_plan={"summary": "Шутер.", "mechanics": ["Волны врагов.", "Контрольные точки."]},
    )
    other_revision = Revision.objects.create(
        chat=run.chat, run=other_run, number=2, title="Игра 2", artifact_hash="b" * 64,
        files={}, html="<canvas></canvas>",
    )
    other = Publication.objects.create(owner=publication.owner, revision=other_revision, title="Второй шутер")
    for item in (publication, other):
        play(item, [30_000] * 8)
    rate(publication, [4] * 3)
    rate(other, [5] * 4)
    with django_assert_num_queries(3):
        hints = signals()
    assert [(h["hint_key"], h["source_revision_id"]) for h in hints] == [
        ("enemy_waves", str(other_revision.pk)), ("checkpoint", str(other_revision.pk)),
        ("optional_clue", str(publication.revision_id)),
    ]
    assert signals() == hints
