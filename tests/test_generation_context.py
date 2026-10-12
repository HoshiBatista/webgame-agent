"""Context reuse must preserve exact source, accounting and isolation across roles/jobs."""

from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from prompt2play.contracts.models import stable
from prompt2play.generation.context import (
    ContextConversations,
    context_delta,
    file_update,
    ordered_context,
)
from prompt2play.generation.gateway import ProviderGateway
from prompt2play.generation.workspace import GenerationControl
from prompt2play.legacy.worker.core import PROMPT_BOUNDARY, ProviderError

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def snapshot(turn: int = 1, **values: Any) -> dict[str, Any]:
    return {
        "attempt_id": "job:1",
        "request": "Точная стратегия",
        "turn": turn,
        "game_spec": {"genre": "strategy"},
        "build_plan": {"visual_design": "Detailed map"},
        "current_files": {"game.js": "\n".join(f"line {n} -- ё" for n in range(500))},
        "tool_results": [{"op": "check", "status": "passed"}],
        **values,
    }


def prompt(context: dict[str, Any]) -> str:
    return "Trusted instructions" + PROMPT_BOUNDARY + ordered_context(context)


def apply_delta(
    before: dict[str, Any], delta: dict[str, Any], previous_reply: dict[str, Any] | None = None
) -> dict[str, Any]:
    result = copy.deepcopy(before)
    for key in delta["remove"]:
        result.pop(key)
    result.update(delta["set"])
    for field, files in delta["file_updates"].items():
        for path, update in files.items():
            if update.get("delete"):
                result[field].pop(path)
            elif "content" in update:
                result[field][path] = update["content"]
            elif "from_previous_response" in update:
                assert previous_reply is not None
                ref = update["from_previous_response"]
                result[field][path] = previous_reply["operations"][ref["operation_index"]][
                    ref["field"]
                ]
            else:
                patch = update["replace_text"]
                assert result[field][path].count(patch["old"]) == 1
                result[field][path] = result[field][path].replace(patch["old"], patch["new"], 1)
    return result


def test_delta_losslessly_reconciles_failed_operations_edits_additions_and_deletions() -> None:
    before = snapshot()
    after = snapshot(
        2,
        current_files={
            "game.js": before["current_files"]["game.js"].replace("line 420", "line 420 improved"),
            "style.css": "",
        },
        tool_results=[{"error": "patch failed; source unchanged elsewhere"}],
    )
    delta = context_delta(before, after)
    assert apply_delta(before, delta) == after
    assert "replace_text" in delta["file_updates"]["current_files"]["game.js"]
    assert len(stable(delta)) < len(stable(after)) / 4
    final = {**after, "current_files": {"style.css": "new styles"}}
    final.pop("build_plan")
    assert apply_delta(after, context_delta(after, final)) == final


def test_generated_file_is_referenced_only_after_exact_confirmation() -> None:
    before = snapshot(current_files={})
    after = snapshot(2)
    reply = {
        "operations": [
            {"op": "create", "path": "game.js", "content": after["current_files"]["game.js"]}
        ]
    }
    delta = context_delta(before, after, reply)
    assert "from_previous_response" in delta["file_updates"]["current_files"]["game.js"]
    assert apply_delta(before, delta, reply) == after
    # A rejected create or a later operation must not be implicitly confirmed.
    rejected = snapshot(2, current_files={})
    assert not context_delta(before, rejected, reply)["file_updates"]
    changed = snapshot(2, current_files={"game.js": "actual different source"})
    update = context_delta(before, changed, reply)
    assert "from_previous_response" not in update["file_updates"]["current_files"]["game.js"]
    assert apply_delta(before, update, reply) == changed


