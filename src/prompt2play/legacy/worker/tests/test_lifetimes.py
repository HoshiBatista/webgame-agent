"""Camp lessons applied as generic pre-author gates and scoped context tests."""

import copy
import json
import unittest
from prompt2play.legacy.worker.core import (
    ProviderError,
    contract_entries,
    validate_semantic_contract,
)
from prompt2play.legacy.worker.semantics import validate_semantic_coverage
from prompt2play.legacy.worker.pipeline import Pipeline
from prompt2play.legacy.validator.scenarios import validate_scenarios
from .fixtures import fixture_plan, SOURCES, FixtureProvider
from .test_pipeline import job
from .test_semantics import EditingProvider, context


def persistent_plan():
    plan = fixture_plan()
    contract = plan["semantic_contract"]
    contract["state_domains"][0]["lifetime"] = "persistent"
    contract["state_domains"][0]["reset_policy"] = (
        "Explicit new profile clears data; load only replaces after validation"
    )
    contract["persistence"] = [
        {
            "id": "save-format",
            "owner": "ui.js",
            "domain_ids": ["attempt-data"],
            "storage": "local_storage",
            "format_version": "1",
            "validation_rules": ["Finite score, accepted steps agree with progression"],
            "migration_policy": "Accept v1; reject unknown versions without replacement",
            "write_policy": "Write after accepted actions, never while rendering",
            "conflict_policy": "Reject stale base; in-memory checkpoint remains exportable",
            "failure_policy": "Mark memory only on denial; never show durable success",
            "scenario_ids": ["save-roundtrip", "storage-denied"],
        }
    ]

    def scenario(id, steps):
        return dict(
            id=id,
            category="persistence",
            purpose="Protocol-only persistence observation",
            seed="fixture",
            steps=[json.dumps(step) for step in steps],
            affected_files=["engine.js", "ui.js"],
            limitations=["Declaration fixture, not a generated game implementation"],
        )

    equality = {
        "op": "assert",
        "left": {"path": "/score"},
        "cmp": "eq",
        "right": {"saved": "before", "path": "/score"},
    }
    plan["qa_scenarios"] += [
        scenario(
            "save-roundtrip",
            [
                {"op": "act", "action": {"type": "wait"}},
                {"op": "capture", "key": "before"},
                {"op": "serialize", "key": "save1"},
                {"op": "act", "action": {"type": "wait"}},
                {
                    "op": "assert",
                    "left": {"path": "/score"},
                    "cmp": "gt",
                    "right": {"saved": "before", "path": "/score"},
                },
                {"op": "restore", "saved": "save1", "expect": "accepted"},
                equality,
                {"op": "restore", "text": "   ", "expect": "rejected"},
                copy.deepcopy(equality),
            ],
        ),
        scenario(
            "storage-denied",
            [
                {"op": "storage_fault", "mode": "denied"},
                {"op": "act", "action": {"type": "wait"}},
                {
                    "op": "assert",
                    "left": {"path": "/persistence/status"},
                    "cmp": "eq",
                    "right": {"value": "memory-only"},
                },
                {"op": "storage_fault", "mode": "normal"},
            ],
        ),
    ]
    return plan


def transaction_plan():
    plan = fixture_plan()
    plan["semantic_contract"]["transactions"] = [
        {
            "id": "claim-reward",
            "owner": "engine.js",
            "action_json": '{"type":"claim"}',
            "domain_ids": ["attempt-data"],
            "preconditions": ["Objective is ready and reward fits"],
            "commit": ["Mark claimed and credit score together"],
            "rejection_policy": "Failed preflight leaves score and objective unchanged",
            "repeat_policy": "An already claimed objective returns false with no new reward",
            "scenario_ids": ["claim-once"],
        }
    ]
    plan["qa_scenarios"].append(
        dict(
            id="claim-once",
            category="accounting",
            purpose="Reward once",
            seed="fixture",
            steps=[
                json.dumps(step)
                for step in [
                    {"op": "act", "action": {"type": "claim"}},
                    {"op": "capture", "key": "claimed"},
                    {"op": "act", "action": {"type": "claim"}, "repeat": 2},
                    {
                        "op": "assert",
                        "left": {"path": "/score"},
                        "cmp": "eq",
                        "right": {"saved": "claimed", "path": "/score"},
                    },
                ]
            ],
            affected_files=["engine.js", "ui.js"],
            limitations=["Plan fixture; no actual reward implementation"],
        )
    )
    return plan


