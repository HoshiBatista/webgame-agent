import copy
import os
import threading
import unittest
from unittest.mock import patch
from prompt2play.legacy.worker.pipeline import Pipeline
from prompt2play.legacy.worker.core import Budget, BudgetExceeded, Cancelled, ProviderError
from prompt2play.legacy.validator.checks import assemble
from .fixtures import FixtureProvider, SOURCES, PLAN


def job(**kwargs):
    return dict(
        id="test-job",
        kind="generate",
        prompt="A new test game",
        provider="codex",
        model="",
        base_version_id=None,
        max_repairs=2,
        budget_tokens=2_000_000,
        **kwargs,
    )


class PipelineTests(unittest.TestCase):
    def test_ui_output_capacity_has_a_larger_default_and_honors_explicit_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            pipeline = Pipeline(job(), FixtureProvider())
            pipeline.plan({})
            pipeline.prepare({})
            self.assertEqual(pipeline.output_limits["engine"], 16000)
            self.assertEqual(pipeline.output_limits["ui"], 32000)
            self.assertEqual(
                pipeline.budget.reserved["0:ui"],
                len(pipeline.prompts["ui"].encode()) + 32000 + 1024,
            )
        with patch.dict(os.environ, {"FORGE_CODE_OUTPUT_TOKENS": "24000"}, clear=True):
            self.assertEqual(Pipeline(job(), FixtureProvider()).output_limits["ui"], 24000)
        with patch.dict(
            os.environ,
            {"FORGE_CODE_OUTPUT_TOKENS": "24000", "FORGE_UI_OUTPUT_TOKENS": "48000"},
            clear=True,
        ):
            limits = Pipeline(job(), FixtureProvider()).output_limits
            self.assertEqual(limits["engine"], 24000)
            self.assertEqual(limits["ui"], 48000)
        with patch.dict(os.environ, {"FORGE_UI_OUTPUT_TOKENS": "0"}, clear=True):
            with self.assertRaisesRegex(ValueError, "FORGE_UI_OUTPUT_TOKENS"):
                Pipeline(job(), FixtureProvider())

    def test_output_allowances_validate_and_drive_reservations(self):
        with patch.dict(
            os.environ,
            {
                "FORGE_CODE_OUTPUT_TOKENS": "64000",
                "FORGE_PLAN_OUTPUT_TOKENS": "1000",
                "FORGE_REVIEW_OUTPUT_TOKENS": "12000",
            },
        ):
            p = Pipeline(job(), FixtureProvider())
            p.plan({})
            p.prepare({})
            self.assertEqual(
                p.output_limits,
                {
                    "plan": 1000,
                    "review": 12000,
                    "engine": 64000,
                    "renderer": 64000,
                    "audio": 64000,
                    "ui": 64000,
                },
            )
            for role, prompt in p.prompts.items():
                self.assertEqual(
                    p.budget.reserved["0:" + role], len(prompt.encode("utf-8")) + 64000 + 1024
                )
        for value in ("999", "64001", "not-a-number"):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {"FORGE_CODE_OUTPUT_TOKENS": value}),
            ):
                with self.assertRaisesRegex(ValueError, "1000 through 64000"):
                    Pipeline(job(), FixtureProvider())

    def test_parallel_pipeline_honest_partial(self):
        model = FixtureProvider()
        result = Pipeline(job(), model).run()
        self.assertEqual(set(result["files"]), set(SOURCES))
        self.assertEqual(result["validation"]["status"], "partial")
        self.assertEqual(result["usage"]["calls"], 6)
        self.assertEqual(result["usage"]["cached_input_tokens"], 150)
        self.assertEqual(result["html"].count("<script>"), 1)
        self.assertIn(
            "isolated_browser_runtime",
            [c["name"] for c in result["validation"]["checks"] if c["status"] == "skipped"],
        )

    def test_static_failure_repairs_only_engine(self):
        model = FixtureProvider(invalid_engine_once=True)
        result = Pipeline(job(), model).run()
        self.assertEqual(model.calls.count("engine"), 2)
        for role in ("renderer", "audio", "ui"):
            self.assertEqual(model.calls.count(role), 1)
        self.assertEqual(result["validation"]["errors"], [])

    def test_revision_preserves_other_files_byte_for_byte(self):
        base = {
            "files": {
                **SOURCES,
                "engine.js": SOURCES["engine.js"] + "\n// preserve this exact byte sequence",
            },
            "spec": PLAN,
            "is_reference": False,
        }
        j = job()
        j.update(kind="revise", base_version_id="base-uuid")
        model = FixtureProvider(affected=["audio.js"])
        result = Pipeline(j, model, base_version=base).run()
        for name in ("engine.js", "renderer.js", "ui.js"):
            self.assertEqual(result["files"][name], base["files"][name])
        self.assertEqual(model.calls, ["plan", "audio", "review"])

    def test_checkpoint_skips_successful_authors(self):
        saved = {}

        def persist(cp, usage):
            saved.clear()
            saved.update(copy.deepcopy(cp))

        with self.assertRaises(ProviderError):
            Pipeline(job(), FixtureProvider(fail_once="renderer"), persist=persist).run()
        completed = set(saved["component_cycles"])
        second = FixtureProvider()
        result = Pipeline(job(), second, checkpoint=saved, persist=persist).run()
        self.assertNotIn("plan", second.calls)
        for role in completed:
            self.assertNotIn(role, second.calls)
        self.assertIn("renderer", second.calls)
        self.assertEqual(result["validation"]["status"], "partial")

    def test_cancel_before_any_provider_call(self):
        event = threading.Event()
        event.set()
        model = FixtureProvider()
        with self.assertRaises(Cancelled):
            Pipeline(job(), model, cancel=event).run()
        self.assertEqual(model.calls, [])

    def test_parallel_budget_is_reserved_before_fanout(self):
        j = job()
        model = FixtureProvider()
        probe = Pipeline(j, model)
        # Enough for the actual planning prompt, but not the parallel author set.
        j["budget_tokens"] = (
            Budget.estimate(probe._prompt("plan"), probe.output_limits["plan"]) + 100
        )
        with self.assertRaises(BudgetExceeded):
            Pipeline(j, model).run()
        self.assertEqual(model.calls, ["plan"])

    def test_legacy_reference_revision_rejected(self):
        j = job()
        j["kind"] = "revise"
        with self.assertRaisesRegex(ValueError, "read-only"):
            Pipeline(j, FixtureProvider(), base_version={"is_reference": True})

    def test_paths_and_script_escaping(self):
        bad = {**SOURCES, "../outside.js": "anything"}
        with self.assertRaises(ValueError):
            assemble(bad, "test")
        sources = {**SOURCES, "ui.js": SOURCES["ui.js"] + "\nconst a='</script><h1>bad</h1>';"}
        out = assemble(sources, "<img onerror=x>")
        self.assertEqual(out.count("</script>"), 1)
        self.assertIn("&lt;img", out)

    def test_unknown_reservations_survive_restart(self):
        b = Budget(10000, reserved={"dead-request": 3000})
        self.assertEqual(b.uncertain, 3000)
        with self.assertRaises(BudgetExceeded):
            b.reserve_many({"next": 8000})


if __name__ == "__main__":
    unittest.main()
