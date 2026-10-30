import io
import json
from unittest.mock import patch

import pytest
from django.core.management import call_command

from generation.errors import GenerationError
from studio.models import Chat, Invocation, User
from studio.services import create_run
from studio.tasks import process_run


@pytest.mark.django_db(transaction=True)
def test_trace_is_durable_before_send_and_failure_does_not_repeat(settings, monkeypatch):
    settings.GAMEFORGE_PROVIDER = "vllm"
    settings.GAMEFORGE_MODEL = "diagnostic-test"
    monkeypatch.setenv("GAMEFORGE_PRICES_JSON", json.dumps({"diagnostic-test": {
        "input": 0, "cached": 0, "output": 0, "context_window": 32768, "max_output_tokens": 6144,
    }}))
    owner = User.objects.create_user(username="diagnostics-owner")
    chat = Chat.objects.create(owner=owner)

    def fail(request, **kwargs):
        inv = Invocation.objects.get(run=run)
        assert inv.state == "sent"
        assert inv.provider_metadata["trace_id"] == request["transport_trace_id"] == inv.id.hex
        raise GenerationError("provider_disconnected", "Failure", outcome_unknown=True,
                              raw_response="PRIVATE RESPONSE",
                              provider_metadata={"trace_id": inv.id.hex, "transport_error": "ReadTimeout"})

    with (
        patch("studio.tasks.process_run.delay"),
        patch("validation.service.environment_identity", return_value={"version": "test"}),
        patch("generation.service.generate", side_effect=fail) as model,
    ):
        run = create_run(chat, {"prompt": "PRIVATE PROMPT", "idempotency_key": "diagnostic", "model_profile": ""})
        process_run(str(run.id))
        process_run(str(run.id))
        model.assert_called_once()
    inv = Invocation.objects.get(run=run)
    assert inv.state == "unknown"
    assert inv.provider_metadata["transport_error"] == "ReadTimeout"
    output = io.StringIO()
    call_command("diagnose_invocation", str(inv.id), stdout=output)
    report = output.getvalue()
    assert json.loads(report)["metadata"]["trace_id"] == inv.id.hex
    assert "PRIVATE RESPONSE" not in report and "PRIVATE PROMPT" not in report
