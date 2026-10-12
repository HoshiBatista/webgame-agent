"""Failure diagnostics must retain useful causes while excluding local secrets."""

import json
from typing import Any, cast

import pytest

from prompt2play.legacy.worker.core import ProviderError
from prompt2play.legacy.worker.providers import parse_json
from prompt2play.workers.diagnostics import emit, exception_details, safe_message


def test_secrets_redacted_without_losing_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPT2PLAY_RUNNER_TOKEN", "private-runner-fixture")
    monkeypatch.setenv("CUSTOM_API_KEY", "private-api-fixture")
    message = safe_message(
        "Schema failed: private-runner-fixture private-api-fixture private-lease-fixture "
        "Bearer separate-secret https://person:password@localhost/a "
        "https://localhost/preview/id/?token=query-fixture&other=visible "
        'password="password-fixture"',
        ["private-lease-fixture"],
    )
    assert "Schema failed" in message and "other=visible" in message
    for secret in (
        "private-runner-fixture",
        "private-api-fixture",
        "private-lease-fixture",
        "separate-secret",
        "person:password",
        "query-fixture",
        "password-fixture",
    ):
        assert secret not in message
    assert len(safe_message("x" * 5000)) == 4000


def test_schema_failure_coordinates_survive_without_rejected_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rejected_value = "private-rejected-payload"
    try:
        cast(Any, parse_json)(
            json.dumps({"count": rejected_value}),
            {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
            },
        )
    except ProviderError as exc:
        details = exception_details(exc)
        emit("stage_failed", job_id="job-fixture", stage="plan", **details)
    output = capsys.readouterr().out
    record = json.loads(output)
    assert rejected_value not in output
    assert len(record["exceptions"]) == 1
    assert record["exceptions"][0]["structured_diagnostic"]["instance_path"] == ["count"]
    assert record["job_id"] == "job-fixture"
    assert record["exceptions"][0]["frames"]
    assert "locals" not in output


def test_exception_chain_and_json_messages_are_bounded_and_valid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        try:
            raise ValueError('missing "transition"\nfrom state')
        except ValueError as cause:
            raise cast(Any, ProviderError)("plan rejected") from cause
    except ProviderError as exc:
        emit("stage_failed", **exception_details(exc))
    record = json.loads(capsys.readouterr().out)
    assert [item["type"] for item in record["exceptions"]] == ["ProviderError", "ValueError"]
    assert '"transition"\n' in record["exceptions"][1]["message"]


def test_receipt_keeps_token_counters(capsys: pytest.CaptureFixture[str]) -> None:
    emit("model_receipt", invocation_key="author:abc", usage={"total_tokens": 321})
    record = json.loads(capsys.readouterr().out)
    assert record["usage"]["total_tokens"] == 321
    assert record["timestamp"].endswith("+00:00")


def test_provider_failure_preserves_cause_not_transcript(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prompt2play.workers.provider_diagnostics import codex_diagnostic

    monkeypatch.setenv("PRIVATE_API_KEY", "secret-value-fixture")
    events, stderr = tmp_path / "events", tmp_path / "stderr"
    events.write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                {"type": "item.completed", "item": {"text": "private-generated-source"}},
                {
                    "type": "turn.failed",
                    "error": {
                        "code": "context_length_exceeded",
                        "message": "Context window exceeded. secret-value-fixture prompt=private-user-prompt",
                    },
                },
            ]
        )
    )
    stderr.write_text("private unrelated output")
    diagnostic = codex_diagnostic(events, stderr, 7)
    assert diagnostic["category"] == "context_length"
    assert diagnostic["code"] == "context_length_exceeded"
    assert diagnostic["exit_code"] == 7
    serialized = json.dumps(diagnostic)
    for secret in (
        "private-generated-source",
        "secret-value-fixture",
        "private-user-prompt",
        "private unrelated output",
    ):
        assert secret not in serialized
    error = cast(Any, ProviderError)("provider failed")
    error.provider_diagnostic = diagnostic
    assert exception_details(error)["exceptions"][0]["provider_diagnostic"] == diagnostic
    events.write_text("not-json")
    assert codex_diagnostic(events, stderr, 1)["category"] == "unknown"
    stderr.write_text("error: unexpected argument --unknown\nprivate prompt")
    assert codex_diagnostic(events, stderr, 2)["category"] == "configuration"
