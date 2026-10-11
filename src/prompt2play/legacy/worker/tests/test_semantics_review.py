"""Independent 1.2.1 regressions for evidence bindings, not generated game quality.

The optional Node check executes only the handwritten adapter below through the
existing bounded interpreter. It never evaluates model-produced game source.
"""

import copy
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from prompt2play.legacy.validator.scenarios import validate_scenarios
from prompt2play.legacy.worker.core import ProviderError, validate_semantic_contract
from prompt2play.legacy.worker.semantics import validate_semantic_coverage
from prompt2play.legacy.worker.tests.fixtures import fixture_plan
from prompt2play.legacy.worker.tests.test_lifetimes import persistent_plan, transaction_plan


ROOT = Path(__file__).resolve().parents[2]


def assertion(path, cmp="eq", *, saved=None, value=None):
    return {
        "op": "assert",
        "left": {"path": path},
        "cmp": cmp,
        "right": {"path": path, "saved": saved} if saved else {"value": value},
    }


def export_plan(steps=None):
    plan = persistent_plan()
    plan["semantic_contract"]["persistence"][0].update(
        storage="export_only", scenario_ids=["save-roundtrip"]
    )
    plan["qa_scenarios"].pop()
    if steps is not None:
        plan["qa_scenarios"][2]["steps"] = copy.deepcopy(steps)
    return plan


def declaration(plan):
    return validate_semantic_coverage(
        plan["semantic_contract"], validate_scenarios(plan["qa_scenarios"])
    )


def misleading_restore_steps(kind):
    act = {"op": "act", "action": {"type": "wait"}}
    capture = {"op": "capture", "key": "before"}
    serialize = {"op": "serialize", "key": "save1"}
    divergent = assertion("/score", "gt", saved="before")
    head = [copy.deepcopy(act), capture, serialize, copy.deepcopy(act), divergent]
    if kind == "another-field":
        head[3]["action"]["type"] = "tick"
        head[4] = assertion("/tick", "gt", saved="before")
    elif kind == "another-capture":
        head = [
            {"op": "capture", "key": "older"},
            copy.deepcopy(act),
            capture,
            serialize,
            assertion("/score", "gt", saved="older"),
        ]
    elif kind == "changed-back":
        head.append({"op": "act", "action": {"type": "undo"}})
    elif kind == "capture-before-saved-state":
        head = [capture, copy.deepcopy(act), serialize, copy.deepcopy(act), divergent]
    return head + [
        {"op": "restore", "saved": "save1", "expect": "accepted"},
        assertion("/score", saved="before"),
        {"op": "restore", "text": "", "expect": "rejected"},
        assertion("/score", saved="before"),
    ]