class LifetimeContractTests(unittest.TestCase):
    def test_all_declared_fields_have_exactly_one_authoritative_lifetime(self):
        for mutation in ("missing", "duplicate", "wrong-owner", "blank-reset"):
            contract = fixture_plan()["semantic_contract"]
            domain = contract["state_domains"][0]
            if mutation == "missing":
                domain["field_ids"].pop()
            elif mutation == "duplicate":
                contract["state_domains"].append({**domain, "id": "duplicate-domain"})
            elif mutation == "wrong-owner":
                domain["owner"] = "ui.js"
            else:
                domain["reset_policy"] = " "
            with self.subTest(mutation=mutation), self.assertRaises(ProviderError):
                validate_semantic_contract(contract)

    def test_optional_campaign_and_saves_are_not_forced_on_simple_games(self):
        plan = fixture_plan()
        validate_semantic_contract(plan["semantic_contract"])
        coverage = validate_semantic_coverage(
            plan["semantic_contract"], validate_scenarios(plan["qa_scenarios"])
        )
        self.assertEqual(coverage["obligations"], [])
        self.assertEqual(coverage["status"], "declared")

    def test_missing_progress_loop_stops_before_parallel_author_calls(self):
        provider = EditingProvider(
            plan_edit=lambda plan: plan["semantic_contract"]["first_playable_loop"].update(
                scenario_id="invented"
            )
        )
        with self.assertRaisesRegex(ProviderError, "First playable loop"):
            Pipeline(job(), provider).run()
        self.assertEqual(provider.calls, ["plan"])

    def test_unreachable_unlock_cycle_and_unknown_progress_sources_rejected(self):
        contract = fixture_plan()["semantic_contract"]
        goal = dict(
            id="first-goal",
            owner="engine.js",
            source_field_id="score",
            unit="points",
            starts_when="accepted",
            completion="score reaches ten",
            prerequisites=["second-goal"],
            reward_policy="once",
            scenario_ids=["progress"],
        )
        contract["progression"] = [
            goal,
            {**goal, "id": "second-goal", "prerequisites": ["first-goal"]},
        ]
        with self.assertRaisesRegex(ProviderError, "cycle"):
            validate_semantic_contract(contract)
        contract["progression"][1]["prerequisites"] = []
        validate_semantic_contract(contract)
        contract["progression"][0]["source_field_id"] = "invented"
        with self.assertRaisesRegex(ProviderError, "authoritative"):
            validate_semantic_contract(contract)

    def test_transactions_need_same_owner_and_real_repeated_command(self):
        plan = transaction_plan()
        validate_semantic_contract(plan["semantic_contract"])
        validate_semantic_coverage(
            plan["semantic_contract"], validate_scenarios(plan["qa_scenarios"])
        )
        steps = plan["qa_scenarios"][-1]["steps"]
        steps[2] = json.dumps({"op": "act", "action": {"type": "wait"}, "repeat": 2})
        with self.assertRaisesRegex(ProviderError, "repeats its real command"):
            validate_semantic_coverage(
                plan["semantic_contract"], validate_scenarios(plan["qa_scenarios"])
            )
        plan["semantic_contract"]["transactions"][0]["owner"] = "ui.js"
        with self.assertRaisesRegex(ProviderError, "own all"):
            validate_semantic_contract(plan["semantic_contract"])

    def test_persistence_requires_roundtrip_rejection_and_storage_failure_observations(self):
        plan = persistent_plan()
        validate_semantic_contract(plan["semantic_contract"])
        scenarios = validate_scenarios(plan["qa_scenarios"])
        coverage = validate_semantic_coverage(plan["semantic_contract"], scenarios)
        self.assertEqual(coverage["obligations"][0]["contract_id"], "save-format")
        for mutation in ("no-rejection", "literal-only", "no-fault"):
            bad = copy.deepcopy(scenarios)
            if mutation == "no-rejection":
                bad[2]["steps"] = bad[2]["steps"][:7]
            elif mutation == "literal-only":
                for step in bad[2]["steps"]:
                    if step["op"] == "assert":
                        step["right"] = {"value": 1}
            else:
                bad[3]["steps"] = bad[3]["steps"][1:]
            with self.subTest(mutation=mutation), self.assertRaises(ProviderError):
                validate_semantic_coverage(plan["semantic_contract"], bad)

    def test_export_only_persistence_does_not_require_local_storage_fault(self):
        plan = persistent_plan()
        plan["semantic_contract"]["persistence"][0].update(
            storage="export_only", scenario_ids=["save-roundtrip"]
        )
        plan["qa_scenarios"].pop()
        validate_semantic_coverage(
            plan["semantic_contract"], validate_scenarios(plan["qa_scenarios"])
        )

    def test_storage_contract_dependency_includes_actual_data_and_ui_consumers(self):
        contract = persistent_plan()["semantic_contract"]
        self.assertEqual(
            contract_entries(contract)["save-format"], {"engine.js", "renderer.js", "ui.js"}
        )
        self.assertNotIn("audio.js", contract_entries(contract)["save-format"])

    def test_tautology_or_reset_only_cannot_stand_in_for_a_playable_loop(self):
        for steps in (
            [
                {"op": "reset"},
                {"op": "assert", "left": {"path": "/score"}, "cmp": "eq", "right": {"value": 0}},
            ],
            [
                {"op": "act", "action": {"type": "wait"}},
                {
                    "op": "assert",
                    "left": {"path": "/score"},
                    "cmp": "eq",
                    "right": {"path": "/score"},
                },
            ],
            [
                {"op": "act", "action": {"type": "wait"}},
                {
                    "op": "assert",
                    "left": {"value": {"path": "/fake"}},
                    "cmp": "ne",
                    "right": {"value": {}},
                },
            ],
        ):
            plan = fixture_plan()
            scenarios = validate_scenarios(plan["qa_scenarios"])
            scenarios[0]["steps"] = steps
            with (
                self.subTest(steps=steps),
                self.assertRaisesRegex(ProviderError, "First playable loop"),
            ):
                validate_semantic_coverage(plan["semantic_contract"], scenarios)

    def test_an_assertion_before_duplicate_reward_does_not_cover_its_effect(self):
        plan = transaction_plan()
        scenarios = validate_scenarios(plan["qa_scenarios"])
        steps = scenarios[-1]["steps"]
        scenarios[-1]["steps"] = [steps[1], steps[3], steps[0], steps[2]]
        with self.assertRaisesRegex(ProviderError, "repeats its real command"):
            validate_semantic_coverage(plan["semantic_contract"], scenarios)

    def test_restore_needs_its_own_prior_domain_comparison_not_a_later_ui_tautology(self):
        for mutation in ("wrong-domain", "shared-late-assertion", "capture-after-restore"):
            plan = persistent_plan()
            scenarios = validate_scenarios(plan["qa_scenarios"])
            steps = scenarios[2]["steps"]
            if mutation == "wrong-domain":
                for step in steps:
                    if step["op"] == "assert":
                        step["left"]["path"] = "/paused"
                        step["right"]["path"] = "/paused"
            elif mutation == "shared-late-assertion":
                del steps[6]
            else:
                steps.insert(6, {"op": "capture", "key": "before"})
            with (
                self.subTest(mutation=mutation),
                self.assertRaisesRegex(ProviderError, "accepted save/restore"),
            ):
                validate_semantic_coverage(plan["semantic_contract"], scenarios)

    def test_roundtrip_must_distinguish_a_noop_importer_from_real_restoration(self):
        plan = persistent_plan()
        scenarios = validate_scenarios(plan["qa_scenarios"])
        del scenarios[2]["steps"][4]
        with self.assertRaisesRegex(ProviderError, "accepted save/restore"):
            validate_semantic_coverage(plan["semantic_contract"], scenarios)

    def test_next_action_cannot_supply_the_assertion_for_a_repeated_transaction(self):
        plan = transaction_plan()
        scenarios = validate_scenarios(plan["qa_scenarios"])
        scenarios[-1]["steps"].insert(3, {"op": "act", "action": {"type": "wait"}})
        with self.assertRaisesRegex(ProviderError, "repeats its real command"):
            validate_semantic_coverage(plan["semantic_contract"], scenarios)

    def test_progression_checks_its_real_source_after_play_not_an_unrelated_reset(self):
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
                scenario_ids=["progress"],
            )
        ]
        scenarios = validate_scenarios(plan["qa_scenarios"])
        scenarios[0]["steps"][-1]["left"]["path"] = "/tick"
        scenarios[0]["steps"][-1]["right"]["path"] = "/tick"
        with self.assertRaisesRegex(ProviderError, "Progression needs"):
            validate_semantic_coverage(plan["semantic_contract"], scenarios)


