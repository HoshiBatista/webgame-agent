import json
from pathlib import Path
from unittest.mock import patch

import pytest

from generation.audiences import AUDIENCES
from generation.prompts import build_messages
from studio.models import Chat, User
from studio.services import create_run
from studio.tasks import request_for


@pytest.mark.django_db
@pytest.mark.parametrize("audience", ["beginners", "family", "learning", "relax"])
def test_audience_is_accepted_frozen_and_reaches_planning_and_implementation(client, settings, audience):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    client.force_login(User.objects.create_user(username="audience-owner"))
    created = client.post("/api/chats/", {"audience": audience}, content_type="application/json")
    assert created.status_code == 201
    chat = Chat.objects.get(pk=created.json()["id"])
    with patch("studio.services.schedule"):
        run = create_run(chat, {"prompt": "Игра про сад", "audience": audience, "idempotency_key": "audience"})
    assert run.audience == audience and "audiences.py" in run.policy_snapshot["source_hashes"]
    request = request_for(run, None, [])
    for operation in ("plan", "create", "edit", "repair"):
        context = json.loads(build_messages({**request, "operation": operation})[1]["content"])
        assert context["audience"] == audience
        assert AUDIENCES[audience] in context["audience_guidance"]
        assert "not only colors" in context["audience_guidance"]
    assert Path(f"web/public/assets/audience-{audience}.svg").exists()
