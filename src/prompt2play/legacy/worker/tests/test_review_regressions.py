"""Regression tests from code review. No real model or generated JS execution."""

import asyncio
import copy
import io
import json
import os
import threading
import time
import unittest
from unittest.mock import Mock, MagicMock, patch

import httpx

from prompt2play.legacy.worker.__main__ import main
from prompt2play.legacy.worker.core import COMPONENT_SCHEMA, ProviderError, Cancelled, empty_usage
from prompt2play.legacy.worker.pipeline import Pipeline
from prompt2play.legacy.worker.providers import OpenAIProvider
from .fixtures import FixtureProvider, PLAN, SOURCES
from .test_pipeline import job


class ProtocolRegressionTests(unittest.TestCase):
    def provider_with(self, handler, **options):
        real = httpx.AsyncClient
        return patch(
            "prompt2play.legacy.worker.providers.httpx.AsyncClient",
            side_effect=lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
        )

    def terminal(self, text, kind="response.completed"):
        return {
            "type": kind,
            "response": {
                "output": [{"content": [{"type": "output_text", "text": text}]}],
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 40,
                    "input_tokens_details": {"cached_tokens": 30},
                },
            },
        }

    def test_invalid_and_incomplete_answers_keep_known_usage(self):
        for event in (self.terminal("not JSON"), self.terminal("", "response.incomplete")):

            def handler(request):
                return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n")

            saved = {}
            pipeline = Pipeline(
                job(),
                OpenAIProvider(model="test", api_key="test"),
                persist=lambda cp, usage: saved.update(copy.deepcopy(cp)),
            )
            with self.provider_with(handler), self.assertRaises(ProviderError):
                pipeline.run()
            self.assertEqual(pipeline.budget.usage["total_tokens"], 160)
            self.assertEqual(pipeline.budget.usage["cached_input_tokens"], 30)
            self.assertEqual(pipeline.budget.uncertain, 0)
            self.assertEqual(saved["budget"]["usage"]["calls"], 1)
            self.assertEqual(saved["budget"]["reserved"], {})

    def test_http_rejection_is_not_reported_as_unknown_spend(self):
        pipeline = Pipeline(job(), OpenAIProvider(model="test", api_key="test"))
        with self.provider_with(lambda req: httpx.Response(401)), self.assertRaises(ProviderError):
            pipeline.run()
        self.assertEqual(pipeline.budget.usage, empty_usage())
        self.assertEqual(pipeline.budget.uncertain, 0)

    def test_ambiguous_server_failure_is_not_replayed_or_refunded(self):
        attempts = []

        def handler(req):
            attempts.append(1)
            return httpx.Response(503)

        pipeline = Pipeline(job(), OpenAIProvider(model="test", api_key="test"))
        with self.provider_with(handler), self.assertRaises(ProviderError):
            pipeline.run()
        self.assertEqual(len(attempts), 1)
        self.assertGreater(pipeline.budget.uncertain, 0)

    def test_completed_event_returns_without_waiting_for_eof(self):
        event = self.terminal(json.dumps({"source": "x", "summary": "ok"}))

        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                yield ("data: " + json.dumps(event) + "\n\n").encode()
                raise AssertionError("Provider read past terminal completion")

            async def aclose(self):
                self.closed = True

        stream = Stream()
        with self.provider_with(lambda req: httpx.Response(200, stream=stream)):
            reply = OpenAIProvider(model="test", api_key="test").generate(
                "x", COMPONENT_SCHEMA, "engine", threading.Event()
            )
        self.assertEqual(reply.data["source"], "x")
        self.assertTrue(stream.closed)

    def test_stalled_stream_is_cancelled_and_wall_bounded(self):
        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                await asyncio.sleep(20)
                yield b""

            async def aclose(self):
                self.closed = True

        for cancellation in (True, False):
            stream = Stream()
            cancel = threading.Event()
            timer = threading.Timer(0.1, cancel.set) if cancellation else None
            if timer:
                timer.start()
            started = time.monotonic()
            try:
                with self.provider_with(lambda req: httpx.Response(200, stream=stream)):
                    with self.assertRaises(Cancelled if cancellation else ProviderError):
                        OpenAIProvider(
                            model="test", api_key="test", timeout=0.2 if not cancellation else 10
                        ).generate("x", COMPONENT_SCHEMA, "engine", cancel)
            finally:
                if timer:
                    timer.cancel()
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(stream.closed)

    def test_multiline_sse_and_bound(self):
        event = self.terminal(json.dumps({"source": "x", "summary": "ok"}))
        text = (
            "\n".join("data: " + line for line in json.dumps(event, indent=2).splitlines()) + "\n\n"
        )
        with self.provider_with(lambda req: httpx.Response(200, text=text)):
            reply = OpenAIProvider(model="test", api_key="test").generate(
                "x", COMPONENT_SCHEMA, "engine", threading.Event()
            )
        self.assertEqual(reply.data["summary"], "ok")
        with self.provider_with(
            lambda req: httpx.Response(200, content=b"x" * (4 * 1024 * 1024 + 1))
        ):
            with self.assertRaisesRegex(ProviderError, "safety limit"):
                OpenAIProvider(model="test", api_key="test").generate(
                    "x", COMPONENT_SCHEMA, "engine", threading.Event()
                )


