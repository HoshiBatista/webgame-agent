"""PostgreSQL-backed API and workflow integration without paid model calls."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

import prompt2play.api.app as api_module
import prompt2play.application.workflow as workflow_module
from prompt2play.adapters.artifacts import ArtifactStore
from prompt2play.application.ports import ModelResult
from prompt2play.application.workflow import generate_run, specify_run, validate_run
from prompt2play.auth import hash_password
from prompt2play.config import Settings, get_settings
from prompt2play.contracts import GameSpec, GeneratedGame, Rubric
from prompt2play.db import SessionLocal, engine
from prompt2play.models import Base, GenerationRun, Revision, User

pytestmark = pytest.mark.integration


class FakeGateway:
    """Deterministic provider adapter used only at the integration boundary."""

    def __init__(self) -> None:
        self.learning_contexts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-golden-model"

    def specify(self, prompt: str, analytics_context: str) -> ModelResult[GameSpec]:
        assert prompt
        assert analytics_context
        self.learning_contexts.append(analytics_context)
        value = GameSpec(
            title="Golden Bee",
            genre="arcade",
            audience="дети и семья",
            player_goal="Запустить игру",
            core_loop="Нажимать большую кнопку и менять состояние",
            controls=["pointer", "touch", "keyboard"],
            visual_direction="Контрастные крупные формы",
            accessibility=["крупные кнопки"],
            win_condition="Цель выполнена",
            lose_condition="Закончились жизни",
            rubrics=[
                Rubric(id=f"r{index}", description="Проверяемое действие", verification="bridge")
                for index in range(3)
            ],
        )
        return ModelResult(value, "spec-response", 10, 20, 5)

    def generate(
        self,
        prompt: str,
        spec: GameSpec,
        *,
        parent_html: str | None = None,
        revision_instruction: str | None = None,
        findings: str | None = None,
        feedback_context: str | None = None,
    ) -> ModelResult[GeneratedGame]:
        del prompt, spec, parent_html, revision_instruction, findings, feedback_context
        html = (Path(__file__).parents[2] / "golden/smoke-game/index.html").read_text(
            encoding="utf-8"
        )
        return ModelResult(
            GeneratedGame(title="Golden Bee", summary="Validated fixture game", html=html),
            "game-response",
            30,
            40,
            8,
        )


@pytest.fixture(scope="module", autouse=True)
def postgres_schema() -> Iterator[None]:
    if os.environ.get("P2P_INTEGRATION_TESTS") != "1":
        pytest.skip("Set P2P_INTEGRATION_TESTS=1 with a real PostgreSQL database")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def test_api_generation_validation_revision_and_analytics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        browser_validation=True,
        public_base_url="http://testserver",
    )
    store = ArtifactStore(settings.artifact_root)
    monkeypatch.setattr(api_module, "_try_dispatch", lambda: None)
    monkeypatch.setattr(
        workflow_module,
        "validate_in_browser",
        lambda _path, _timeout: (
            True,
            [],
            ["browser_boot", "bridge_reset", "mobile_pointer_state_change"],
        ),
    )
    app = api_module.create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    with SessionLocal.begin() as session:
        session.add_all(
            [
                User(
                    username="Creator",
                    username_normalized="creator",
                    password_hash=hash_password("creator-password-123"),
                    is_admin=True,
                ),
                User(
                    username="Outsider",
                    username_normalized="outsider",
                    password_hash=hash_password("outsider-password-123"),
                ),
            ]
        )

    with TestClient(app) as client:
        assert client.get("/v1/projects").status_code == 401
        login = client.post(
            "/v1/auth/login",
            json={"username": "creator", "password": "creator-password-123"},
        )
        assert login.status_code == 200
        assert login.json()["username"] == "Creator"
        assert "HttpOnly" in login.headers["set-cookie"]
        created = client.post(
            "/v1/projects",
            json={"prompt": "Сделай аркаду про пчелу для детей"},
            headers={"Idempotency-Key": "integration-create"},
        )
        assert created.status_code == 202
        ids = created.json()
        repeated = client.post(
            "/v1/projects",
            json={"prompt": "Сделай аркаду про пчелу для детей"},
            headers={"Idempotency-Key": "integration-create"},
        )
        assert repeated.status_code == 202
        assert repeated.json() == ids
        conflict = client.post(
            "/v1/projects",
            json={"prompt": "Сделай совершенно другую игру"},
            headers={"Idempotency-Key": "integration-create"},
        )
        assert conflict.status_code == 409

        gateway = FakeGateway()
        from uuid import UUID

        run_id = UUID(ids["run_id"])
        assert specify_run(SessionLocal, lambda: gateway, run_id)
        assert generate_run(SessionLocal, lambda: gateway, store, run_id)
        assert validate_run(SessionLocal, store, settings, run_id)

        run_response = client.get(f"/v1/runs/{run_id}")
        assert run_response.json()["state"] == "succeeded"
        revision_id = cast(str, run_response.json()["revision_id"])

        project_response = client.get(f"/v1/projects/{ids['project_id']}")
        assert project_response.status_code == 200
        assert project_response.json()["current_revision_id"] == revision_id

        client.post("/v1/auth/logout")
        outsider_login = client.post(
            "/v1/auth/login",
            json={"username": "OUTSIDER", "password": "outsider-password-123"},
        )
        assert outsider_login.status_code == 200
        assert client.get(f"/v1/projects/{ids['project_id']}").status_code == 404
        assert client.get(f"/v1/runs/{run_id}").status_code == 404
        client.post("/v1/auth/logout")
        assert (
            client.post(
                "/v1/auth/login",
                json={"username": "Creator", "password": "creator-password-123"},
            ).status_code
            == 200
        )

        preview = client.get(f"/v1/revisions/{revision_id}/preview")
        assert preview.status_code == 200
        assert "default-src 'none'" in preview.headers["content-security-policy"]

        published = client.post(f"/v1/revisions/{revision_id}/publish")
        assert published.status_code == 200
        assert "/play/" in published.json()["share_url"]
        public_game_id = published.json()["public_game_id"]
        feed = client.get("/v1/public-games")
        assert feed.status_code == 200
        assert feed.json()[0]["author_username"] == "Creator"
        renamed = client.put(
            f"/v1/public-games/{public_game_id}", json={"title": "Golden Community Game"}
        )
        assert renamed.json()["title"] == "Golden Community Game"
        liked = client.put(f"/v1/public-games/{public_game_id}/like")
        assert liked.json()["like_count"] == 1
        assert liked.json()["liked_by_me"] is True
        remixed = client.post(f"/v1/public-games/{public_game_id}/remix", json={})
        assert remixed.status_code == 201
        assert remixed.json()["forked_from_revision_id"] == revision_id
        assert remixed.json()["current_revision_id"] is not None

        analytics = client.post(
            f"/v1/revisions/{revision_id}/analytics",
            json={"session_id": "integration-session", "event_type": "win", "payload": {}},
        )
        assert analytics.status_code == 204
        summary = client.get("/v1/analytics/summary").json()
        assert summary == [{"genre": "arcade", "event": "win", "count": 1}]

        feedback = client.post(
            f"/v1/revisions/{revision_id}/feedback",
            json={
                "rating": 3,
                "reasons": ["music"],
                "comment": "Не хватает крутой музыки",
            },
        )
        assert feedback.status_code == 200
        assert feedback.json()["rating"] == 3

        events = client.get(f"/v1/runs/{run_id}/events")
        assert events.status_code == 200
        assert "event: succeeded" in events.text

        revised = client.post(
            f"/v1/revisions/{revision_id}/revise",
            json={"instruction": "Добавь второй уровень"},
            headers={"Idempotency-Key": "integration-revise"},
        )
        assert revised.status_code == 202
        revised_run_id = UUID(revised.json()["run_id"])
        assert specify_run(SessionLocal, lambda: gateway, revised_run_id)
        assert "музыка и звуковой дизайн" in gateway.learning_contexts[-1]
        cancel = client.post(f"/v1/runs/{revised_run_id}/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["project_id"] == ids["project_id"]
        assert cancel.json()["state"] == "cancelled"

        exported = client.get(f"/v1/revisions/{revision_id}/export?format=zip")
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        restored = client.post(f"/v1/revisions/{revision_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["current_revision_id"] == revision_id
        assert restored.json()["messages"][0]["text"] == "Сделай аркаду про пчелу для детей"
        assert client.get(f"/v1/projects/{ids['project_id']}/feedback").json()[0]["rating"] == 3
        mine = client.get("/v1/public-games?sort=popular&mine=true")
        assert mine.status_code == 200
        assert mine.json()[0]["id"] == public_game_id

        assert client.delete(f"/v1/projects/{ids['project_id']}").status_code == 204
        assert client.get(f"/v1/projects/{ids['project_id']}").status_code == 404
        assert client.get(f"/v1/revisions/{revision_id}/export").status_code == 404
        # A publication survives chat archival, can still be played and remixed.
        assert client.get(published.json()["share_url"]).status_code == 200
        assert client.post(f"/v1/public-games/{public_game_id}/remix", json={}).status_code == 201
        assert client.delete(f"/v1/public-games/{public_game_id}").status_code == 204
        assert client.get(published.json()["share_url"]).status_code == 404
        assert client.get(f"/v1/projects/{remixed.json()['id']}").status_code == 200

    with SessionLocal() as session:
        stored_run = session.get(GenerationRun, run_id)
        assert stored_run is not None and stored_run.state == "succeeded"
        revision = session.get(Revision, stored_run.revision_id)
        assert revision is not None and revision.status == "validated"
