"""Provider failures stay billed/ambiguous; completed responses can be reused."""

from __future__ import annotations

from typing import Any, cast

import pytest

from prompt2play.generation.gateway import ProviderGateway
from prompt2play.generation.workspace import GenerationControl, GenerationStopped
from prompt2play.legacy.worker.core import ProviderError, Reply
from prompt2play.legacy.worker.providers import parse_json, portable_output_schema


class Journal:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.settlements: list[dict[str, Any]] = []
        self.completed: dict[str, Any] | None = None

    def reserve(
        self, key: str, reserved_tokens: int, operation: str, request_sha256: str
    ) -> dict[str, Any] | None:
        assert reserved_tokens > 0 and operation and request_sha256
        self.requests.append(key)
        return self.completed

    def settle(
        self, key: str, *, data: dict[str, Any] | None, usage: dict[str, int] | None, status: str
    ) -> None:
        self.settlements.append({"key": key, "data": data, "usage": usage, "status": status})


class ReplyProvider:
    def __init__(self, *, error: Exception | None = None, revoke: list[bool] | None = None) -> None:
        self.error, self.revoke = error, revoke
        self.calls = 0

    def generate(self, *args: Any, **kwargs: Any) -> Reply:
        del args, kwargs
        self.calls += 1
        if self.error:
            raise self.error
        if self.revoke is not None:
            self.revoke[0] = False
        return Reply(
            {"ok": True},
            {
                "input_tokens": 3,
                "cached_input_tokens": 0,
                "output_tokens": 4,
                "total_tokens": 7,
                "calls": 1,
            },
        )


def test_ambiguous_failure_is_not_replayed_and_reservation_remains_charged() -> None:
    journal = Journal()
    gateway = ProviderGateway("codex", "explicit", journal=journal)
    provider = ReplyProvider(error=cast(Any, ProviderError)("Network lost"))
    gateway.provider = provider
    control = GenerationControl.bounded()
    with pytest.raises(ProviderError):
        gateway.generate("prompt", {}, "plan", control)
    assert provider.calls == 1
    assert control.uncertain_tokens > 0
    assert journal.settlements[-1]["status"] == "interrupted_unknown"


def test_completed_matching_response_reuse_preserves_original_usage_without_paid_replay() -> None:
    journal = Journal()
    journal.completed = {
        "data": {"ok": True},
        "usage": {
            "input_tokens": 3,
            "cached_input_tokens": 0,
            "output_tokens": 4,
            "total_tokens": 7,
            "calls": 1,
        },
    }
    gateway = ProviderGateway("codex", "explicit", journal=journal)
    provider = ReplyProvider()
    gateway.provider = provider
    reply = gateway.generate("prompt", {}, "plan", GenerationControl.bounded())
    assert reply.reused and reply.usage["total_tokens"] == 7
    assert provider.calls == 0
    assert gateway.is_replay and gateway.records[-1]["status"] == "reused"
    journal.completed = None
    gateway.generate("different request", {}, "plan", GenerationControl.bounded())
    assert provider.calls == 1
    assert not gateway.is_replay


def test_stale_result_is_accounted_but_cannot_be_submitted() -> None:
    current = [True]
    journal = Journal()
    gateway = ProviderGateway("codex", "explicit", journal=journal)
    gateway.provider = ReplyProvider(revoke=current)
    control = GenerationControl.bounded(fence_check=lambda: current[0])
    with pytest.raises(GenerationStopped, match="fence"):
        gateway.generate("prompt", {}, "plan", control)
    assert control.usage["total_tokens"] == 7
    assert journal.settlements[0]["status"] == "completed"


def test_budget_rejection_before_provider_dispatch_is_recorded_as_zero_cost() -> None:
    journal = Journal()
    gateway = ProviderGateway("codex", "explicit", journal=journal)
    provider = ReplyProvider()
    gateway.provider = provider
    control = GenerationControl.bounded(token_limit=1)
    with pytest.raises(GenerationStopped, match="Cannot reserve"):
        gateway.generate("prompt", {}, "plan", control)
    assert provider.calls == 0
    assert control.uncertain_tokens == 0 and not control.reservations
    assert journal.settlements[-1]["usage"]["total_tokens"] == 0
    assert journal.settlements[-1]["usage"]["calls"] == 0
    assert gateway.records[-1]["status"] == "not_started"


def test_optional_start_marker_is_not_required_for_existing_journals() -> None:
    journal = Journal()
    gateway = ProviderGateway("codex", "explicit", journal=journal)
    provider = ReplyProvider()
    gateway.provider = provider
    reply = gateway.generate("prompt", {}, "plan", GenerationControl.bounded())
    assert reply.data == {"ok": True} and provider.calls == 1
    assert journal.settlements[-1]["status"] == "completed"


def test_failed_start_marker_prevents_dispatch_and_releases_reservation_at_zero_cost() -> None:
    class FailedMarkerJournal(Journal):
        def mark_started(self, _key: str) -> None:
            raise OSError("Authored dispatch checkpoint failure")

    journal = FailedMarkerJournal()
    gateway = ProviderGateway("codex", "explicit", journal=journal)
    provider = ReplyProvider()
    gateway.provider = provider
    control = GenerationControl.bounded()
    with pytest.raises(OSError, match="checkpoint failure"):
        gateway.generate("prompt", {}, "plan", control)
    assert provider.calls == 0
    assert control.usage["calls"] == 0 and control.uncertain_tokens == 0
    assert not control.reservations
    assert journal.settlements[-1]["status"] == "not_started"
    assert journal.settlements[-1]["usage"]["total_tokens"] == 0
    assert gateway.records[-1]["status"] == "not_started"


def test_cancel_during_start_checkpoint_stops_before_provider_dispatch() -> None:
    control = GenerationControl.bounded()

    class CancelledMarkerJournal(Journal):
        def mark_started(self, _key: str) -> None:
            control.cancel.set()

    journal = CancelledMarkerJournal()
    gateway = ProviderGateway("codex", "explicit", journal=journal)
    provider = ReplyProvider()
    gateway.provider = provider
    with pytest.raises(GenerationStopped, match="cancelled"):
        gateway.generate("prompt", {}, "plan", control)
    assert provider.calls == 0
    assert not control.reservations and control.uncertain_tokens == 0
    assert journal.settlements[-1]["status"] == "not_started"
    assert journal.settlements[-1]["usage"]["calls"] == 0


def test_portable_wire_schema_preserves_strict_objects_and_full_local_bounds() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 2, "maxLength": 5}},
        "required": ["name"],
        "additionalProperties": False,
    }
    portable: dict[str, Any] = cast(Any, portable_output_schema)(schema)
    assert portable["additionalProperties"] is False
    assert portable["required"] == ["name"]
    assert "minLength" not in portable["properties"]["name"]
    with pytest.raises(ProviderError, match="invalid structured"):
        cast(Any, parse_json)('{"name":""}', schema)


def test_schema_failure_exposes_safe_coordinates_without_payload() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"save": {"type": "object", "additionalProperties": {"type": "integer"}}},
    }
    with pytest.raises(ProviderError) as caught:
        cast(Any, parse_json)('{"save":{"private-sensitive-key":"secret-value"}}', schema)
    diagnostic = cast(Any, caught.value).structured_diagnostic
    assert diagnostic["keyword"] == "type"
    assert diagnostic["instance_path"] == ["save", "<dynamic>"]
    assert diagnostic["schema_path"] == ["properties", "save", "additionalProperties", "type"]
    assert "private" not in str(caught.value) and "secret-value" not in str(caught.value)
    assert caught.value.__suppress_context__