def test_file_updates_roundtrip_unicode_repeated_text_newlines_and_empty_files() -> None:
    rng = random.Random(7)
    for _ in range(250):
        before = "".join(rng.choice(["x", "ё", "🎲", "\r\n", " repeated "]) for _ in range(150))
        start, stop = sorted([rng.randrange(len(before)), rng.randrange(len(before))])
        after = before[:start] + rng.choice(["", "new\n", "🎲updated"]) + before[stop:]
        assert apply_delta(
            {"files": {"x": before}},
            {"set": {}, "remove": [], "file_updates": {"files": {"x": file_update(before, after)}}},
        ) == {"files": {"x": after}}
    for old, new in [("", "x"), ("x", ""), (None, ""), ("x", None)]:
        update = file_update(old, new)
        assert update.get("content") == new if new is not None else update["delete"]


def test_history_is_appended_and_refreshes_without_losing_snapshot_or_stopping() -> None:
    contexts = ContextConversations()
    first = contexts.prepare(prompt(snapshot()), SCHEMA, "author", "model")
    assert first is not None and not first.continuation
    contexts.commit(first, {"ok": True})
    second = contexts.prepare(prompt(snapshot(2)), SCHEMA, "author", "model")
    assert second is not None and second.continuation
    assert second.messages[:-1] == first.conversation.messages
    assert apply_delta(snapshot(), json.loads(second.text)) == snapshot(2)
    assert len(second.reservation_prompt) > len(first.text) > len(second.text)
    contexts.commit(second, {"ok": True, "large_obsolete_reply": "x" * 100_000})
    third = contexts.prepare(prompt(snapshot(3)), SCHEMA, "author", "model")
    assert third is not None and not third.continuation and third.reason == "history_refresh"
    assert json.loads(third.text) == snapshot(3)
    assert third.conversation.turns == 0


def test_reservation_covers_observed_codex_context_without_padding_the_wire_message() -> None:
    contexts = ContextConversations()
    first = contexts.prepare(prompt(snapshot()), SCHEMA, "author", "model")
    assert first is not None
    first.conversation.last_usage = {"input_tokens": 30000, "output_tokens": 4000}
    contexts.commit(first, {"ok": True})
    next_request = contexts.prepare(prompt(snapshot(2)), SCHEMA, "author", "model")
    assert next_request is not None and next_request.continuation
    assert len(next_request.reservation_prompt.encode()) >= 34000 + len(next_request.text.encode())
    assert len(next_request.text) < 500
    assert len(stable(next_request.messages)) < 15000


@pytest.mark.parametrize(
    "role,model,attempt,schema",
    [
        ("visual_review", "model", "job:1", SCHEMA),
        ("author", "other", "job:1", SCHEMA),
        ("author", "model", "other_job:1", SCHEMA),
        ("author", "model", "job:1", {}),
    ],
)
def test_conversations_do_not_cross_roles_models_attempts_or_schemas(
    role: str, model: str, attempt: str, schema: dict[str, Any]
) -> None:
    contexts = ContextConversations()
    first = contexts.prepare(prompt(snapshot()), SCHEMA, "author", "model")
    assert first is not None
    contexts.commit(first, {"ok": True})
    next_request = contexts.prepare(prompt(snapshot(2, attempt_id=attempt)), schema, role, model)
    assert next_request is not None and not next_request.continuation


def fake_codex(
    tmp_path: Path, *, fail_second: bool = False, regressed_usage: bool = False
) -> tuple[Path, Path]:
    log = tmp_path / "calls.jsonl"
    executable = tmp_path / "codex"
    executable.write_text(
        "#!"
        + sys.executable
        + "\n"
        + f"""
import sys,json,os
from pathlib import Path
log=Path({str(log)!r})
args=sys.argv
text=sys.stdin.read()
calls=[json.loads(s) for s in log.read_text().splitlines()] if log.exists() else []
resume='resume' in args
assert '--ignore-user-config' in args and '--ignore-rules' in args
assert args[args.index('--sandbox')+1]=='read-only'
assert 'features.shell_tool=false' in args and 'web_search="disabled"' in args
assert '--ephemeral' not in args
assert 'OPENAI_API_KEY' not in os.environ
with log.open('a') as f:f.write(json.dumps({{'args':args,'text':text,'cwd':os.getcwd()}})+'\\n')
print(json.dumps({{'type':'thread.started','thread_id':'00000000-0000-0000-0000-000000000123'}}))
usage={{'input_tokens':220 if resume else 100,'cached_input_tokens':90 if resume else 0,'output_tokens':30 if resume else 20}}
if resume and {regressed_usage!r}:usage['input_tokens']=50
print(json.dumps({{'type':'turn.completed','usage':usage}}))
if len(calls)==1 and {fail_second!r}:sys.exit(1)
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({{'ok':True}}))
"""
    )
    executable.chmod(0o700)
    return executable, log


