import uuid
from datetime import timedelta

import pytest

from studio.analytics_hints import HINTS, choose_analytics_hint
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


def signal():
    return choose_analytics_hint(prompt="Сделай космический шутер", audience="everyone")


def test_exact_public_version_has_sufficient_evidence_without_copying_authored_text(publication, django_assert_num_queries):
    play(publication, [30_000] * 4 + [29_999] * 4)
    rate(publication, [4, 4, 4])
    with django_assert_num_queries(3):
        hint = signal()
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
    hint = choose_analytics_hint(prompt=prompt, audience="everyone")
    assert (hint["match_basis"], hint["theme"], hint["genre"]) == ("theme", "space", None)
    for precise in ("Сделай научную викторину про космос", "Сделай игру про космос без волн"):
        assert choose_analytics_hint(prompt=precise, audience="everyone") is None
    Publication.objects.filter(pk=publication.pk).update(title="Космическая игра")
    run = publication.revision.run
    run.game_plan = {"summary": "A forest game; press Space to jump.", "progression": "Волны врагов."}
    run.save(update_fields=["game_plan"])
    assert choose_analytics_hint(prompt=prompt, audience="everyone") is None


def test_explicit_constraints_genre_and_audience_are_respected(publication):
    play(publication, [35_000] * 8)
    rate(publication, [5] * 3)
    for prompt in ("космическая головоломка", "космос", "Шутер без волн", "Shooter without waves"):
        assert choose_analytics_hint(prompt=prompt, audience="everyone") is None
    assert choose_analytics_hint(prompt="шутер", audience="children") is None
    run = publication.revision.run
    run.game_plan = {"summary": "Космический шутер.", "mechanics": ["Без волн врагов."],
                     "request_reference": "Предусмотреть волны врагов"}
    run.save(update_fields=["game_plan"])
    assert signal() is None


def test_only_sessions_from_the_current_public_revision_and_artifact_count(publication):
    rate(publication, [5] * 4)
    play(publication, [40_000] * 7)
    play(publication, [40_000], revision_id_snapshot=uuid.uuid4())
    play(publication, [40_000], artifact_hash="0" * 64)
    assert signal() is None
    play(publication, [0] * 8)
    assert signal() is None
    play(publication, [30_000])
    assert signal()["sessions_count"] == 16


def test_old_votes_weak_support_and_removed_publications_are_skipped(publication):
    play(publication, [30_000] * 8)
    rate(publication, [5, 5])
    assert signal() is None
    rate_row = PublicationRating.objects.create(publication=publication, user=publication.owner, rating=1)
    assert signal() is None  # Two five-star and one one-star rating shrink below 3.5.
    rate_row.rating = 5
    rate_row.save()
    assert signal() is not None
    PublicationRating.objects.filter(pk=rate_row.pk).update(updated_at=publication.updated_at - timedelta(seconds=1))
    assert signal() is None
    rate_row.save()
    publication.unavailable_at = publication.updated_at
    publication.save(update_fields=["unavailable_at"])
    assert signal() is None
    publication.unavailable_at = None
    publication.save(update_fields=["unavailable_at"])
    Revision.objects.filter(pk=publication.revision_id).update(pipeline_version=1)
    assert signal() is None


def test_shrunk_rating_prefers_supported_four_and_a_half_stars_over_three_perfect_votes(publication):
    other = Publication.objects.create(owner=publication.owner, revision=publication.revision, title="Другой пример")
    for item in (publication, other):
        play(item, [35_000] * 8)
    rate(publication, [5] * 3)
    rate(other, [4, 5] * 4)
    assert signal()["source_publication_id"] == str(other.pk)
