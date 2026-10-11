"""Provider lifecycle regressions using authored subprocesses/HTTP doubles only."""

from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx

from prompt2play.legacy.worker.__main__ import main
from prompt2play.legacy.worker.core import COMPONENT_SCHEMA, Cancelled, ProviderError
from prompt2play.legacy.worker.pipeline import Pipeline
from prompt2play.legacy.worker.providers import CodexProvider, OpenAIProvider
from .test_pipeline import job


RAW_USAGE = {
    "input_tokens": 120,
    "output_tokens": 40,
    "input_tokens_details": {"cached_tokens": 30},
}
EXPECTED_USAGE = {
    "input_tokens": 120,
    "output_tokens": 40,
    "cached_input_tokens": 30,
    "total_tokens": 160,
    "calls": 1,
}


class CodexInterruptionReviewTests(unittest.TestCase):
    def test_terminal_usage_survives_timeout_during_process_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="forge-test-cli-") as directory:
            binary = Path(directory) / "fake-codex"
            binary.write_text(
                "#!"
                + sys.executable
                + "\n"
                + f"""import json,sys,time
sys.stdin.read()
print(json.dumps({{'type':'turn.completed','usage':{RAW_USAGE!r}}}), flush=True)
time.sleep(30)
""",
                encoding="utf-8",
            )
            binary.chmod(0o755)
            pipeline = Pipeline(job(), CodexProvider(executable=str(binary), timeout=0.4))
            with self.assertRaisesRegex(ProviderError, "wall timeout"):
                pipeline.run()
            self.assertEqual(pipeline.budget.usage, EXPECTED_USAGE)
            self.assertEqual(pipeline.budget.uncertain, 0)
            self.assertEqual(pipeline.cp["trace"]["calls"][-1]["usage"], EXPECTED_USAGE)
            self.assertNotIn("plan", pipeline.cp)

    def test_terminal_usage_survives_cancel_without_accepting_output(self):
        with tempfile.TemporaryDirectory(prefix="forge-test-cli-") as directory:
            binary = Path(directory) / "fake-codex"
            binary.write_text(
                "#!"
                + sys.executable
                + "\n"
                + f"""import json,sys,time
sys.stdin.read()
print(json.dumps({{'type':'turn.completed','usage':{RAW_USAGE!r}}}), flush=True)
time.sleep(30)
""",
                encoding="utf-8",
            )
            binary.chmod(0o755)
            cancel = threading.Event()
            timer = threading.Timer(0.5, cancel.set)
            timer.start()
            try:
                with self.assertRaises(Cancelled) as failure:
                    CodexProvider(executable=str(binary), timeout=5).generate(
                        "test input", COMPONENT_SCHEMA, "engine", cancel
                    )
            finally:
                timer.cancel()
            self.assertEqual(getattr(failure.exception, "usage", None), EXPECTED_USAGE)

    def test_process_that_never_started_does_not_consume_an_unknown_reservation(self):
        pipeline = Pipeline(job(), CodexProvider(executable="authored-cli-fixture"))
        with (
            patch(
                "prompt2play.legacy.worker.providers.shutil.which", return_value="/authored-fixture"
            ),
            patch(
                "prompt2play.legacy.worker.providers.subprocess.Popen",
                side_effect=OSError("fixture exec failed"),
            ),
        ):
            with self.assertRaises(ProviderError):
                pipeline.run()
        self.assertEqual(pipeline.budget.usage["total_tokens"], 0)
        self.assertEqual(pipeline.budget.uncertain, 0)
        self.assertEqual(pipeline.budget.reserved, {})

    def test_unreadable_structured_result_keeps_reported_terminal_usage(self):
        with tempfile.TemporaryDirectory(prefix="forge-test-cli-") as directory:
            binary = Path(directory) / "fake-codex"
            binary.write_text(
                "#!"
                + sys.executable
                + "\n"
                + f"""import json,sys
sys.stdin.read()
with open(sys.argv[sys.argv.index('--output-last-message')+1],'wb') as f: f.write(b'\\xff')
print(json.dumps({{'type':'turn.completed','usage':{RAW_USAGE!r}}}), flush=True)
""",
                encoding="utf-8",
            )
            binary.chmod(0o755)
            with self.assertRaises(ProviderError) as failure:
                CodexProvider(executable=str(binary), timeout=5).generate(
                    "test input", COMPONENT_SCHEMA, "engine", threading.Event()
                )
            self.assertEqual(failure.exception.usage, EXPECTED_USAGE)