def test_codex_resume_uses_delta_stable_cwd_and_charges_only_new_usage(tmp_path: Path) -> None:
    binary, log = fake_codex(tmp_path)
    gateway = ProviderGateway("codex", "test", executable=str(binary))
    control = GenerationControl.bounded()
    try:
        first = gateway.generate(prompt(snapshot()), SCHEMA, "author", control)
        second = gateway.generate(prompt(snapshot(2)), SCHEMA, "author", control)
        calls = [json.loads(s) for s in log.read_text().splitlines()]
        assert "resume" not in calls[0]["args"] and "resume" in calls[1]["args"]
        assert calls[0]["cwd"] == calls[1]["cwd"]
        assert apply_delta(snapshot(), json.loads(calls[1]["text"])) == snapshot(2)
        assert first.usage["input_tokens"] == 100 and second.usage["input_tokens"] == 120
        assert second.usage["cached_input_tokens"] == 90 and second.usage["output_tokens"] == 10
        assert control.usage["input_tokens"] == 220 and control.usage["calls"] == 2
        assert gateway.records[-1]["context"]["mode"] == "delta"
    finally:
        gateway.close()
    assert not Path(calls[0]["cwd"]).exists()


@pytest.mark.parametrize("regressed", [False, True])
def test_failed_resumed_call_discards_context_and_preserves_known_or_unknown_spend(
    tmp_path: Path, regressed: bool
) -> None:
    binary, log = fake_codex(tmp_path, fail_second=True, regressed_usage=regressed)
    gateway = ProviderGateway("codex", "test", executable=str(binary))
    control = GenerationControl.bounded()
    try:
        gateway.generate(prompt(snapshot()), SCHEMA, "author", control)
        with pytest.raises(ProviderError):
            gateway.generate(prompt(snapshot(2)), SCHEMA, "author", control)
        assert not gateway.contexts.sessions
        assert control.usage["input_tokens"] == (100 if regressed else 220)
        assert (control.uncertain_tokens > 0) is regressed
        gateway.generate(prompt(snapshot(3)), SCHEMA, "author", control)
        calls = [json.loads(s) for s in log.read_text().splitlines()]
        assert "resume" not in calls[-1]["args"]
        assert json.loads(calls[-1]["text"].split(PROMPT_BOUNDARY)[1]) == snapshot(3)
    finally:
        gateway.close()


def test_responses_preserves_messages_and_separates_untrusted_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        payload = {
            "type": "response.completed",
            "response": {
                "output": [{"content": [{"type": "output_text", "text": '{"ok":true}'}]}],
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        }
        return httpx.Response(200, text="data: " + json.dumps(payload) + "\n\n")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        "prompt2play.legacy.worker.providers.httpx.AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    gateway = ProviderGateway("openai", "test", api_key="fake")
    control = GenerationControl.bounded()
    gateway.generate(prompt(snapshot()), SCHEMA, "author", control)
    gateway.generate(prompt(snapshot(2)), SCHEMA, "author", control)
    assert captured[0]["instructions"] == captured[1]["instructions"]
    assert "Точная стратегия" not in captured[0]["instructions"]
    assert captured[1]["input"][:1] == captured[0]["input"]
    assert captured[1]["input"][1]["role"] == "assistant"
    assert json.loads(captured[1]["input"][-1]["content"])["type"] == "context_delta"
    assert captured[1]["store"] is False
    assert control.usage["input_tokens"] == 200  # Responses receipts are per response.
