from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from generation.providers.fake import generate as fake_generate
from studio.models import Chat, User
from studio.services import DomainError, create_run
from studio.tasks import process_run


@pytest.fixture
def chat(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3
    settings.GAMEFORGE_RUN_INLINE = False
    with patch("studio.services.schedule"), patch("studio.tasks.dispatch_outbox"), patch("studio.tasks.dispatch_run"):
        yield Chat.objects.create(owner=User.objects.create_user(username="budget-maker"))


@pytest.mark.django_db
@pytest.mark.parametrize("budget", [{"model_call_limit": True}, {"model_call_limit": 5},
                                    {"model_call_limit": 0}, {"model_call_deadline": "2026-10-24T10:00:00"}])
def test_invalid_call_budget_is_rejected_before_scheduling(chat, budget):
    with pytest.raises(DomainError, match="Лимит|ISO"):
        create_run(chat, {"prompt": "game", "idempotency_key": "budget", **budget})
    assert not chat.runs.exists()


@pytest.mark.django_db
def test_expired_deadline_cannot_send_a_model_call(chat):
    run = create_run(chat, {"prompt": "game", "idempotency_key": "deadline",
                           "model_call_deadline": (timezone.now() - timedelta(seconds=1)).isoformat()})
    with patch("generation.service.generate") as model:
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention" and run.error["code"] == "model_deadline"
    assert run.attempts == model.call_count == 0
    assert not run.invocations.exists()


@pytest.mark.django_db
def test_call_limit_survives_repeated_worker_execution_and_idempotent_retry(chat):
    data = {"prompt": "game", "idempotency_key": "one", "model_call_limit": 1}
    run = create_run(chat, data)
    assert create_run(chat, data).id == run.id
    with pytest.raises(DomainError):
        create_run(chat, {**data, "model_call_limit": 2})
    with patch("generation.service.generate", side_effect=fake_generate) as model, \
            patch("validation.service.validate", return_value={"status": "failed", "findings": [
                {"code": "runtime", "message": "Real runtime error"}], "facts": []}):
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.max_model_calls == run.attempts == model.call_count == 1
    assert run.status == "needs_attention" and run.candidate_revision_id
