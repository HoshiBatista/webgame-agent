"""Bounded staged execution and restart safety, using local provider doubles only."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from generation.errors import GenerationError
from generation.providers.fake import generate as fixture_generate
from studio.models import Chat, User
from studio.serialization import revision_data
from studio.services import DomainError, create_run, reserve_invocation
from studio.tasks import process_run, recover_expired

SYNTAX = {"status": "failed", "findings": [
    {"code": "javascript_syntax", "message": "Unexpected end of input", "line": 1},
], "facts": [], "stages": [{"stage": "syntax", "status": "failed"}]}
GAMEPLAY = {"status": "failed", "findings": [
    {"code": "effect_mismatch", "check_id": "tap", "message": "Input had no effect",
     "before": 0, "after": 0, "expected": {"operator": "eq", "value": 1}},
], "facts": []}
PASS = {"status": "passed", "findings": [], "facts": [], "environment": "test"}


@pytest.fixture
def setup(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3
    settings.GAMEFORGE_LEASE_SECONDS = 100
    with (patch("studio.tasks.dispatch_run"),
          patch("studio.tasks.dispatch_outbox"),
          patch("validation.service.environment_identity", return_value="staged-test")):
        chat = Chat.objects.create(owner=User.objects.create_user(username="staged-maker"))
        yield chat


def new_run(chat):
    return create_run(chat, {"prompt": "Make a complete small game", "idempotency_key": "staged"})


@pytest.mark.django_db(transaction=True)
def test_stages_repair_only_current_problem_and_stop_on_success(setup):
    run = new_run(setup)
    with (patch("generation.service.generate", side_effect=fixture_generate) as model,
          patch("validation.service.validate", side_effect=[SYNTAX, GAMEPLAY, PASS]) as check):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert model.call_count == check.call_count == 3
    requests = [call.args[0] for call in model.call_args_list]
    assert [r["operation"] for r in requests] == ["create", "repair", "repair"]
    assert requests[1]["findings"][0]["code"] == "javascript_syntax"
    assert requests[2]["findings"][0]["code"] == "effect_mismatch"
    assert requests[1]["base_revision"] != requests[2]["base_revision"]
    assert run.check_reports.count() == 3
    first_report = run.check_reports.order_by("id").first()
    assert first_report.stages == [{"stage": "syntax", "status": "failed"}]
    assert revision_data(first_report.revision)["report"]["stages"] == first_report.stages
    assert run.events.filter(kind="repairing").count() == 2
    assert run.max_model_calls == 4


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("repairs", [2, 3])
@pytest.mark.parametrize("provider", ["fake", "codex"])
def test_allowance_is_frozen_and_failed_games_cannot_loop(setup, settings, repairs, provider):
    settings.GAMEFORGE_PROVIDER = provider
    settings.GAMEFORGE_MODEL = "fixture" if provider == "fake" else "gpt-6-luna"
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = repairs
    run = new_run(setup)
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3 if repairs == 2 else 2
    with (patch("generation.service.generate", side_effect=fixture_generate) as model,
          patch("validation.service.validate", return_value=GAMEPLAY)):
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention", run.error
    assert run.error["code"] == "repair_exhausted"
    assert run.max_repair_attempts == repairs
    assert run.attempts == model.call_count == run.invocations.count() == repairs + 1
    assert run.result_revision_id is None
    assert run.candidate_revision_id is not None
    assert run.invocations.filter(state="settled").count() == repairs + 1
    with pytest.raises(DomainError, match="Лимит исправлений"):
        reserve_invocation(run, {})


@pytest.mark.django_db(transaction=True)
def test_restart_between_checks_preserves_responses_and_remaining_allowance(setup, settings):
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 2
    run = new_run(setup)
    with (patch("generation.service.generate", side_effect=fixture_generate) as model,
          patch("validation.service.validate", side_effect=[SYNTAX, KeyboardInterrupt])):
        with pytest.raises(KeyboardInterrupt):
            process_run(str(run.id))
    assert model.call_count == 2
    run.refresh_from_db()
    first_ids = list(run.invocations.values_list("id", flat=True))
    run.lease_until = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["lease_until"])
    recover_expired()
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3
    with (patch("generation.service.generate", side_effect=fixture_generate) as model,
          patch("validation.service.validate", side_effect=[GAMEPLAY, PASS])):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert model.call_count == 1
    assert run.attempts == 3 and run.max_repair_attempts == 2
    assert run.invocations.filter(id__in=first_ids).count() == 2


@pytest.mark.django_db(transaction=True)
def test_unknown_execution_does_not_use_repair_allowance(setup):
    run = new_run(setup)
    with patch("generation.service.generate", side_effect=GenerationError(
            "connection_lost", "Result is unknown", outcome_unknown=True)) as model:
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "unknown" and model.call_count == 1
    assert run.invocations.get().state == "unknown"


@pytest.mark.django_db(transaction=True)
def test_format_failures_also_consume_the_same_finite_allowance(setup):
    from generation.errors import ContractError

    run = new_run(setup)
    with (patch("generation.service.generate", side_effect=ContractError(
            "invalid_schema", "Invalid format", raw_response='{"bad":true}',
            usage={"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5})) as model,
          patch("validation.service.validate") as check):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "needs_attention", run.error
    assert model.call_count == run.invocations.count() == 4
    assert all(i.raw_response == '{"bad":true}' for i in run.invocations.all())
    check.assert_not_called()
