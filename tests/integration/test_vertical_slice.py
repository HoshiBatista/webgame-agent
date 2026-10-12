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
from prompt2play.config import Settings, get_settings
from prompt2play.contracts import GameSpec, GeneratedGame, Rubric
from prompt2play.db import SessionLocal, engine
from prompt2play.models import Base, GenerationRun, Revision

pytestmark = pytest.mark.integration


class FakeGateway:
    """Deterministic provider adapter used only at the integration boundary."""

    @property
    def model_name(self) -> str:
        return "fake-golden-model"

    def specify(self, prompt: str, analytics_context: str) -> ModelResult[GameSpec]:
        assert prompt
        assert analytics_context
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
    ) -> ModelResult[GeneratedGame]:
        del prompt, spec, parent_html, revision_instruction, findings
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

    with TestClient(app) as client:
        created = client.post(
            "/v1/projects",
            json={"prompt": "Сделай аркаду про пчелу для детей"},
            headers={"Idempotency-Key": "integration-create"},
        )
        assert created.status_code == 202
        ids = created.json()

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

        preview = client.get(f"/v1/revisions/{revision_id}/preview")
        assert preview.status_code == 200
        assert "default-src 'none'" in preview.headers["content-security-policy"]

        published = client.post(f"/v1/revisions/{revision_id}/publish")
        assert published.status_code == 200
        assert "/play/" in published.json()["share_url"]

        analytics = client.post(
            f"/v1/revisions/{revision_id}/analytics",
            json={"session_id": "integration-session", "event_type": "win", "payload": {}},
        )
        assert analytics.status_code == 204
        summary = client.get("/v1/analytics/summary").json()
        assert summary == [{"genre": "arcade", "event": "win", "count": 1}]

        events = client.get(f"/v1/runs/{run_id}/events")
        assert events.status_code == 200
        assert "event: succeeded" in events.text

        revised = client.post(
            f"/v1/revisions/{revision_id}/revise",
            json={"instruction": "Добавь второй уровень"},
            headers={"Idempotency-Key": "integration-revise"},
        )
        assert revised.status_code == 202
        cancel = client.post(f"/v1/runs/{revised.json()['run_id']}/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["project_id"] == ids["project_id"]

    with SessionLocal() as session:
        stored_run = session.get(GenerationRun, run_id)
        assert stored_run is not None and stored_run.state == "succeeded"
        revision = session.get(Revision, stored_run.revision_id)
        assert revision is not None and revision.status == "validated"
