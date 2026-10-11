"""Durak lessons as optional contracts, focused context and honest evidence.

Only authored Python declarations, provider doubles and syntax checks execute.
No model-generated JavaScript, browser, audio or external model runs here.
"""

from __future__ import annotations

import copy
import json
import unittest

import jsonschema

from prompt2play.legacy.worker.core import (
    PLAN_SCHEMA,
    PLAN_OUTPUT_SCHEMA,
    PROMPT_BOUNDARY,
    ProviderError,
    contract_entries,
    presentation_mode,
    validate_semantic_contract,
)
from prompt2play.legacy.worker.pipeline import Pipeline
from prompt2play.legacy.worker.providers import parse_json
from prompt2play.legacy.worker.semantics import (
    validate_semantic_coverage,
    review_obligation_context,
)
from prompt2play.legacy.validator.scenarios import validate_scenarios
from .fixtures import SOURCES, FixtureProvider, fixture_issue, fixture_plan
from .test_lifetimes import persistent_plan, transaction_plan
from .test_pipeline import job
from .test_semantics import EditingProvider, context


def obligation(kind="focus", *, id="input-identity", owners=None, contracts=None, scenarios=None):
    return {
        "id": id,
        "kind": kind,
        "owners": owners or ["ui.js"],
        "contract_ids": contracts or ["resource:raf"],
        "scenario_ids": scenarios or [],
        "limitations": [
            "Source-review declaration; no browser or asynchronous race executed by this fixture."
        ],
    }


def extended_plan(mode="canvas", items=None):
    plan = fixture_plan()
    plan["presentation_mode"] = mode
    plan["semantic_contract"]["review_obligations"] = copy.deepcopy(items or [])
    return plan


def declaration(plan):
    validate_semantic_contract(plan["semantic_contract"])
    return validate_semantic_coverage(
        plan["semantic_contract"], validate_scenarios(plan["qa_scenarios"])
    )


def sections(prompt):
    return [json.loads(line) for line in prompt.partition(PROMPT_BOUNDARY)[2].splitlines()]


def revision_job():
    task = job()
    task.update(kind="revise", base_version_id="v3-base")
    return task


