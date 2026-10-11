import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from prompt2play.legacy.worker.providers import (
    OpenAIProvider,
    CodexProvider,
    parse_json,
    response_text,
)
from prompt2play.legacy.worker.core import (
    COMPONENT_SCHEMA,
    ProviderError,
    Cancelled,
    usage_record,
    PROMPT_BOUNDARY,
)


class ProviderTests(unittest.TestCase):
    def test_responses_missing_usage_retains_pipeline_reservation(self):
        from prompt2play.legacy.worker.pipeline import Pipeline
        from .fixtures import PLAN
        from .test_pipeline import job

        attempts = []

        def handler(req):
            attempts.append(1)
            payload = {
                "type": "response.completed",
                "response": {
                    "output": [{"content": [{"type": "output_text", "text": json.dumps(PLAN)}]}],
                    "usage": None,
                },
            }
            return httpx.Response(200, text="data: " + json.dumps(payload) + "\n\n")

        real = httpx.AsyncClient
        pipeline = Pipeline(job(), OpenAIProvider(model="test", api_key="fake"))
        with patch(
            "prompt2play.legacy.worker.providers.httpx.AsyncClient",
            side_effect=lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
        ):
            with self.assertRaisesRegex(ProviderError, "valid usage"):
                pipeline.run()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(pipeline.budget.usage["total_tokens"], 0)
        self.assertGreater(pipeline.budget.uncertain, 0)
        self.assertEqual(pipeline.budget.reserved, {})
        self.assertEqual(
            usage_record({"input_tokens": 12, "output_tokens": 3, "input_tokens_details": None})[
                "total_tokens"
            ],
            15,
        )

    def test_strict_parser_and_refusal(self):
        with self.assertRaises(ProviderError):
            parse_json('{"source":"x","summary":"y","extra":true}', COMPONENT_SCHEMA)
        with self.assertRaises(ProviderError):
            response_text({"output": [{"content": [{"type": "refusal"}]}]})

    def test_responses_stream_usage_and_schema(self):
        captured = []

        def handler(req):
            captured.append(json.loads(req.content))
            payload = {
                "type": "response.completed",
                "response": {
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps({"source": "x", "summary": "ok"}),
                                }
                            ]
                        }
                    ],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "input_tokens_details": {"cached_tokens": 70},
                    },
                },
            }
            return httpx.Response(200, text="data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n")

        real = httpx.AsyncClient
        with patch(
            "prompt2play.legacy.worker.providers.httpx.AsyncClient",
            side_effect=lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
        ):
            result = OpenAIProvider(model="test", api_key="fake-key").generate(
                "stable instructions" + PROMPT_BOUNDARY + '{"task":"dynamic"}',
                COMPONENT_SCHEMA,
                "engine",
                threading.Event(),
                max_output=16000,
            )
        self.assertEqual(result.usage["cached_input_tokens"], 70)
        self.assertEqual(result.usage["total_tokens"], 150)
        self.assertTrue(captured[0]["text"]["format"]["strict"])
        self.assertEqual(captured[0]["prompt_cache_key"], "game-forge-v3-engine")
        self.assertEqual(captured[0]["instructions"], "stable instructions")
        self.assertEqual(captured[0]["input"], '{"task":"dynamic"}')
        self.assertEqual(captured[0]["max_output_tokens"], 16000)

    def test_codex_safe_args_stdin_schema_and_filtered_env(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "fake-codex"
            binary.write_text(
                "#!"
                + sys.executable
                + "\n"
                + """import sys,json,os
assert '--sandbox' in sys.argv and sys.argv[sys.argv.index('--sandbox')+1]=='read-only'
assert '--dangerously-bypass-approvals-and-sandbox' not in sys.argv
settings=[sys.argv[i+1] for i,arg in enumerate(sys.argv[:-1]) if arg=='-c']
assert 'features.shell_tool=false' in settings and 'web_search="disabled"' in settings
assert 'FORGE_RUNNER_TOKEN' not in os.environ and 'OPENAI_API_KEY' not in os.environ and 'DJANGO_SECRET_KEY' not in os.environ
assert sys.stdin.read()=='test prompt stdin'
path=sys.argv[sys.argv.index('--output-last-message')+1]
with open(path,'w') as f:json.dump({'source':'class Example {}','summary':'ok'},f)
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':20,'cached_input_tokens':5,'output_tokens':10}}))
"""
            )
            binary.chmod(0o755)
            with patch.dict(
                os.environ,
                {
                    "FORGE_RUNNER_TOKEN": "secret",
                    "OPENAI_API_KEY": "secret",
                    "DJANGO_SECRET_KEY": "secret",
                },
            ):
                result = CodexProvider(executable=str(binary), timeout=5).generate(
                    "test prompt stdin",
                    COMPONENT_SCHEMA,
                    "engine",
                    threading.Event(),
                    model="untrusted; shell text",
                )
            self.assertEqual(result.usage["total_tokens"], 30)

    def test_codex_cancel_terminates_running_process(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "fake-codex"
            binary.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(30)\n")
            binary.chmod(0o755)
            cancel = threading.Event()
            timer = threading.Timer(0.2, cancel.set)
            timer.start()
            start = time.monotonic()
            try:
                with self.assertRaises(Cancelled):
                    CodexProvider(executable=str(binary), timeout=5).generate(
                        "x", COMPONENT_SCHEMA, "engine", cancel
                    )
            finally:
                timer.cancel()
            self.assertLess(time.monotonic() - start, 5)

    def test_codex_terminal_failure_preserves_reported_usage(self):
        for scenario in ("failed", "missing", "oversized"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                binary = Path(directory) / "fake-codex"
                binary.write_text(
                    "#!"
                    + sys.executable
                    + "\n"
                    + f"""import sys,json
sys.stdin.read()
print(json.dumps({{'type':'turn.completed','usage':{{'input_tokens':20,'cached_input_tokens':5,'output_tokens':10}}}}))
scenario={scenario!r}
if scenario=='oversized':
    with open(sys.argv[sys.argv.index('--output-last-message')+1],'w') as f:f.write('x'*2000001)
if scenario=='failed':sys.exit(1)
"""
                )
                binary.chmod(0o755)
                with self.assertRaises(ProviderError) as error:
                    CodexProvider(executable=str(binary), timeout=5).generate(
                        "x", COMPONENT_SCHEMA, "engine", threading.Event()
                    )
                self.assertEqual(error.exception.usage["total_tokens"], 30)

    def test_openai_explicit_retry_is_bounded(self):
        attempts = []

        def handler(req):
            attempts.append(1)
            return httpx.Response(429, json={"error": "rate limited"})

        real = httpx.AsyncClient

        class ImmediateCancelEvent:
            def is_set(self):
                return False

            def wait(self, _):
                return False

        with patch(
            "prompt2play.legacy.worker.providers.httpx.AsyncClient",
            side_effect=lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
        ):
            with self.assertRaises(ProviderError):
                OpenAIProvider(model="test", api_key="fake").generate(
                    "x", COMPONENT_SCHEMA, "engine", ImmediateCancelEvent()
                )
        self.assertEqual(len(attempts), 3)


if __name__ == "__main__":
    unittest.main()
