"""Regression coverage for genre-neutral planning/context and exact evidence.

Only test model doubles and syntax parsing; never execute model-generated JS here.
"""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from prompt2play.legacy.worker.core import (
    FILES,
    PROMPT_BOUNDARY,
    ProviderError,
    BudgetExceeded,
    usage_record,
    validate_semantic_contract,
    validate_review,
)
from prompt2play.legacy.worker.pipeline import Pipeline
from prompt2play.legacy.validator.evidence import artifact_manifest, report_matches
from .fixtures import FixtureProvider, PLAN, SOURCES, fixture_plan, fixture_issue
from .test_pipeline import job


class EditingProvider(FixtureProvider):
    def __init__(self, *, plan_edit=None, issue=None, **kwargs):
        super().__init__(**kwargs)
        self.plan_edit = plan_edit
        self.issue = issue
        self.prompts = []

    def generate(self, prompt, schema, role, *args, **kwargs):
        reply = super().generate(prompt, schema, role, *args, **kwargs)
        self.prompts.append((role, prompt))
        if role == "plan" and self.plan_edit:
            self.plan_edit(reply.data)
        if role == "review" and self.issue and self.calls.count("review") == 1:
            reply.data = {
                "approved": False,
                "summary": "Controlled regression review",
                "issues": [copy.deepcopy(self.issue)],
            }
        return reply


def context(prompt):
    return json.loads(prompt.partition(PROMPT_BOUNDARY)[2].splitlines()[-1])["current_context"]


class SemanticPlanTests(unittest.TestCase):
    def test_turn_based_and_fixed_step_without_required_avatar(self):
        for mode in ("turn_based", "fixed_step"):
            plan = fixture_plan(mode)
            self.assertIs(
                validate_semantic_contract(plan["semantic_contract"]), plan["semantic_contract"]
            )
            self.assertNotIn("player", json.loads(plan["state_schema"]))
        p = Pipeline(job(), FixtureProvider())
        self.assertNotIn("REFERENCE STYLE EXCERPT", p._prefix("engine"))
        self.assertIn("NO mandatory wait action", p._prefix("engine"))

    def test_invalid_units_event_examples_and_terminal_transitions_fail_before_authors(self):
        def bad_unit(p):
            p["semantic_contract"]["fields"][0]["unit"] = ""

        def bad_example(p):
            p["semantic_contract"]["events"][0]["example_json"] = (
                '{"id":"1","type":"score","points":"one"}'
            )

        def terminal_action(p):
            p["semantic_contract"]["state_machines"][0]["transitions"][0]["from"] = "won"

        def duplicate(p):
            p["semantic_contract"]["fields"][0]["id"] = "timing"

        for edit in (bad_unit, bad_example, terminal_action, duplicate):
            provider = EditingProvider(plan_edit=edit)
            with self.subTest(edit=edit.__name__), self.assertRaises(ProviderError):
                Pipeline(job(), provider).run()
            self.assertEqual(provider.calls, ["plan"])

    def test_schema_references_and_nonfinite_examples_never_resolve_or_execute(self):
        contract = copy.deepcopy(PLAN["semantic_contract"])
        contract["events"][0]["payload_schema"] = '{"$ref":"https://example.invalid/schema"}'
        with self.assertRaisesRegex(ProviderError, "self-contained"):
            validate_semantic_contract(contract)
        contract = copy.deepcopy(PLAN["semantic_contract"])
        contract["fields"][0]["example_json"] = "NaN"
        with self.assertRaisesRegex(ProviderError, "finite JSON"):
            validate_semantic_contract(contract)

    def test_private_fields_and_cyclic_machines_are_permitted(self):
        contract = copy.deepcopy(PLAN["semantic_contract"])
        contract["fields"][0]["consumers"] = []
        machine = contract["state_machines"][0]
        machine["terminal_states"] = []
        machine["transitions"].append(
            {
                "from": "won",
                "to": "playing",
                "trigger": "cycle phase",
                "effect": "no terminal state declared",
            }
        )
        validate_semantic_contract(contract)

    def test_invalid_and_missing_lifecycle_scenarios_reject_before_fanout(self):
        def absent(p):
            p["qa_scenarios"] = p["qa_scenarios"][:1]

        def code(p):
            p["qa_scenarios"][0]["steps"].insert(0, '{"op":"eval","source":"throw 1"}')

        def clock(p):
            p["qa_scenarios"][0]["steps"].insert(0, '{"op":"advance","frames":1}')

        for edit in (absent, code, clock):
            provider = EditingProvider(plan_edit=edit)
            with self.subTest(edit=edit.__name__), self.assertRaises(ProviderError):
                Pipeline(job(), provider).run()
            self.assertEqual(provider.calls, ["plan"])

    def test_shared_semantic_revision_requires_only_real_dependents(self):
        base = {"files": copy.deepcopy(SOURCES), "spec": copy.deepcopy(PLAN), "is_reference": False}
        task = job()
        task.update(kind="revise", base_version_id="base")

        def change(p):
            p["semantic_contract"]["fields"][1]["unit"] = "currency"

        provider = EditingProvider(plan_edit=change, affected=["engine.js"])
        with self.assertRaisesRegex(ProviderError, "semantic contracts"):
            Pipeline(task, provider, base_version=base).run()
        self.assertEqual(provider.calls, ["plan"])
        provider = EditingProvider(plan_edit=change, affected=["engine.js", "renderer.js", "ui.js"])
        result = Pipeline(task, provider, base_version=base).run()
        self.assertNotIn("audio", provider.calls)
        self.assertEqual(result["files"]["audio.js"], base["files"]["audio.js"])

    def test_legacy_revision_requires_coordinated_upgrade_before_authors(self):
        previous = copy.deepcopy(PLAN)
        previous.pop("semantic_contract")
        previous.pop("qa_scenarios")
        task = job()
        task.update(kind="revise", base_version_id="legacy-base")
        provider = FixtureProvider(affected=["audio.js"])
        with self.assertRaisesRegex(ProviderError, "one-time upgrade"):
            Pipeline(task, provider, base_version={"files": SOURCES, "spec": previous}).run()
        self.assertEqual(provider.calls, ["plan"])