class OptionalContractTests(unittest.TestCase):
    def test_historical_v3_remains_readable_while_live_output_requires_explicit_extensions(self):
        historical = fixture_plan()
        jsonschema.validate(historical, PLAN_SCHEMA)
        validate_semantic_contract(historical["semantic_contract"])
        self.assertEqual(presentation_mode(historical), "canvas")
        with self.assertRaises(ProviderError):
            parse_json(json.dumps(historical), PLAN_OUTPUT_SCHEMA)
        complete = extended_plan()
        self.assertEqual(parse_json(json.dumps(complete), PLAN_OUTPUT_SCHEMA), complete)
        self.assertEqual(declaration(complete)["obligations"], [])

    def test_strict_provider_schema_has_no_optional_object_properties(self):
        pending = [PLAN_OUTPUT_SCHEMA]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)

    def test_obligation_id_reference_kind_owner_and_size_bounds_reject_bad_declarations(self):
        def changed(key, value):
            return lambda plan: plan["semantic_contract"]["review_obligations"][0].update(
                {key: value}
            )

        edits = [
            changed("id", "tick"),
            changed("kind", "make_every_game_multiplayer"),
            changed("contract_ids", ["invented"]),
            changed("contract_ids", []),
            changed("contract_ids", ["input-identity"]),
            changed("owners", ["audio.js"]),
            changed("owners", ["ui.js", "ui.js"]),
            changed("owners", []),
            changed("limitations", [" "]),
            changed("limitations", ["x" * 601]),
            lambda p: p["semantic_contract"].update(
                review_obligations=[obligation(id="risk" + str(i)) for i in range(9)]
            ),
        ]
        for index, edit in enumerate(edits):
            plan = extended_plan(items=[obligation()])
            edit(plan)
            with self.subTest(index=index), self.assertRaises(ProviderError):
                declaration(plan)

    def test_obligations_cannot_reference_one_another_even_in_a_forward_list_order(self):
        plan = extended_plan(items=[obligation(contracts=["second"]), obligation(id="second")])
        with self.assertRaisesRegex(ProviderError, "known references"):
            declaration(plan)
        plan["semantic_contract"]["review_obligations"].reverse()
        with self.assertRaisesRegex(ProviderError, "known references"):
            declaration(plan)

    def test_scenario_bindings_must_exist_cover_owners_and_be_observable(self):
        for mutation in ("missing", "missing-owner", "exists-only"):
            plan = extended_plan(items=[obligation(scenarios=["progress"])])
            if mutation == "missing":
                plan["semantic_contract"]["review_obligations"][0]["scenario_ids"] = ["missing"]
            elif mutation == "missing-owner":
                plan["qa_scenarios"][0]["affected_files"] = ["engine.js"]
            else:
                plan["qa_scenarios"][1]["steps"] = [
                    json.dumps(step)
                    for step in [
                        {"op": "reset"},
                        {"op": "assert", "left": {"path": "/score"}, "cmp": "exists"},
                    ]
                ]
                plan["semantic_contract"]["review_obligations"][0]["scenario_ids"] = ["restart"]
            with self.subTest(mutation=mutation), self.assertRaises(ProviderError):
                declaration(plan)

    def test_review_only_obligation_is_explicitly_limited_not_silently_executed(self):
        plan = extended_plan(items=[obligation()])
        coverage = declaration(plan)
        self.assertEqual(coverage["status"], "declared")
        self.assertEqual(coverage["obligations"][0]["evidence_scope"], "review_only")
        self.assertEqual(coverage["obligations"][0]["scenario_ids"], [])
        plan["semantic_contract"]["review_obligations"][0]["limitations"] = []
        with self.assertRaisesRegex(ProviderError, "explain why"):
            declaration(plan)

    def test_local_storage_conflict_requirement_does_not_force_storage_into_other_games(self):
        item = obligation("durable_conflict", contracts=["save-format"])
        plan = persistent_plan()
        plan["semantic_contract"]["review_obligations"] = [item]
        self.assertEqual(declaration(plan)["obligations"][-1]["review_kind"], "durable_conflict")
        plan["semantic_contract"]["persistence"][0]["storage"] = "export_only"
        with self.assertRaisesRegex(ProviderError, "local_storage"):
            declaration(plan)
        self.assertEqual(declaration(extended_plan())["obligations"], [])

    def test_alternative_choice_binding_needs_distinct_observed_strategy_commands(self):
        plan = extended_plan(
            items=[obligation("alternative_choice", contracts=["tick"], scenarios=["branches"])]
        )
        scenario = copy.deepcopy(plan["qa_scenarios"][0])
        scenario.update(
            id="branches",
            category="strategy",
            purpose="Compare two explicitly declared legal choices",
        )
        scenario["steps"] = [
            json.dumps(step)
            for step in [
                {"op": "act", "action": {"type": "primary"}},
                {"op": "assert", "left": {"path": "/score"}, "cmp": "eq", "right": {"value": 1}},
                {"op": "reset", "seed": "fixture"},
                {"op": "act", "action": {"type": "alternative"}},
                {"op": "assert", "left": {"path": "/score"}, "cmp": "eq", "right": {"value": 2}},
            ]
        ]
        plan["qa_scenarios"].append(scenario)
        coverage = declaration(plan)
        self.assertEqual(coverage["obligations"][0]["evidence_scope"], "declared_scenarios")
        scenario["steps"][3] = json.dumps({"op": "act", "action": {"type": "primary"}, "repeat": 2})
        with self.assertRaisesRegex(ProviderError, "different real commands"):
            declaration(plan)


