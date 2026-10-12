"""Fake replies test the harness; these fixtures are never counted as live games."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, cast

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
        self.roles: list[str] = []

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
        self.roles.append(role)
        # Existing operation fixtures are not art-quality evaluations. Dedicated
        # review tests below supply explicit failures and inspect the round trips.
        if role == "visual_review" and (not self.replies or "criteria" not in self.replies[0]):
            data = json.loads(
                (Path(__file__).parent / "fixtures/visual-review-ready.json").read_text()
            )
        else:
            data = self.replies.pop(0)
        return GatewayReply(
            data,
            {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3, "calls": 1},
            role,
        )


def operation(
    op: str, path: str = "", *, content: str = "", old: str = "", new: str = ""
) -> dict[str, str]:
    return {"op": op, "path": path, "content": content, "old": old, "new": new}


def fixture() -> tuple[dict[str, Any], str]:
    root = RESOURCE_ROOT / "runtime" / "examples" / "dom"
    design = json.loads((Path(__file__).parent / "fixtures/design-contract.json").read_text())
    return {
        "game_spec": json.loads((root / "spec.json").read_text()),
        "build_plan": {**json.loads((root / "plan.json").read_text()), **design},
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
    assert "javascript_syntax" in gateway.prompts[gateway.roles.index("author", 2)]
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
    assert "immutable" in gateway.prompts[gateway.roles.index("author", 2)]


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


def test_repeated_reads_are_feedback_and_do_not_stop_generation() -> None:
    plan, source = fixture()
    repeated = {"operations": [operation("read", "missing.js")], "summary": "Retry reading"}
    gateway = ScriptedGateway(
        [
            plan,
            repeated,
            repeated,
            {
                "operations": [operation("create", "game.js", content=source), operation("submit")],
                "summary": "Complete",
            },
        ]
    )
    candidate = GenerationHarness().attempt(
        GenerationRequest("Fixture"), gateway, GenerationControl.bounded()
    )
    assert candidate.files["game.js"] == source
    assert candidate.provenance["turns"] == 3


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


def review_fixture(*, reject: bool = False) -> dict[str, Any]:
    value = json.loads((Path(__file__).parent / "fixtures/visual-review-ready.json").read_text())
    if reject:
        value["criteria"]["assets_and_detail"].update(
            status="needs_revision", required_change="Replace flat placeholder beacon treatment."
        )
    return cast_review(value)


def cast_review(value: Any) -> dict[str, Any]:
    assert isinstance(value, dict)
    return value


def test_new_plan_requires_detailed_design_but_historical_plan_remains_readable() -> None:
    from prompt2play.contracts import BuildPlan, ContractError

    plan, _ = fixture()
    del plan["build_plan"]["visual_design"]
    del plan["build_plan"]["implementation_design"]
    assert BuildPlan(plan["build_plan"]).data["format"] == "runtime-v1"
    gateway = ScriptedGateway([plan])
    with pytest.raises(ContractError, match="New game plan"):
        GenerationHarness().attempt(
            GenerationRequest("Full game"), gateway, GenerationControl.bounded()
        )
    assert gateway.roles == ["plan"]


def test_visual_findings_require_changed_source_and_new_review_before_submission() -> None:
    from prompt2play.contracts.models import digest

    plan, source = fixture()
    gateway = ScriptedGateway(
        [
            plan,
            {
                "operations": [operation("create", "game.js", content=source), operation("submit")],
                "summary": "Draft",
            },
            review_fixture(reject=True),
            {"operations": [operation("submit")], "summary": "Attempt unchanged submission"},
            {
                "operations": [
                    operation("patch", "game.js", old='"#227a58"', new='"#287950"'),
                    operation("submit"),
                ],
                "summary": "Authored patch fixture",
            },
            review_fixture(),
        ]
    )
    candidate = GenerationHarness().attempt(
        GenerationRequest("Full game"), gateway, GenerationControl.bounded()
    )
    assert gateway.roles == ["plan", "author", "visual_review", "author", "author", "visual_review"]
    feedback = json.loads(gateway.prompts[3].split(PROMPT_BOUNDARY)[1])["tool_results"]
    assert feedback[-1]["op"] == "visual_review" and feedback[-1]["release_eligible"] is False
    assert "unchanged source" in gateway.prompts[4]
    reviews = candidate.provenance["visual_quality"]["reviews"]
    assert [item["status"] for item in reviews] == ["needs_revision", "source_ready"]
    assert reviews[-1]["source_sha256"] == digest(candidate.files)
    assert reviews[0]["source_sha256"] != reviews[-1]["source_sha256"]
    assert candidate.provenance["visual_quality"]["rendered_visual_review"] == "not_performed"


@pytest.mark.parametrize("defect", ["invented_excerpt", "missing_area", "contradictory_status"])
def test_visual_review_cannot_approve_with_unbound_or_incomplete_evidence(defect: str) -> None:
    plan, source = fixture()
    review = review_fixture()
    if defect == "invented_excerpt":
        review["criteria"]["art_direction"]["excerpt"] = "nonexistentArtwork()"
    elif defect == "missing_area":
        del review["criteria"]["interface"]
    else:
        review["criteria"]["interface"]["required_change"] = "Must be changed"
    gateway = ScriptedGateway(
        [
            plan,
            {
                "operations": [operation("create", "game.js", content=source), operation("submit")],
                "summary": "Draft",
            },
            review,
        ]
    )
    candidate = GenerationHarness().attempt(
        GenerationRequest("Full game"), gateway, GenerationControl.bounded()
    )
    assert gateway.roles.count("visual_review") == 2
    assert "Review evidence is invalid" in gateway.prompts[-1]
    assert len(candidate.provenance["visual_quality"]["reviews"]) == 1


def test_visual_review_continues_beyond_three_rounds_until_ready() -> None:
    plan, source = fixture()
    replies = [plan]
    for index in range(4):
        replies.append(
            {
                "operations": [
                    operation(
                        "create" if index == 0 else "replace",
                        "game.js",
                        content=source + f"\n// Authored version {index}",
                    ),
                    operation("submit"),
                ],
                "summary": f"Draft {index}",
            }
        )
        if index < 3:
            replies.append(review_fixture(reject=True))
    gateway = ScriptedGateway(replies)
    candidate = GenerationHarness().attempt(
        GenerationRequest("Full game"), gateway, GenerationControl.bounded()
    )
    assert gateway.roles.count("visual_review") == 4
    assert candidate.provenance["visual_quality"]["reviews"][-1]["status"] == "source_ready"


def test_cancel_during_art_review_does_not_submit() -> None:
    plan, source = fixture()

    class CancelReview(ScriptedGateway):
        def generate(
            self,
            prompt: str,
            schema: dict[str, Any],
            role: str,
            control: GenerationControl,
            *,
            max_output: int = 16000,
        ) -> GatewayReply:
            if role == "visual_review":
                control.cancel.set()
            return super().generate(prompt, schema, role, control, max_output=max_output)

    gateway = CancelReview(
        [
            plan,
            {
                "operations": [operation("create", "game.js", content=source), operation("submit")],
                "summary": "Draft",
            },
        ]
    )
    with pytest.raises(GenerationStopped):
        GenerationHarness().attempt(
            GenerationRequest("Full game"), gateway, GenerationControl.bounded()
        )


def test_old_revision_replans_design_without_widening_file_permissions() -> None:
    plan, source = fixture()
    old_plan = {
        key: value
        for key, value in plan["build_plan"].items()
        if key not in ("visual_design", "implementation_design")
    }
    for value in (old_plan, plan["build_plan"]):
        value["files"] = [
            *value["files"],
            {"path": "style.css", "purpose": "Style", "dependencies": []},
        ]
    gateway = ScriptedGateway(
        [
            plan,
            {
                "operations": [
                    operation("patch", "style.css", old="red", new="blue"),
                    operation("submit"),
                ],
                "summary": "Authored local edit",
            },
        ]
    )
    result = GenerationHarness().attempt(
        GenerationRequest(
            "Change red to blue",
            kind="revise",
            base_files={"game.js": source, "style.css": "article{color:red}"},
            base_spec=plan["game_spec"],
            base_plan=old_plan,
            changed_files=frozenset({"style.css"}),
        ),
        gateway,
        GenerationControl.bounded(),
    )
    assert gateway.roles == ["plan", "author", "visual_review"]
    assert result.files["game.js"] == source and result.files["style.css"] == "article{color:blue}"
    assert "visual_design" in result.plan and "visual_design" not in old_plan


def test_long_authoring_exceeds_old_batch_turn_operation_and_check_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from prompt2play.generation.harness import OPERATIONS_SCHEMA
    from prompt2play.legacy.worker.providers import parse_json

    plan, source = fixture()
    first = {
        "operations": [operation("create", "game.js", content=source)]
        + [operation("read", "game.js") for _ in range(20)],
        "summary": "Large valid batch",
    }
    # Exercise the actual transport parser which rejected the user's answer.
    assert cast(Any, parse_json)(json.dumps(first), OPERATIONS_SCHEMA) == first
    batch = {
        "operations": [operation("read", "game.js") for _ in range(6)] + [operation("check")],
        "summary": "Continue",
    }
    monkeypatch.setattr("prompt2play.generation.workspace.quick_check", lambda *_: [])
    gateway = ScriptedGateway(
        [
            plan,
            first,
            *[batch for _ in range(10)],
            {"operations": [operation("submit")], "summary": "Finished"},
        ]
    )
    candidate = GenerationHarness().attempt(
        GenerationRequest("Long fixture"), gateway, GenerationControl.bounded()
    )
    assert candidate.provenance["turns"] == 12
    assert candidate.provenance["quick_checks"] == 10
    assert candidate.files["game.js"] == source


def test_checkpoint_resumes_before_review_without_replanning_or_rewriting() -> None:
    from dataclasses import replace

    plan, source = fixture()
    saved: list[dict[str, Any]] = []

    class Interrupted(Exception):
        pass

    def save(state: dict[str, Any]) -> None:
        saved.append(state)
        if state["phase"] == "review":
            raise Interrupted()

    request = GenerationRequest("Recover fixture", attempt_id="job:1")
    first = ScriptedGateway(
        [
            plan,
            {
                "operations": [operation("create", "game.js", content=source), operation("submit")],
                "summary": "Persisted author",
            },
        ]
    )
    with pytest.raises(Interrupted):
        GenerationHarness(on_checkpoint=save).attempt(request, first, GenerationControl.bounded())
    resumed = ScriptedGateway([])
    candidate = GenerationHarness().attempt(
        replace(request, resume_state=saved[-1]), resumed, GenerationControl.bounded()
    )
    assert resumed.roles == ["visual_review"]
    assert candidate.files["game.js"] == source and candidate.provenance["turns"] == 1
    with pytest.raises(ValueError, match="different generation request"):
        GenerationHarness().attempt(
            replace(request, prompt="Another game", resume_state=saved[-1]),
            ScriptedGateway([]),
            GenerationControl.bounded(),
        )


@pytest.mark.parametrize("stop", ["cancel", "money"])
def test_continued_authoring_still_stops_for_user_or_money(stop: str) -> None:
    from prompt2play.pricing import nano_usd

    plan, _ = fixture()
    control = GenerationControl.bounded(cost_limit_nano=nano_usd("10"))

    class StoppingGateway(ScriptedGateway):
        def generate(self, *args: Any, **kwargs: Any) -> GatewayReply:
            if self.roles.count("author") == 10:
                if stop == "cancel":
                    control.cancel.set()
                else:
                    control.spent_nano = nano_usd("11")
            return super().generate(*args, **kwargs)

    gateway = StoppingGateway(
        [
            plan,
            *[
                {"operations": [operation("read", "missing.js")], "summary": "Retry"}
                for _ in range(12)
            ],
        ]
    )
    with pytest.raises(GenerationStopped):
        GenerationHarness().attempt(GenerationRequest("Continue"), gateway, control)
    assert gateway.roles.count("author") == 10


def test_explicit_experiment_turn_bound_remains_opt_in() -> None:
    plan, _ = fixture()
    batch = {"operations": [operation("read", "missing.js")], "summary": "Feedback"}
    with pytest.raises(GenerationStopped, match="explicit turn budget"):
        GenerationHarness(limits=WorkspaceLimits(max_turns=2)).attempt(
            GenerationRequest("Bounded experiment"),
            ScriptedGateway([plan, batch, batch]),
            GenerationControl.bounded(),
        )


def test_restored_ready_draft_must_have_review_for_exact_source() -> None:
    from dataclasses import replace

    plan, source = fixture()
    states: list[dict[str, Any]] = []
    request = GenerationRequest("Fixture")
    GenerationHarness(on_checkpoint=states.append).attempt(
        request,
        ScriptedGateway(
            [
                plan,
                {
                    "operations": [
                        operation("create", "game.js", content=source),
                        operation("submit"),
                    ],
                    "summary": "Fixture",
                },
            ]
        ),
        GenerationControl.bounded(),
    )
    saved = states[-1]
    assert saved["phase"] == "ready"
    saved["files"]["game.js"] += "\n// Changed after review"
    with pytest.raises(ValueError, match="matching successful source review"):
        GenerationHarness().attempt(
            replace(request, resume_state=saved), ScriptedGateway([]), GenerationControl.bounded()
        )


def test_draft_snapshot_larger_than_plan_envelope_survives_restart() -> None:
    from dataclasses import replace

    plan, source = fixture()
    source += "\n/* " + "authored source padding " * 5000 + " */"
    assert 100_000 < len(source.encode()) < WorkspaceLimits().max_file_bytes
    states: list[dict[str, Any]] = []
    request = GenerationRequest("Large draft")
    GenerationHarness(on_checkpoint=states.append).attempt(
        request,
        ScriptedGateway(
            [
                plan,
                {
                    "operations": [
                        operation("create", "game.js", content=source),
                        operation("submit"),
                    ],
                    "summary": "Large fixture",
                },
            ]
        ),
        GenerationControl.bounded(),
    )
    resumed = ScriptedGateway([])
    candidate = GenerationHarness().attempt(
        replace(request, resume_state=states[-1]), resumed, GenerationControl.bounded()
    )
    assert candidate.files["game.js"] == source and not resumed.roles
