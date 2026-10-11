"""Fake replies test the harness; these fixtures are never counted as live games."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from prompt2play.contracts import PLAN_SCHEMA
from prompt2play.contracts.models import stable
from prompt2play.generation import runtime
from prompt2play.generation.gateway import GatewayReply
from prompt2play.generation.harness import GenerationHarness, GenerationRequest
from prompt2play.generation.workspace import (
    GenerationControl,
    GenerationStopped,
    WorkspaceLimits,
    invocation_reservation,
)
from prompt2play.legacy.worker.core import PROMPT_BOUNDARY
from prompt2play.paths import LEGACY_ROOT, RESOURCE_ROOT


class ScriptedGateway:
    name = "test-fixture"
    model = "deterministic"
    is_replay = True
    capabilities = frozenset({"structured_output", "file_operations"})

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def generate(
        self,
        prompt: str,
        schema: dict[str, Any],
        role: str,
        control: GenerationControl,
        *,
        max_output: int = 16000,
    ) -> GatewayReply:
        del schema, max_output
        control.guard()
        self.prompts.append(prompt)
        return GatewayReply(
            self.replies.pop(0),
            {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3, "calls": 1},
            role,
        )


def operation(
    op: str, path: str = "", *, content: str = "", old: str = "", new: str = ""
) -> dict[str, str]:
    return {"op": op, "path": path, "content": content, "old": old, "new": new}


def fixture() -> tuple[dict[str, Any], str]:
    root = RESOURCE_ROOT / "runtime" / "examples" / "dom"
    return {
        "game_spec": json.loads((root / "spec.json").read_text()),
        "build_plan": json.loads((root / "plan.json").read_text()),
    }, (root / "game.js").read_text()


def test_one_attempt_submits_one_candidate_with_exact_source_identity() -> None:
    plan, source = fixture()
    gateway = ScriptedGateway(
        [
            plan,
            {
                "operations": [
                    operation("create", "game.js", content=source),
                    operation("check"),
                    operation("submit"),
                ],
                "summary": "Fixture only",
            },
        ]
    )
    candidate = GenerationHarness().attempt(
        GenerationRequest("Test fixture"), gateway, GenerationControl.bounded()
    )
    assert candidate.files == {"game.js": source}
    assert candidate.format == "runtime-v1"
    assert candidate.provenance["turns"] == 1
    assert candidate.provenance["quick_checks"] == 1
    assert candidate.provenance["replay"] is True
    assert candidate.provenance["source_sha256"]["game.js"]
    assert "validation" not in candidate.as_dict()
    assert "audio" not in candidate.spec["capabilities"]
    # Transport portability may omit numeric bounds, but the planner sees the
    # exact authoritative schema before the untrusted user-data boundary.
    assert stable(PLAN_SCHEMA) in gateway.prompts[0]
    assert gateway.prompts[0].index(stable(PLAN_SCHEMA)) < gateway.prompts[0].index(PROMPT_BOUNDARY)


def test_author_can_apply_local_fix_after_quick_check_without_global_repair() -> None:
    plan, source = fixture()
    bad = source + "\nconst broken = ;"
    gateway = ScriptedGateway(
        [
            plan,
            {
                "operations": [operation("create", "game.js", content=bad), operation("check")],
                "summary": "Draft",
            },
            {
                "operations": [
                    operation(
                        "patch", "game.js", old="const broken = ;", new="const repaired = 1;"
                    ),
                    operation("submit"),
                ],
                "summary": "Fixed draft",
            },
        ]
    )
    candidate = GenerationHarness().attempt(
        GenerationRequest("Fixture"), gateway, GenerationControl.bounded()
    )
    assert "const repaired = 1;" in candidate.files["game.js"]
    assert "javascript_syntax" in gateway.prompts[-1]
    assert candidate.provenance["turns"] == 2


def test_runtime_write_is_rejected_and_feedback_returns_to_model() -> None:
    plan, source = fixture()
    gateway = ScriptedGateway(
        [
            plan,
            {
                "operations": [operation("create", "runtime-v1.js", content="hijack")],
                "summary": "Attempt forbidden write",
            },
            {
                "operations": [operation("create", "game.js", content=source), operation("submit")],
                "summary": "Proper draft",
            },
        ]
    )
    candidate = GenerationHarness().attempt(
        GenerationRequest("Fixture"), gateway, GenerationControl.bounded()
    )
    assert set(candidate.files) == {"game.js"}
    assert "immutable" in gateway.prompts[-1]


def test_local_visual_edit_preserves_mechanics_bytes() -> None:
    plan, source = fixture()
    plan["build_plan"]["files"].append(
        {"path": "style.css", "purpose": "Appearance", "dependencies": []}
    )
    gateway = ScriptedGateway(
        [
            {
                "operations": [
                    operation("patch", "style.css", old="red", new="blue"),
                    operation("submit"),
                ],
                "summary": "Color edit",
            }
        ]
    )
    request = GenerationRequest(
        "Change red to blue",
        kind="revise",
        base_files={"game.js": source, "style.css": "article{color:red}"},
        base_spec=plan["game_spec"],
        base_plan=plan["build_plan"],
        changed_files=frozenset({"style.css"}),
    )
    candidate = GenerationHarness().attempt(request, gateway, GenerationControl.bounded())
    assert candidate.files["game.js"] == source
    assert candidate.files["style.css"] == "article{color:blue}"


def test_repeated_tool_calls_stop_within_original_turn_budget() -> None:
    plan, _ = fixture()
    repeated = {"operations": [operation("read", "missing.js")], "summary": "No progress"}
    gateway = ScriptedGateway([plan, repeated, repeated])
    with pytest.raises(GenerationStopped, match="Repeated identical"):
        GenerationHarness(limits=WorkspaceLimits(max_turns=3)).attempt(
            GenerationRequest("Fixture"), gateway, GenerationControl.bounded()
        )


def test_unsupported_provider_cannot_enable_unrestricted_tools() -> None:
    gateway = ScriptedGateway([])
    gateway.capabilities = frozenset({"structured_output"})
    with pytest.raises(ValueError, match="does not support"):
        GenerationHarness().attempt(
            GenerationRequest("Fixture"), gateway, GenerationControl.bounded()
        )


def test_four_authors_reduce_parallelism_when_all_reservations_do_not_fit() -> None:
    legacy = json.loads((LEGACY_ROOT / "reference" / "corpus" / "lamps" / "spec.json").read_text())

    class BudgetGateway(ScriptedGateway):
        def __init__(self) -> None:
            super().__init__([])
            self.lock = threading.Lock()
            self.active = 0
            self.peak = 0
            self.author_bounds: list[int] = []

        def generate(
            self,
            prompt: str,
            schema: dict[str, Any],
            role: str,
            control: GenerationControl,
            *,
            max_output: int = 16000,
        ) -> GatewayReply:
            del schema
            bound = invocation_reservation(prompt, max_output)
            control.reserve(role, bound)
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
                if role != "plan":
                    self.author_bounds.append(bound)
            # Keep calls outstanding long enough to reproduce simultaneous
            # conservative reservations rather than serial test completion.
            time.sleep(0.02)
            usage = {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3, "calls": 1}
            control.settle(role, usage)
            with self.lock:
                self.active -= 1
            return GatewayReply(
                legacy
                if role == "plan"
                else {"source": f"const {role}Fixture=1;", "summary": "Fixture"},
                usage,
                role,
            )

    harness = GenerationHarness(plan_output_tokens=100, code_output_tokens=100)
    request = GenerationRequest("Budget fixture", mode="four_author")
    generous = BudgetGateway()
    harness.attempt(request, generous, GenerationControl.bounded(token_limit=1_000_000))
    assert generous.peak == 4
    limit = 2 * max(generous.author_bounds) + 1024
    assert sum(generous.author_bounds) > limit
    bounded = BudgetGateway()
    control = GenerationControl.bounded(token_limit=limit)
    candidate = harness.attempt(request, bounded, control)
    assert len(candidate.files) == 4 and 1 <= bounded.peak < 4
    assert control.usage["calls"] == 5 and not control.reservations
    assert control.uncertain_tokens == 0


def test_provider_spanning_runtime_upgrade_keeps_one_exact_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, source = fixture()
    original = runtime.trusted_runtime()
    captured = runtime.capture_runtime_identity()
    root = tmp_path / "runtime"
    archive = root / "versions" / captured["sha256"]
    archive.mkdir(parents=True)
    for name, contents in original.items():
        (root / name).write_text(contents)
        (archive / name).write_text(contents)
    monkeypatch.setattr(runtime, "RESOURCE_ROOT", tmp_path)

    class UpgradingGateway(ScriptedGateway):
        def generate(
            self,
            prompt: str,
            schema: dict[str, Any],
            role: str,
            control: GenerationControl,
            *,
            max_output: int = 16000,
        ) -> GatewayReply:
            if role == "plan":
                (root / "runtime-v1.js").write_text(
                    original["runtime-v1.js"].replace(captured["version"], "runtime-v9.0.0")
                )
            return super().generate(prompt, schema, role, control, max_output=max_output)

    gateway = UpgradingGateway(
        [
            plan,
            {
                "operations": [operation("create", "game.js", content=source), operation("submit")],
                "summary": "Fixture only",
            },
        ]
    )
    candidate = GenerationHarness().attempt(
        GenerationRequest("Fixture"), gateway, GenerationControl.bounded()
    )
    assert runtime.capture_runtime_identity()["version"] == "runtime-v9.0.0"
    assert candidate.spec["runtime"] == captured
    assert candidate.provenance["runtime"] == captured
    assert original["runtime-v1.js"] in candidate.html
    assert 'const VERSION = "runtime-v9.0.0"' not in candidate.html
    assert runtime.assemble_runtime(candidate.files, candidate.spec) == candidate.html