class RestoreEvidenceReviewTests(unittest.TestCase):
    def test_divergence_and_equality_must_describe_the_same_live_path_and_capture(self):
        for kind in (
            "another-field",
            "another-capture",
            "changed-back",
            "capture-before-saved-state",
        ):
            with (
                self.subTest(kind=kind),
                self.assertRaisesRegex(ProviderError, "accepted save/restore"),
            ):
                declaration(export_plan(misleading_restore_steps(kind)))

    def test_unsaved_domain_cannot_be_the_only_proof_of_restoration(self):
        plan = export_plan(misleading_restore_steps("another-field"))
        domain = plan["semantic_contract"]["state_domains"][0]
        domain["field_ids"] = ["score"]
        plan["semantic_contract"]["state_domains"].append(
            {**domain, "id": "transient", "field_ids": ["tick"], "lifetime": "attempt"}
        )
        with self.assertRaisesRegex(ProviderError, "accepted save/restore"):
            declaration(plan)

    def test_rejected_saved_import_compares_current_state_not_the_old_serialization(self):
        plan = export_plan()
        steps = validate_scenarios(plan["qa_scenarios"])[2]["steps"]
        steps = steps[:7] + [
            {"op": "act", "action": {"type": "wait"}},
            {"op": "capture", "key": "current"},
            {"op": "restore", "saved": "save1", "expect": "rejected"},
            assertion("/score", saved="current"),
        ]
        plan["qa_scenarios"][2]["steps"] = steps
        self.assertEqual(declaration(plan)["status"], "declared")

    def test_rejected_import_cannot_compare_a_stale_capture_before_live_progress(self):
        plan = export_plan()
        steps = validate_scenarios(plan["qa_scenarios"])[2]["steps"]
        steps.insert(7, {"op": "act", "action": {"type": "wait"}})
        plan["qa_scenarios"][2]["steps"] = steps
        with self.assertRaisesRegex(ProviderError, "accepted save/restore"):
            declaration(plan)

    def test_roundtrip_and_repeated_rejection_keep_valid_observation_chains(self):
        plan = export_plan()
        steps = validate_scenarios(plan["qa_scenarios"])[2]["steps"]
        # Captures remain valid when an equality after a previous import proves
        # that the live field is still the captured value before another import.
        steps += [
            {"op": "restore", "text": "{", "expect": "rejected"},
            assertion("/score", saved="before"),
        ]
        plan["qa_scenarios"][2]["steps"] = steps
        self.assertEqual(declaration(plan)["status"], "declared")

    @unittest.skipUnless(shutil.which("node"), "Node unavailable for trusted interpreter test")
    def test_misleading_declarations_really_allow_noop_or_wrong_importers_to_pass(self):
        cases = {
            kind: validate_scenarios(export_plan(misleading_restore_steps(kind))["qa_scenarios"])[2]
            for kind in (
                "another-field",
                "another-capture",
                "changed-back",
                "capture-before-saved-state",
            )
        }
        body = r"""
import assert from 'node:assert/strict';
import {runScenario} from RUNNER_URI;
const cases=CASES;
for (const [kind,scenario] of Object.entries(cases)) {
  let state;
  const adapter={
    reset: async()=>{state={score:0,tick:0};},
    setManualMode:async()=>{},
    snapshot:async()=>structuredClone(state),
    act:async action=>{
      if(action.type==='wait'){state.score++;state.tick++;}
      if(action.type==='tick')state.tick++;
      if(action.type==='undo'){state.score--;state.tick--;}
    },
    exportSave:async()=>JSON.stringify(state),
    importSave:async text=>{
      if(!text)return {ok:false};
      // The last defect uses a loader that silently returns the initial profile;
      // all other defects use a loader that never restores anything at all.
      if(kind==='capture-before-saved-state')state={score:0,tick:0};
      return {ok:true};
    }
  };
  const result=await runScenario(adapter,scenario);
  assert.equal(result.ok,true,kind+': '+result.message);
}
""".replace("RUNNER_URI", json.dumps((ROOT / "validator/scenario_runner.mjs").as_uri())).replace(
            "CASES", json.dumps(cases)
        )
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", body],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ProgressAndReplayReviewTests(unittest.TestCase):
    def test_first_actions_from_separate_reset_instances_are_not_duplicate_claims(self):
        plan = transaction_plan()
        plan["qa_scenarios"][-1]["steps"] = [
            {"op": "act", "action": {"type": "claim"}},
            {"op": "reset"},
            {"op": "act", "action": {"type": "claim"}},
            assertion("/score", value=1),
        ]
        with self.assertRaisesRegex(ProviderError, "repeats its real command"):
            declaration(plan)

    def test_boolean_and_number_commands_do_not_share_transaction_identity(self):
        plan = transaction_plan()
        plan["semantic_contract"]["transactions"][0]["action_json"] = (
            '{"type":"claim","eligible":true}'
        )
        plan["qa_scenarios"][-1]["steps"] = [
            {"op": "act", "action": {"type": "claim", "eligible": 1}, "repeat": 2},
            assertion("/score", value=1),
        ]
        with self.assertRaisesRegex(ProviderError, "repeats its real command"):
            declaration(plan)

    def test_numeric_json_formatting_does_not_change_a_real_transaction_command(self):
        plan = transaction_plan()
        plan["semantic_contract"]["transactions"][0]["action_json"] = '{"type":"claim","amount":1}'
        plan["qa_scenarios"][-1]["steps"] = [
            {"op": "act", "action": {"amount": 1.0, "type": "claim"}, "repeat": 2},
            assertion("/score", value=1),
        ]
        self.assertEqual(declaration(plan)["status"], "declared")

    def test_reset_or_restore_assertions_are_not_consequences_of_earlier_play(self):
        for op in ("reset", "restore"):
            plan = fixture_plan()
            steps = [
                {"op": "act", "action": {"type": "wait"}},
                {"op": "reset"}
                if op == "reset"
                else {"op": "restore", "text": "", "expect": "rejected"},
                assertion("/score", value=0),
            ]
            plan["qa_scenarios"][0]["steps"] = steps
            with self.subTest(op=op), self.assertRaisesRegex(ProviderError, "First playable loop"):
                declaration(plan)

    def test_valid_loop_before_cleanup_is_not_discarded_by_a_later_ui_key(self):
        plan = fixture_plan()
        plan["qa_scenarios"][0]["steps"].append({"op": "key", "key": "Escape"})
        self.assertEqual(declaration(plan)["status"], "declared")

    def test_goal_observation_does_not_cross_an_explicit_reset(self):
        plan = fixture_plan()
        plan["semantic_contract"]["progression"] = [
            dict(
                id="score-goal",
                owner="engine.js",
                source_field_id="score",
                unit="points",
                starts_when="new game",
                completion="earn points",
                prerequisites=[],
                reward_policy="score",
                scenario_ids=["goal-reset"],
            )
        ]
        plan["qa_scenarios"].append(
            {
                "id": "goal-reset",
                "category": "progress",
                "purpose": "Reset is not earned progress",
                "seed": "fixture",
                "steps": [
                    {"op": "act", "action": {"type": "wait"}},
                    {"op": "reset"},
                    assertion("/score", value=0),
                ],
                "affected_files": ["engine.js", "ui.js"],
                "limitations": ["Declaration regression only"],
            }
        )
        with self.assertRaisesRegex(ProviderError, "Progression needs"):
            declaration(plan)


class FiniteDeclarationsReviewTests(unittest.TestCase):
    def test_decimal_exponent_overflow_is_not_a_finite_field_event_or_timing_action(self):
        for kind in ("field", "event", "timing"):
            contract = fixture_plan("fixed_step" if kind == "timing" else "turn_based")[
                "semantic_contract"
            ]
            if kind == "field":
                contract["fields"][0].update(type="number", example_json="1e999")
            elif kind == "event":
                event = contract["events"][0]
                schema = json.loads(event["payload_schema"])
                schema["properties"]["points"]["type"] = "number"
                event["payload_schema"] = json.dumps(schema)
                event["example_json"] = '{"id":"1","type":"score","points":1e999}'
            else:
                contract["timing"]["step_action"] = '{"type":"step","dt":1e999}'
            with self.subTest(kind=kind), self.assertRaisesRegex(ProviderError, "finite JSON"):
                validate_semantic_contract(contract)


if __name__ == "__main__":
    unittest.main()