class RepairContextTests(unittest.TestCase):
    def test_local_contract_reference_does_not_rewrite_consumers(self):
        issue = fixture_issue("renderer.js", contract_ids=["score"])
        provider = EditingProvider(issue=issue)
        Pipeline(job(), provider).run()
        self.assertEqual(provider.calls.count("renderer"), 2)
        for role in ("engine", "audio", "ui"):
            self.assertEqual(provider.calls.count(role), 1)
        repair = context([p for role, p in provider.prompts if role == "renderer"][-1])
        self.assertEqual(repair["integration_dependency_sources"], {})
        self.assertEqual(repair["current_source"], SOURCES["renderer.js"])
        self.assertNotIn("other_module_interfaces", repair)

    def test_integration_repair_has_full_named_sources_not_arbitrary_prefixes(self):
        issue = fixture_issue(
            "engine.js",
            scope="integration",
            affected_files=["engine.js", "ui.js"],
            contract_ids=["score"],
        )
        provider = EditingProvider(issue=issue)
        Pipeline(job(), provider).run()
        self.assertEqual(provider.calls.count("engine"), 2)
        self.assertEqual(provider.calls.count("ui"), 2)
        self.assertEqual(provider.calls.count("renderer"), 1)
        self.assertEqual(provider.calls.count("audio"), 1)
        repair = context([p for role, p in provider.prompts if role == "engine"][-1])
        self.assertEqual(repair["integration_dependency_sources"], {"ui.js": SOURCES["ui.js"]})
        self.assertEqual(repair["repair_issues"], [issue])
        self.assertEqual(set(repair["source_fingerprints"]), set(FILES))

    def test_contract_alignment_expands_owners_and_consumers(self):
        provider = EditingProvider(issue=fixture_issue(scope="contract", contract_ids=["score"]))
        Pipeline(job(), provider).run()
        for role in ("engine", "renderer", "ui"):
            self.assertEqual(provider.calls.count(role), 2)
        self.assertEqual(provider.calls.count("audio"), 1)

    def test_review_cannot_invent_contract_or_regression_identifiers(self):
        for change in (
            {"contract_ids": ["invented"]},
            {"regression_scenario_id": "not-a-real-test"},
            {"scope": "local", "affected_files": ["engine.js", "ui.js"]},
        ):
            issue = fixture_issue()
            issue.update(change)
            with self.subTest(change=change), self.assertRaises(ProviderError):
                validate_review(
                    {"approved": False, "summary": "bad test review", "issues": [issue]}, PLAN
                )
        with self.assertRaisesRegex(ProviderError, "actionable"):
            validate_review(
                {"approved": False, "summary": "No concrete reason", "issues": []}, PLAN
            )

    def test_stable_task_and_spec_precede_changing_sources(self):
        provider = EditingProvider(issue=fixture_issue("renderer.js"))
        Pipeline(job(), provider).run()
        prompts = [prompt for role, prompt in provider.prompts if role == "renderer"]
        prefix = prompts[0].partition(PROMPT_BOUNDARY)[0]
        self.assertEqual(prefix, prompts[1].partition(PROMPT_BOUNDARY)[0])
        first = prompts[0].partition(PROMPT_BOUNDARY)[2].splitlines()
        second = prompts[1].partition(PROMPT_BOUNDARY)[2].splitlines()
        self.assertEqual(first[:2], second[:2])
        self.assertNotEqual(first[-1], second[-1])
        self.assertEqual(list(json.loads(first[1])), ["frozen_spec"])

    def test_current_job_freezes_prompt_bytes_when_disk_reader_changes(self):
        pipeline = Pipeline(job(), FixtureProvider())
        prefix = pipeline._prefix("engine")
        with patch.object(Pipeline, "_read_prefix", return_value="New contract bytes"):
            self.assertEqual(pipeline._prefix("engine"), prefix)
            self.assertNotEqual(Pipeline(job(), FixtureProvider())._prefix("engine"), prefix)


