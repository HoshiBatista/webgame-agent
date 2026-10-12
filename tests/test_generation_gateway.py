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
        self,
        key: str,
        reserved_tokens: int,
        operation: str,
        request_sha256: str,
        *,
        estimate: dict[str, int] | None = None,
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


@pytest.mark.parametrize("journal", [None, Journal()])
def test_frozen_rate_model_mismatch_cannot_dispatch(journal: Journal | None) -> None:
    from prompt2play.pricing import nano_usd, snapshot

    control = GenerationControl.bounded(
        cost_limit_nano=nano_usd("10"), pricing=snapshot("gpt-6-astra", "codex")
    )
    gateway = ProviderGateway("codex", "gpt-6-sol", journal=journal)
    provider = ReplyProvider()
    gateway.provider = provider
    with pytest.raises(GenerationStopped, match="tariff"):
        gateway.generate("fixture", {}, "plan", control)
    assert provider.calls == 0


@pytest.mark.parametrize("known_usage", [False, True])
def test_local_timeout_retries_once_and_keeps_original_cost(known_usage: bool) -> None:
    from prompt2play.legacy.worker.core import CodexCallTimeout

    journal = Journal()
    gateway = ProviderGateway("codex", "fixture", journal=journal)
    provider = ReplyProvider(
        error=cast(Any, CodexCallTimeout)(
            "Codex call exceeded wall timeout",
            usage={
                "input_tokens": 3,
                "cached_input_tokens": 0,
                "output_tokens": 4,
                "total_tokens": 7,
                "calls": 1,
            }
            if known_usage
            else None,
        )
    )
    gateway.provider = provider
    control = GenerationControl.bounded()
    with pytest.raises(CodexCallTimeout):
        gateway.generate("prompt", {}, "author", control)
    assert provider.calls == 2
    assert journal.requests[1] == journal.requests[0] + ":retry:1"
    assert [entry["status"] for entry in journal.settlements] == ["timed_out", "timed_out"]
    assert control.usage["total_tokens"] == (14 if known_usage else 0)
    assert bool(control.uncertain_tokens) != known_usage


@pytest.mark.parametrize("stop", ["cancel", "fence", "deadline", "budget"])
def test_timeout_cannot_bypass_stopping_constraints(stop: str) -> None:
    import time

    from prompt2play.legacy.worker.core import CodexCallTimeout

    current = [True]
    control = GenerationControl.bounded(fence_check=lambda: current[0])

    class TimeoutProvider(ReplyProvider):
        def generate(self, *args: Any, **kwargs: Any) -> Reply:
            self.calls += 1
            if stop == "cancel":
                control.cancel.set()
            elif stop == "fence":
                current[0] = False
            elif stop == "deadline":
                control.deadline = time.monotonic() - 1
            else:
                control.token_limit = sum(control.reservations.values())
            raise cast(Any, CodexCallTimeout)("Codex call exceeded wall timeout")

    provider = TimeoutProvider()
    gateway = ProviderGateway("codex", "fixture", journal=Journal())
    gateway.provider = provider
    with pytest.raises(GenerationStopped):
        gateway.generate("prompt", {}, "author", control)
    assert provider.calls == 1
    assert control.uncertain_tokens > 0


def test_saved_timeout_and_retry_receipts_survive_evaluator_restart(tmp_path: Any) -> None:
    from prompt2play.evaluation import FileJournal
    from prompt2play.legacy.worker.core import CodexCallTimeout

    class TimeoutOnce(ReplyProvider):
        def generate(self, *args: Any, **kwargs: Any) -> Reply:
            if self.calls == 0:
                self.calls += 1
                raise cast(Any, CodexCallTimeout)("Codex call exceeded wall timeout")
            return super().generate(*args, **kwargs)

    path = tmp_path / "calls.json"
    first = ProviderGateway("codex", "fixture", journal=FileJournal(path))
    first.provider = TimeoutOnce()
    reply = first.generate("prompt", {}, "author", GenerationControl.bounded())
    assert first.provider.calls == 2 and reply.invocation_key.endswith(":retry:1")
    journal = FileJournal(path)
    usage, uncertain = journal.accounting()
    assert usage["total_tokens"] == 7 and uncertain > 0
    second = ProviderGateway("codex", "fixture", journal=journal)
    second.provider = ReplyProvider()
    reused = second.generate(
        "prompt", {}, "author", GenerationControl.bounded(usage=usage, uncertain_tokens=uncertain)
    )
    assert reused.reused and second.provider.calls == 0
    assert journal.accounting() == (usage, uncertain)


def test_default_generation_uses_no_timer_but_retains_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import math

    def forbidden_timer(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("An unlimited generation must not install a wall timer")

    monkeypatch.setattr("prompt2play.generation.gateway.threading.Timer", forbidden_timer)
    control = GenerationControl.bounded()
    assert math.isinf(control.deadline)
    gateway = ProviderGateway("codex", "fixture")
    assert gateway.provider.timeout is None
    gateway.provider = ReplyProvider()
    gateway.generate("prompt", {}, "author", control)
    control.cancel.set()
    with pytest.raises(GenerationStopped, match="cancelled"):
        gateway.generate("next", {}, "author", control)
    assert gateway.provider.calls == 1
    assert ProviderGateway("openai", "fixture").provider.timeout is None


def png(value: int = 0) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes([0, value, value, value, 255])))
        + chunk(b"IEND", b"")
    )


def test_image_pixels_bind_invocation_identity_and_are_delivered_without_log_data() -> None:
    import base64

    from prompt2play.generation.images import ImageInput

    class ImageProvider(ReplyProvider):
        def generate(self, *args: Any, **kwargs: Any) -> Reply:
            assert base64.b64decode(kwargs["images"][0]["base64"]) in (png(), png(30))
            assert "messages" not in kwargs and "session_id" not in kwargs
            return super().generate(*args, **kwargs)

    gateway = ProviderGateway("codex", "explicit", journal=Journal())
    gateway.provider = ImageProvider()
    control = GenerationControl.bounded(token_limit=1_000_000)
    first = gateway.generate(
        "image fixture",
        {},
        "rendered_review",
        control,
        images=[ImageInput("start-1280.png", png())],
    )
    second = gateway.generate(
        "image fixture",
        {},
        "rendered_review",
        control,
        images=[ImageInput("start-1280.png", png(30))],
    )
    assert first.invocation_key != second.invocation_key
    assert control.usage["calls"] == 2
    assert base64.b64encode(png()).decode() not in str(gateway.records)


def test_invalid_duplicate_or_corrupt_png_inputs_never_dispatch() -> None:
    from prompt2play.generation.images import ImageInput

    gateway = ProviderGateway("codex", "explicit", journal=Journal())
    provider = ReplyProvider()
    gateway.provider = provider
    for images in (
        [ImageInput("../secret.png", png())],
        [ImageInput("a.png", png()[:-1])],
        [ImageInput("a.png", png())] * 7,
        [ImageInput("a.png", png())] * 2,
    ):
        with pytest.raises(ValueError):
            gateway.generate(
                "fixture", {}, "rendered_review", GenerationControl.bounded(), images=images
            )
    assert provider.calls == 0