class LifetimeRevisionTests(unittest.TestCase):
    def test_equivalent_json_formatting_keeps_local_revision_context_small(self):
        previous = fixture_plan()
        task = job()
        task.update(kind="revise", base_version_id="base")
        provider = EditingProvider(
            affected=["audio.js"],
            plan_edit=lambda p: p.update(
                state_schema=json.dumps(json.loads(p["state_schema"]), indent=2)
            ),
        )
        Pipeline(task, provider, base_version={"files": SOURCES, "spec": previous}).run()
        prompt = next(p for role, p in provider.prompts if role == "audio")
        self.assertEqual(context(prompt)["integration_dependency_sources"], {})
        self.assertEqual(context(prompt)["current_source"], SOURCES["audio.js"])

    def test_lifetime_edit_requires_dependents_before_replacing_source(self):
        previous = fixture_plan()
        task = job()
        task.update(kind="revise", base_version_id="base")
        provider = EditingProvider(
            affected=["engine.js"],
            plan_edit=lambda p: p["semantic_contract"]["state_domains"][0].update(
                reset_policy="Reset by phase"
            ),
        )
        with self.assertRaisesRegex(ProviderError, "semantic contracts"):
            Pipeline(task, provider, base_version={"files": SOURCES, "spec": previous}).run()
        self.assertEqual(provider.calls, ["plan"])

    def test_changed_lifetime_sends_neighbors_before_first_revision_author_call(self):
        previous = fixture_plan()
        task = job()
        task.update(kind="revise", base_version_id="base")
        provider = EditingProvider(
            affected=["engine.js", "renderer.js", "ui.js"],
            plan_edit=lambda p: p["semantic_contract"]["state_domains"][0].update(
                reset_policy="Reset by phase"
            ),
        )
        output = Pipeline(task, provider, base_version={"files": SOURCES, "spec": previous}).run()
        prompt = next(p for role, p in provider.prompts if role == "engine")
        self.assertEqual(
            context(prompt)["integration_dependency_sources"],
            {"renderer.js": SOURCES["renderer.js"], "ui.js": SOURCES["ui.js"]},
        )
        self.assertEqual(output["files"]["audio.js"], SOURCES["audio.js"])
        self.assertNotIn("audio", provider.calls)

    def test_old_semantic_version_is_readable_but_requires_full_revision_upgrade(self):
        old = fixture_plan()
        for key in (
            "state_domains",
            "transactions",
            "progression",
            "persistence",
            "first_playable_loop",
        ):
            del old["semantic_contract"][key]
        old["semantic_contract"]["version"] = 2
        validate_semantic_contract(old["semantic_contract"])
        task = job()
        task.update(kind="revise", base_version_id="v2")
        provider = FixtureProvider(affected=["audio.js"])
        with self.assertRaisesRegex(ProviderError, "one-time upgrade"):
            Pipeline(task, provider, base_version={"files": SOURCES, "spec": old}).run()
        self.assertEqual(provider.calls, ["plan"])


if __name__ == "__main__":
    unittest.main()