class RecoveryRegressionTests(unittest.TestCase):
    def test_saved_explicit_model_pins_handoff_and_limits_must_match(self):
        first = FixtureProvider()
        first.model = "model-a"
        pipeline = Pipeline(job(), first)
        pipeline.plan({})
        saved = copy.deepcopy(pipeline.cp)
        second = FixtureProvider()
        second.model = "model-b"
        received = []
        original = second.generate

        def generate(*args, **kwargs):
            received.append(kwargs["model"])
            return original(*args, **kwargs)

        second.generate = generate
        result = Pipeline(job(), second, checkpoint=saved).run()
        self.assertTrue(received)
        self.assertEqual(set(received), {"model-a"})
        self.assertEqual(result["spec"]["generation"]["model"], "model-a")
        with patch.dict(os.environ, {"FORGE_CODE_OUTPUT_TOKENS": "32000"}):
            with self.assertRaisesRegex(ValueError, "execution contract/output limits changed"):
                Pipeline(job(), second, checkpoint=saved)
        legacy = copy.deepcopy(saved)
        legacy.pop("execution")
        with self.assertRaisesRegex(ValueError, "Legacy checkpoint"):
            Pipeline(job(), second, checkpoint=legacy)
        self.assertEqual(saved["budget"]["usage"]["calls"], 1)

    def test_new_runtime_evidence_invalidates_cached_review(self):
        initial = Pipeline(job(), FixtureProvider())
        initial.run()
        next_provider = FixtureProvider()
        with patch(
            "prompt2play.legacy.worker.pipeline.validate",
            return_value=copy.deepcopy(initial.cp["validation"]),
        ):
            result = Pipeline(job(), next_provider, checkpoint=initial.cp, runtime=True).run()
        self.assertEqual(next_provider.calls, ["review"])
        self.assertEqual(result["usage"]["calls"], 7)

    def test_empty_or_schema_breaking_revision_never_publishes_noop(self):
        base = {"files": SOURCES, "spec": PLAN, "is_reference": False}
        task = job()
        task.update(kind="revise", base_version_id="base")
        provider = FixtureProvider(affected=[])
        with self.assertRaisesRegex(ProviderError, "at least one"):
            Pipeline(task, provider, base_version=base).run()
        self.assertEqual(provider.calls, ["plan"])
        provider = FixtureProvider(affected=["audio.js"])
        original = provider.generate

        def generate(*args, **kwargs):
            reply = original(*args, **kwargs)
            if args[2] == "plan":
                reply.data["state_schema"] = '{"player":{"renamed_x":"number"}}'
            return reply

        provider.generate = generate
        with self.assertRaisesRegex(ProviderError, "shared schemas"):
            Pipeline(task, provider, base_version=base).run()
        self.assertEqual(provider.calls, ["plan"])


class StartupRegressionTests(unittest.TestCase):
    def test_constructor_failure_does_not_erase_checkpoint_usage(self):
        coordinator = Mock()
        task = job()
        task.update(
            provider="openai",
            usage={
                "input_tokens": 200,
                "output_tokens": 100,
                "total_tokens": 300,
                "cached_input_tokens": 0,
                "calls": 1,
            },
        )
        coordinator.claim.return_value = {
            "job": task,
            "lease_token": "test",
            "checkpoint": {"legacy": True},
        }
        lease = MagicMock()
        lease.__enter__.return_value = lease
        with (
            patch.dict(
                os.environ,
                {"FORGE_RUNNER_TOKEN": "test", "OPENAI_API_KEY": "test", "OPENAI_MODEL": "test"},
            ),
            patch("prompt2play.legacy.worker.__main__.Coordinator", return_value=coordinator),
            patch("prompt2play.legacy.worker.__main__.Lease", return_value=lease),
            patch(
                "prompt2play.legacy.worker.__main__.Pipeline",
                side_effect=ValueError("Legacy checkpoint"),
            ),
            patch("prompt2play.legacy.worker.__main__.signal.signal"),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(main(["--provider", "openai", "--once"]), 1)
        self.assertEqual(lease.write.call_args.args, ("fail",))
        self.assertNotIn("usage", lease.write.call_args.kwargs)

    def test_unavailable_provider_never_claims(self):
        with (
            patch.dict(os.environ, {"FORGE_RUNNER_TOKEN": "test"}),
            patch("prompt2play.legacy.worker.providers.shutil.which", return_value=None),
            patch("prompt2play.legacy.worker.__main__.Coordinator") as coordinator,
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit) as error:
                main(["--provider", "codex", "--once"])
            self.assertEqual(error.exception.code, 2)
            coordinator.assert_not_called()
        with (
            patch.dict(os.environ, {"FORGE_RUNNER_TOKEN": "test", "OPENAI_API_KEY": ""}),
            patch("prompt2play.legacy.worker.__main__.Coordinator") as coordinator,
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit):
                main(["--provider", "openai", "--once"])
            coordinator.assert_not_called()

    def test_cli_preserves_server_name_and_advertises_model_requirement(self):
        coordinator = Mock()
        coordinator.claim.return_value = {"job": None}
        with (
            patch.dict(
                os.environ,
                {"FORGE_RUNNER_TOKEN": "test", "OPENAI_API_KEY": "test", "OPENAI_MODEL": ""},
            ),
            patch("prompt2play.legacy.worker.__main__.Coordinator", return_value=coordinator),
            patch("prompt2play.legacy.worker.__main__.signal.signal"),
        ):
            self.assertEqual(main(["--provider", "openai", "--once"]), 0)
        capabilities, name = coordinator.claim.call_args.args
        self.assertEqual(name, "")
        self.assertEqual(capabilities["requires_job_model"], ["openai"])