class FocusedContextTests(unittest.TestCase):
    def replacement_plan(self, direction):
        previous = fixture_plan()
        if direction == "rule-to-review":
            previous["semantic_contract"]["invariants"].append(
                {
                    "id": "other-rule",
                    "statement": "Controls expose actual status",
                    "owners": ["ui.js"],
                    "check_strategy": "Inspect the real status after an action",
                }
            )
            current = copy.deepcopy(previous)
            current["semantic_contract"]["invariants"] = current["semantic_contract"]["invariants"][
                1:
            ]
            current["semantic_contract"]["review_obligations"] = [
                obligation(id="nonnegative-score")
            ]
        else:
            previous["semantic_contract"]["review_obligations"] = [obligation()]
            current = copy.deepcopy(previous)
            current["semantic_contract"]["review_obligations"] = []
            current["semantic_contract"]["invariants"].append(
                {
                    "id": "input-identity",
                    "statement": "A changed engine rule that requires its real owner",
                    "owners": ["engine.js", "ui.js"],
                    "check_strategy": "Inspect rule consequences",
                }
            )
        return previous, current

    def test_reusing_review_id_cannot_hide_an_added_or_removed_gameplay_contract(self):
        for direction in ("rule-to-review", "review-to-rule"):
            previous, current = self.replacement_plan(direction)
            provider = EditingProvider(
                affected=["ui.js"],
                plan_edit=lambda plan: plan.update(
                    semantic_contract=copy.deepcopy(current["semantic_contract"])
                ),
            )
            pipeline = Pipeline(
                revision_job(), provider, base_version={"files": SOURCES, "spec": previous}
            )
            with (
                self.subTest(direction=direction),
                self.assertRaisesRegex(ProviderError, "dependent modules"),
            ):
                pipeline.plan({})
            self.assertEqual(provider.calls, ["plan"])

    def test_same_id_kind_replacement_is_allowed_when_actual_dependents_are_selected(self):
        for direction in ("rule-to-review", "review-to-rule"):
            previous, current = self.replacement_plan(direction)
            provider = EditingProvider(
                affected=["engine.js", "ui.js"],
                plan_edit=lambda plan: plan.update(
                    semantic_contract=copy.deepcopy(current["semantic_contract"])
                ),
            )
            pipeline = Pipeline(
                revision_job(), provider, base_version={"files": SOURCES, "spec": previous}
            )
            with self.subTest(direction=direction):
                pipeline.plan({})
                self.assertEqual(pipeline._revision_dependencies("ui.js"), {"engine.js", "ui.js"})
                self.assertEqual(pipeline._revision_dependencies("audio.js"), set())

    def test_removing_only_review_metadata_still_preserves_untouched_neighbors(self):
        previous = extended_plan(items=[obligation("information_boundary", contracts=["tick"])])
        provider = EditingProvider(
            affected=["ui.js"],
            plan_edit=lambda plan: plan["semantic_contract"].update(review_obligations=[]),
        )
        pipeline = Pipeline(
            revision_job(), provider, base_version={"files": SOURCES, "spec": previous}
        )
        pipeline.plan({})
        self.assertEqual(pipeline.cp["affected"], ["ui.js"])
        self.assertEqual(pipeline._revision_dependencies("ui.js"), {"engine.js", "ui.js"})

    def test_context_only_selects_explicit_relevant_obligations_without_genre_heuristics(self):
        contract = extended_plan(items=[obligation()])["semantic_contract"]
        focus = review_obligation_context(contract, "ui.js")
        self.assertEqual(focus["obligation_ids"], ["input-identity"])
        for filename in ("engine.js", "renderer.js", "audio.js"):
            self.assertIsNone(review_obligation_context(contract, filename))
        self.assertEqual(focus["status"], "declared")
        self.assertEqual(contract_entries(contract)["input-identity"], {"ui.js"})

    def test_pipeline_supplies_strict_output_schema_but_does_not_rewrite_legacy_v3_by_default(self):
        class SchemaRecorder(FixtureProvider):
            def generate(self, prompt, schema, role, *args, **kwargs):
                if role == "plan":
                    self.requested_schema = copy.deepcopy(schema)
                return super().generate(prompt, schema, role, *args, **kwargs)

        provider = SchemaRecorder(affected=["audio.js"])
        output = Pipeline(
            revision_job(), provider, base_version={"files": SOURCES, "spec": fixture_plan()}
        ).run()
        self.assertEqual(provider.requested_schema, PLAN_OUTPUT_SCHEMA)
        self.assertEqual(provider.calls, ["plan", "audio", "review"])
        for name in ("engine.js", "renderer.js", "ui.js"):
            self.assertEqual(output["files"][name], SOURCES[name])

    def test_new_review_scope_supplies_named_neighbor_source_without_forcing_its_rewrite(self):
        def edit(plan):
            plan["presentation_mode"] = "canvas"
            plan["semantic_contract"]["review_obligations"] = [
                obligation("information_boundary", id="view-access", contracts=["tick"])
            ]

        provider = EditingProvider(plan_edit=edit, affected=["ui.js"])
        output = Pipeline(
            revision_job(), provider, base_version={"files": SOURCES, "spec": fixture_plan()}
        ).run()
        self.assertEqual(provider.calls, ["plan", "ui", "review"])
        prompt = next(prompt for role, prompt in provider.prompts if role == "ui")
        self.assertEqual(
            context(prompt)["integration_dependency_sources"], {"engine.js": SOURCES["engine.js"]}
        )
        self.assertEqual(output["files"]["engine.js"], SOURCES["engine.js"])
        role_scope = next(
            part["role_contract"] for part in sections(prompt) if "role_contract" in part
        )
        self.assertEqual(role_scope["review_focus"]["obligation_ids"], ["view-access"])

    def test_concrete_contract_review_expands_to_bound_dependencies_only(self):
        def edit(plan):
            plan["semantic_contract"]["review_obligations"] = [
                obligation("information_boundary", id="view-access", contracts=["tick"])
            ]

        issue = fixture_issue("ui.js", scope="contract", contract_ids=["view-access"], scenario="")
        provider = EditingProvider(plan_edit=edit, issue=issue)
        Pipeline(job(), provider).run()
        for role in ("engine", "ui"):
            self.assertEqual(provider.calls.count(role), 2)
        for role in ("audio", "renderer"):
            self.assertEqual(provider.calls.count(role), 1)
        repaired = [prompt for role, prompt in provider.prompts if role == "ui"][-1]
        self.assertEqual(
            context(repaired)["integration_dependency_sources"], {"engine.js": SOURCES["engine.js"]}
        )

    def test_scoped_review_guidance_stays_in_stable_sections_and_never_claims_runtime(self):
        def edit(plan):
            plan["semantic_contract"]["review_obligations"] = [obligation()]

        provider = EditingProvider(plan_edit=edit, issue=fixture_issue("ui.js"))
        result = Pipeline(job(), provider).run()
        prompts = [prompt for role, prompt in provider.prompts if role == "ui"]
        self.assertEqual(sections(prompts[0])[:-1], sections(prompts[1])[:-1])
        for role, prompt in provider.prompts:
            if role in {"engine", "renderer", "audio"}:
                role_scope = next(
                    part["role_contract"] for part in sections(prompt) if "role_contract" in part
                )
                self.assertNotIn("review_focus", role_scope)
            if role == "review":
                focus = next(
                    part["declared_review_focus"]
                    for part in sections(prompt)
                    if "declared_review_focus" in part
                )
                self.assertEqual(focus["status"], "declared")
            self.assertNotIn("durak-card-club", prompt)
        coverage = next(
            check
            for check in result["validation"]["checks"]
            if check["name"] == "semantic_coverage"
        )
        self.assertEqual(coverage["check_kind"], "static")
        self.assertEqual(coverage["evidence"]["status"], "declared")
        self.assertEqual(result["validation"]["status"], "partial")

    def test_presentation_change_requires_only_ui_and_renderer_and_supplies_actual_neighbors(self):
        for selected in (["ui.js"], ["renderer.js"]):
            provider = EditingProvider(
                affected=selected, plan_edit=lambda p: p.update(presentation_mode="dom")
            )
            pipeline = Pipeline(
                revision_job(), provider, base_version={"files": SOURCES, "spec": fixture_plan()}
            )
            with (
                self.subTest(selected=selected),
                self.assertRaisesRegex(ProviderError, "presentation mode"),
            ):
                pipeline.plan({})
            self.assertEqual(provider.calls, ["plan"])
        provider = EditingProvider(
            affected=["renderer.js", "ui.js"], plan_edit=lambda p: p.update(presentation_mode="dom")
        )
        pipeline = Pipeline(
            revision_job(), provider, base_version={"files": SOURCES, "spec": fixture_plan()}
        )
        pipeline.plan({})
        self.assertEqual(set(pipeline.cp["affected"]), {"renderer.js", "ui.js"})
        self.assertEqual(pipeline._revision_dependencies("ui.js"), {"renderer.js", "ui.js"})
        self.assertEqual(pipeline._revision_dependencies("engine.js"), set())
        self.assertEqual(pipeline._revision_dependencies("audio.js"), set())

    def test_invalid_mode_or_invented_obligation_fails_before_author_spend(self):
        for edit in (
            lambda p: p.update(presentation_mode="unity-native"),
            lambda p: p["semantic_contract"].update(
                review_obligations=[obligation(contracts=["invented"])]
            ),
        ):
            provider = EditingProvider(plan_edit=edit)
            with self.subTest(edit=edit), self.assertRaises(ProviderError):
                Pipeline(job(), provider).run()
            self.assertEqual(provider.calls, ["plan"])


