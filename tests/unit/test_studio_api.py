"""Studio export, history and deletion policy without infrastructure."""

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from prompt2play.api.app import _request_hash, create_app, get_current_user
from prompt2play.config import Settings, get_settings
from prompt2play.db import get_session
from prompt2play.models import (
    GenerationRun,
    IdempotencyRecord,
    Project,
    PublicGame,
    Revision,
    User,
    utc_now,
)


@pytest.fixture
def studio_client(tmp_path: Path) -> Iterator[tuple[TestClient, Mock, User]]:
    app = create_app()
    user = User(id=uuid4(), username="creator", username_normalized="creator")
    session = Mock(spec=Session)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_settings] = lambda: Settings(artifact_root=tmp_path)
    with TestClient(app) as client:
        yield client, session, user


def test_archive_cancels_active_runs_without_deleting_artifacts(
    studio_client: tuple[TestClient, Mock, User],
) -> None:
    client, session, user = studio_client
    project = Project(id=uuid4(), owner_id=user.id, prompt="Сделай игру", archived=False)
    run = GenerationRun(
        id=uuid4(), project_id=project.id, prompt=project.prompt, state="generating"
    )
    session.scalar.side_effect = [project, 0]
    session.scalars.return_value.all.return_value = [run]

    response = client.delete(f"/v1/projects/{project.id}")

    assert response.status_code == 204
    assert project.archived is True
    assert run.state == "cancelled"
    assert run.cancel_requested is True
    session.delete.assert_not_called()
    session.commit.assert_called_once()


def test_revision_endpoint_accepts_uuid_and_replays_only_the_same_request(
    studio_client: tuple[TestClient, Mock, User],
) -> None:
    client, session, user = studio_client
    revision = Revision(id=uuid4(), project_id=uuid4(), status="validated")
    run = GenerationRun(id=uuid4(), project_id=revision.project_id)
    operation = f"revise:{user.id}"
    record = IdempotencyRecord(
        operation=operation,
        request_hash=_request_hash(operation, str(revision.id), "Добавь второй уровень"),
        project_id=run.project_id,
        run_id=run.id,
    )
    session.scalar.return_value = revision
    session.get.side_effect = [record, run, record, run, record]
    headers = {"Idempotency-Key": "retry-revision"}
    url = f"/v1/revisions/{revision.id}/revise"

    for _attempt in range(2):
        response = client.post(url, json={"instruction": "Добавь второй уровень"}, headers=headers)
        assert response.status_code == 202
        assert response.json() == {"project_id": str(run.project_id), "run_id": str(run.id)}

    conflict = client.post(url, json={"instruction": "Улучши музыку"}, headers=headers)
    assert conflict.status_code == 409
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize("format", ["html", "zip"])
def test_export_contains_the_exact_validated_artifact(
    studio_client: tuple[TestClient, Mock, User],
    tmp_path: Path,
    format: str,
) -> None:
    client, session, _user = studio_client
    html = "<!doctype html><html><body>Локальная игра</body></html>"
    digest = hashlib.sha256(html.encode()).hexdigest()
    artifact = tmp_path / "objects" / "sha256" / digest[:2] / digest[2:4] / digest
    artifact.mkdir(parents=True)
    (artifact / "index.html").write_text(html)
    revision = Revision(
        id=uuid4(), status="validated", artifact_digest=digest, model_name="fixture"
    )
    session.scalar.return_value = revision

    response = client.get(f"/v1/revisions/{revision.id}/export?format={format}")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    if format == "html":
        assert response.content.decode() == html
    else:
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            assert set(bundle.namelist()) == {"index.html", "metadata.json"}
            assert bundle.read("index.html").decode() == html
            assert json.loads(bundle.read("metadata.json"))["sha256"] == digest