class EvidenceHistoryTests(unittest.TestCase):
    def test_known_rejected_usage_exceeding_budget_is_saved_before_failure(self):
        known = usage_record(
            {"input_tokens": 2_000_000, "output_tokens": 500, "cached_input_tokens": 20}
        )

        class RejectedAnswer(FixtureProvider):
            def generate(self, *args, **kwargs):
                raise ProviderError("Controlled invalid answer with known usage", usage=known)

        saved = {}
        pipeline = Pipeline(
            job(), RejectedAnswer(), persist=lambda cp, usage: saved.update(copy.deepcopy(cp))
        )
        with self.assertRaises(BudgetExceeded):
            pipeline.run()
        self.assertEqual(saved["budget"]["usage"], known)
        self.assertEqual(saved["budget"]["reserved"], {})
        self.assertEqual(saved["trace"]["calls"][0]["status"], "failed")
        self.assertEqual(saved["trace"]["calls"][0]["usage"], known)

    def test_schema_or_implementation_upgrade_cannot_resume_old_evidence(self):
        pipeline = Pipeline(job(), FixtureProvider())
        pipeline.plan({})
        checkpoint = copy.deepcopy(pipeline.cp)
        with patch(
            "prompt2play.legacy.worker.pipeline.implementation_fingerprint", return_value="0" * 64
        ):
            with self.assertRaisesRegex(ValueError, "execution contract"):
                Pipeline(job(), FixtureProvider(), checkpoint=checkpoint)
        from prompt2play.legacy.worker.core import PLAN_SCHEMA

        changed = copy.deepcopy(PLAN_SCHEMA)
        changed["properties"]["title"]["maxLength"] = 150
        with patch("prompt2play.legacy.worker.pipeline.PLAN_SCHEMA", changed):
            with self.assertRaisesRegex(ValueError, "execution contract"):
                Pipeline(job(), FixtureProvider(), checkpoint=checkpoint)
        self.assertEqual(checkpoint["budget"]["usage"]["calls"], 1)

    def test_source_change_invalidates_same_cycle_validation_and_review(self):
        first = Pipeline(job(), FixtureProvider())
        first.run()
        checkpoint = copy.deepcopy(first.cp)
        checkpoint["files"]["engine.js"] += "\n// Changed after the recorded validation."
        provider = FixtureProvider()
        second = Pipeline(job(), provider, checkpoint=checkpoint)
        result = second.run()
        self.assertEqual(provider.calls, ["review"])
        self.assertTrue(
            report_matches(result["validation"], result["files"], result["html"], result["spec"])
        )
        iterations = result["validation"]["provenance"]["iterations"]
        self.assertEqual(len(iterations), 2)
        self.assertNotEqual(
            iterations[0]["artifact"]["html_sha256"], iterations[1]["artifact"]["html_sha256"]
        )

    def test_after_review_mutation_of_any_artifact_input_blocks_result(self):
        for target in ("file", "html", "spec"):
            pipeline = Pipeline(job(), FixtureProvider())
            pipeline.run()
            if target == "file":
                pipeline.cp["files"]["engine.js"] += "\n// unsafe late change"
            elif target == "html":
                pipeline.html += "\n<!-- unsafe late change -->"
            else:
                pipeline.cp["plan"]["title"] = "Changed without checking"
            with (
                self.subTest(target=target),
                self.assertRaisesRegex(ProviderError, "changed after validation"),
            ):
                pipeline.result({})

    def test_repairs_preserve_actual_calls_sources_failed_evidence_and_frozen_spec(self):
        pipeline = Pipeline(job(), FixtureProvider(invalid_engine_once=True))
        result = pipeline.run()
        provenance = result["validation"]["provenance"]
        self.assertEqual(len(provenance["calls"]), 8)
        self.assertEqual(
            sum(c["usage"]["total_tokens"] for c in provenance["calls"]),
            result["usage"]["total_tokens"],
        )
        self.assertEqual(
            sum(c["usage"]["cached_input_tokens"] for c in provenance["calls"]),
            result["usage"]["cached_input_tokens"],
        )
        self.assertEqual([x["status"] for x in provenance["iterations"]], ["failed", "partial"])
        self.assertEqual(len(pipeline.cp["trace"]["sources"]), 5)
        first = next(x for x in pipeline.cp["trace"]["sources"] if x["file"] == "engine.js")
        self.assertEqual(first["source"], "class GameEngine {")
        self.assertNotIn("provenance", result["spec"])
        self.assertNotIn("calls", result["spec"]["generation"])
        self.assertEqual(
            result["validation"]["artifact"],
            artifact_manifest(result["files"], result["html"], result["spec"]),
        )
        review = result["validation"]["review"]
        self.assertEqual(review["artifact_sha256"], result["validation"]["artifact"]["html_sha256"])
        self.assertEqual(len(review["prompt_sha256"]), 64)
        for call in provenance["calls"]:
            self.assertEqual(call["status"], "completed")
            self.assertGreater(call["prompt_bytes"], 0)
            self.assertEqual(len(call["stable_prefix_sha256"]), 64)
            if call["role"] in ("engine", "renderer", "audio", "ui") and call["cycle"] == 0:
                # Parallel completion order cannot falsely claim a later file was
                # present in another author's already-frozen input context.
                self.assertEqual(call["source_sha256"], {})
        repair = next(
            call for call in provenance["calls"] if call["role"] == "engine" and call["cycle"] == 1
        )
        self.assertEqual(
            repair["source_sha256"],
            {"engine.js": hashlib.sha256("class GameEngine {".encode()).hexdigest()},
        )


if __name__ == "__main__":
    unittest.main()