class OpenAIInterruptionReviewTests(unittest.TestCase):
    def test_transport_close_exception_keeps_reported_terminal_usage(self):
        event = {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {"source": "authored fixture", "summary": "test only"}
                                ),
                            }
                        ]
                    }
                ],
                "usage": RAW_USAGE,
            },
        }

        class FailedCloseStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield ("data: " + json.dumps(event) + "\n\n").encode()

            async def aclose(self):
                raise RuntimeError("authored transport close failed")

        real_client = httpx.AsyncClient
        with patch(
            "prompt2play.legacy.worker.providers.httpx.AsyncClient",
            side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, stream=FailedCloseStream())
                ),
                **kw,
            ),
        ):
            with self.assertRaisesRegex(ProviderError, "finalization") as failure:
                OpenAIProvider(model="fixture", api_key="fixture", timeout=2).generate(
                    "test input", COMPONENT_SCHEMA, "engine", threading.Event()
                )
        self.assertEqual(failure.exception.usage, EXPECTED_USAGE)

    def test_completed_stream_does_not_win_an_already_signalled_cancellation(self):
        cancel = threading.Event()
        event = {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {"source": "authored fixture", "summary": "test only"}
                                ),
                            }
                        ]
                    }
                ],
                "usage": RAW_USAGE,
            },
        }

        class CancellingCloseStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                await asyncio.sleep(0)  # The cancellation watcher is already waiting.
                yield ("data: " + json.dumps(event) + "\n\n").encode()

            async def aclose(self):
                cancel.set()

        real_client = httpx.AsyncClient
        with patch(
            "prompt2play.legacy.worker.providers.httpx.AsyncClient",
            side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, stream=CancellingCloseStream())
                ),
                **kw,
            ),
        ):
            with self.assertRaises(Cancelled) as failure:
                OpenAIProvider(model="fixture", api_key="fixture", timeout=2).generate(
                    "test input", COMPONENT_SCHEMA, "engine", cancel
                )
        self.assertEqual(getattr(failure.exception, "usage", None), EXPECTED_USAGE)

    def test_terminal_usage_survives_cancel_or_timeout_while_stream_closes(self):
        event = {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {"source": "authored fixture", "summary": "test only"}
                                ),
                            }
                        ]
                    }
                ],
                "usage": RAW_USAGE,
            },
        }
        real_client = httpx.AsyncClient
        for cancel_on_close in (False, True):
            with self.subTest(cancel=cancel_on_close):
                cancel = threading.Event()

                class SlowCloseStream(httpx.AsyncByteStream):
                    close_started = False

                    async def __aiter__(self):
                        yield ("data: " + json.dumps(event) + "\n\n").encode()

                    async def aclose(self):
                        self.close_started = True
                        if cancel_on_close:
                            cancel.set()
                        await asyncio.sleep(30)

                stream = SlowCloseStream()
                with patch(
                    "prompt2play.legacy.worker.providers.httpx.AsyncClient",
                    side_effect=lambda **kw: real_client(
                        transport=httpx.MockTransport(
                            lambda request: httpx.Response(200, stream=stream)
                        ),
                        **kw,
                    ),
                ):
                    with self.assertRaises(
                        Cancelled if cancel_on_close else ProviderError
                    ) as failure:
                        OpenAIProvider(model="fixture", api_key="fixture", timeout=0.2).generate(
                            "test input", COMPONENT_SCHEMA, "engine", cancel
                        )
                self.assertTrue(stream.close_started)
                self.assertEqual(getattr(failure.exception, "usage", None), EXPECTED_USAGE)


class WorkerNumericArgumentsReviewTests(unittest.TestCase):
    def test_nonfinite_intervals_are_rejected_before_credentials_or_claim(self):
        for argument in ("--timeout", "--poll"):
            for value in ("nan", "inf", "-inf"):
                with (
                    self.subTest(argument=argument, value=value),
                    patch.dict(os.environ, {}, clear=True),
                    patch(
                        "prompt2play.legacy.worker.__main__.getpass.getpass", return_value="fixture"
                    ) as prompt,
                    patch("prompt2play.legacy.worker.providers.CodexProvider.preflight"),
                    patch("prompt2play.legacy.worker.__main__.Coordinator") as coordinator,
                    patch("prompt2play.legacy.worker.__main__.signal.signal"),
                    patch("sys.stderr", new_callable=io.StringIO),
                ):
                    coordinator.return_value.claim.return_value = {"job": None}
                    with self.assertRaises(SystemExit) as error:
                        main([argument + "=" + value, "--once"])
                    self.assertEqual(error.exception.code, 2)
                    prompt.assert_not_called()
                    coordinator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