def test_export_rejects_unvalidated_or_unowned_revisions(
    studio_client: tuple[TestClient, Mock, User],
) -> None:
    client, session, _user = studio_client
    revision = Revision(id=uuid4(), status="rejected")
    session.scalar.return_value = revision
    assert client.get(f"/v1/revisions/{revision.id}/export").status_code == 404
    session.scalar.return_value = None
    assert client.get(f"/v1/revisions/{revision.id}/export").status_code == 404


def test_tampered_artifact_is_never_returned_as_a_validated_download(
    studio_client: tuple[TestClient, Mock, User],
    tmp_path: Path,
) -> None:
    client, session, _user = studio_client
    original = "<!doctype html><title>original</title>"
    digest = hashlib.sha256(original.encode()).hexdigest()
    directory = tmp_path / "objects" / "sha256" / digest[:2] / digest[2:4] / digest
    directory.mkdir(parents=True)
    (directory / "index.html").write_text("changed after validation")
    revision = Revision(id=uuid4(), status="validated", artifact_digest=digest)
    session.scalar.return_value = revision

    response = client.get(f"/v1/revisions/{revision.id}/export?format=html")
    assert response.status_code == 503
    assert "changed after validation" not in response.text
    assert response.json()["detail"] == "Artifact integrity check failed"


def test_feed_orders_by_likes_and_filters_by_author(
    studio_client: tuple[TestClient, Mock, User],
) -> None:
    client, session, user = studio_client
    session.scalars.return_value.all.return_value = []

    assert client.get("/v1/public-games?sort=popular&mine=true").json() == []

    statement = session.scalars.call_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "count(*)" in sql
    assert "public_games.author_id" in sql
    assert user.id.hex in sql.replace("-", "")
    assert "DESC" in sql


def test_publication_removal_does_not_delete_the_project_or_revisions(
    studio_client: tuple[TestClient, Mock, User],
) -> None:
    client, session, user = studio_client
    game = PublicGame(id=uuid4(), project_id=uuid4(), author_id=user.id)
    revision = Revision(id=uuid4(), project_id=game.project_id, public_slug="legacy-link")
    session.scalar.return_value = game
    session.scalars.return_value.all.return_value = [revision]

    assert client.delete(f"/v1/public-games/{game.id}").status_code == 204

    session.delete.assert_called_once_with(game)
    assert revision.public_slug is None
    session.commit.assert_called_once()


def test_other_creators_cannot_remove_publications(
    studio_client: tuple[TestClient, Mock, User],
) -> None:
    client, session, user = studio_client
    session.scalar.return_value = None

    assert client.delete(f"/v1/public-games/{uuid4()}").status_code == 404

    session.delete.assert_not_called()
    query = session.scalar.call_args.args[0]
    sql = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert user.id.hex in sql.replace("-", "")


def test_rejected_revision_cannot_be_restored(
    studio_client: tuple[TestClient, Mock, User],
) -> None:
    client, session, _user = studio_client
    revision = Revision(id=uuid4(), status="rejected")
    session.scalar.return_value = revision

    assert client.post(f"/v1/revisions/{revision.id}/restore").status_code == 409
    session.commit.assert_not_called()


def test_restoring_a_revision_changes_only_the_private_current_version(
    studio_client: tuple[TestClient, Mock, User],
) -> None:
    client, session, user = studio_client
    project = Project(
        id=uuid4(),
        owner_id=user.id,
        title="Новая игра",
        prompt="Создай игру",
        current_revision_id=uuid4(),
        selection_version=0,
        created_at=utc_now(),
    )
    old = Revision(
        id=uuid4(),
        project_id=project.id,
        title="Прежняя версия",
        status="validated",
        genre="arcade",
        audience="все",
        model_name="fixture",
        created_at=utc_now(),
    )
    session.scalar.side_effect = [old, project, None]
    session.scalars.return_value.all.side_effect = [[old], []]

    response = client.post(f"/v1/revisions/{old.id}/restore")

    assert response.status_code == 200
    assert response.json()["current_revision_id"] == str(old.id)
    assert project.title == "Прежняя версия"
    assert project.selection_version == 1
    session.add.assert_not_called()
    session.delete.assert_not_called()