class ReplayLifetimeTests(unittest.TestCase):
    def replay_scenario(self, steps):
        plan = transaction_plan()
        scenarios = validate_scenarios(plan["qa_scenarios"])
        # The semantic interval check consumes normalized declarative operations.
        # Lifecycle operation syntax/execution is covered by the validator suite.
        scenarios[-1]["steps"] = steps
        return plan["semantic_contract"], scenarios

    def test_two_first_claims_separated_by_accepted_import_are_not_repeat_evidence(self):
        contract, scenarios = self.replay_scenario(
            [
                {"op": "serialize", "key": "unclaimed"},
                {"op": "act", "action": {"type": "claim"}},
                {"op": "restore", "saved": "unclaimed", "expect": "accepted"},
                {"op": "act", "action": {"type": "claim"}},
                {"op": "assert", "left": {"path": "/score"}, "cmp": "eq", "right": {"value": 1}},
            ]
        )
        with self.assertRaisesRegex(ProviderError, "repeats its real command"):
            validate_semantic_coverage(contract, scenarios)

    def test_reload_and_remount_begin_new_replay_intervals(self):
        for boundary in ({"op": "reload"}, {"op": "lifecycle", "event": "remount"}):
            contract, scenarios = self.replay_scenario(
                [
                    {"op": "act", "action": {"type": "claim"}},
                    boundary,
                    {
                        "op": "assert",
                        "left": {"path": "/score"},
                        "cmp": "eq",
                        "right": {"value": 0},
                    },
                    {"op": "act", "action": {"type": "claim"}},
                    {
                        "op": "assert",
                        "left": {"path": "/score"},
                        "cmp": "eq",
                        "right": {"value": 1},
                    },
                ]
            )
            with (
                self.subTest(boundary=boundary),
                self.assertRaisesRegex(ProviderError, "repeats its real command"),
            ):
                validate_semantic_coverage(contract, scenarios)

    def test_hidden_return_and_rejected_import_preserve_a_single_replay_interval(self):
        equality = {
            "op": "assert",
            "left": {"path": "/score"},
            "cmp": "eq",
            "right": {"saved": "claimed", "path": "/score"},
        }
        for middle in (
            [{"op": "restore", "text": "invalid", "expect": "rejected"}, equality],
            [
                {"op": "lifecycle", "event": "hide"},
                equality,
                {"op": "lifecycle", "event": "show"},
                equality,
            ],
        ):
            contract, scenarios = self.replay_scenario(
                [
                    {"op": "act", "action": {"type": "claim"}},
                    {"op": "capture", "key": "claimed"},
                    *copy.deepcopy(middle),
                    {"op": "act", "action": {"type": "claim"}},
                    equality,
                ]
            )
            with self.subTest(middle=middle):
                self.assertEqual(
                    validate_semantic_coverage(contract, scenarios)["status"], "declared"
                )


if __name__ == "__main__":
    unittest.main()
