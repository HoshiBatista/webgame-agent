import copy
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from prompt2play.legacy.validator.docker import checked_report, run_validation, RUNTIME_CHECKS
from prompt2play.legacy.validator.evidence import artifact_manifest, check_record


class ValidatorRegressionTests(unittest.TestCase):
    def test_empty_and_incomplete_container_success_is_rejected(self):
        for report in (
            {"checks": [], "errors": [], "warnings": []},
            {
                "checks": [{"name": "anything", "status": "passed", "message": "ok"}],
                "errors": [],
                "warnings": [],
            },
            {"checks": [], "errors": "bad", "warnings": []},
        ):
            with self.assertRaises(ValueError):
                checked_report(report)
        manifest = artifact_manifest({}, "<html>fixture</html>", {})
        full = {
            "schema_version": 2,
            "artifact": manifest,
            "checks": [
                check_record(
                    f"{name}:{width}", "passed", "fixture evidence", manifest, check_kind="browser"
                )
                for name in RUNTIME_CHECKS
                for width in (1280, 390)
            ],
            "errors": [],
            "warnings": [],
        }
        self.assertEqual(checked_report(copy.deepcopy(full)), full)
        self.assertEqual(
            checked_report(
                {
                    "schema_version": 2,
                    "artifact": manifest,
                    "checks": [
                        check_record(
                            "runtime_harness", "failed", "Crash", manifest, check_kind="browser"
                        )
                    ],
                    "errors": [],
                    "warnings": [],
                }
            )["errors"],
            ["Crash"],
        )

    def fake_docker(self, directory, body):
        binary = Path(directory) / "docker-double"
        cleanup = Path(directory) / "cleanup.txt"
        binary.write_text(
            "#!"
            + sys.executable
            + "\n"
            + f"""import sys, pathlib, time
if sys.argv[1] == 'image': sys.exit(0)
if sys.argv[1] == 'rm':
    pathlib.Path({str(cleanup)!r}).write_text(' '.join(sys.argv[1:]))
    sys.exit(0)
assert '--network' in sys.argv and sys.argv[sys.argv.index('--network')+1]=='none'
assert '--read-only' in sys.argv and '--pull=never' in sys.argv
assert '--privileged' not in sys.argv
"""
            + body
        )
        binary.chmod(0o755)
        return binary, cleanup

    def test_container_output_is_bounded_and_cleaned_even_after_client_exit(self):
        bodies = [
            "sys.stdout.write('x'*2000000)\nsys.stdout.flush()\ntime.sleep(10)\n",
            "sys.stderr.write('x'*300000)\nsys.stderr.flush()\ntime.sleep(10)\n",
            "sys.exit(2)\n",
        ]
        for body in bodies:
            with tempfile.TemporaryDirectory() as directory:
                binary, cleanup = self.fake_docker(directory, body)
                with patch(
                    "prompt2play.legacy.validator.docker.shutil.which", return_value=str(binary)
                ):
                    report = run_validation(
                        "<html>test only</html>", [], threading.Event(), timeout=2
                    )
                self.assertTrue(report["errors"])
                self.assertTrue(cleanup.read_text().startswith("rm --force forge-validator-"))

    @unittest.skipUnless(shutil.which("node"), "Node unavailable for trusted probe tests")
    def test_audio_probe_requires_started_running_sources(self):
        # This is the handwritten trusted probe against doubles, never game code.
        probe = (Path(__file__).resolve().parents[2] / "validator" / "audio_probe.mjs").as_uri()
        script = f"""import {{installAudioProbe}} from {json.dumps(probe)};
import assert from 'node:assert/strict';
class Context {{constructor(){{this.state='suspended';this.currentTime=0;}}createOscillator(){{return {{start(){{}}}};}}createBufferSource(){{return {{start(){{}}}};}}}}
globalThis.window={{AudioContext:Context,webkitAudioContext:Context}};
installAudioProbe(); const c=new Context(); const node=c.createOscillator();
const read=()=>window.__FORGE_AUDIO_PROBE__.snapshot();
assert.equal(read().created,1); assert.equal(read().runningStarts,0);
node.start(); assert.equal(read().started,1); assert.equal(read().runningStarts,0);
c.state='running'; assert.equal(read().runningStarts,1);
c.createBufferSource().start(100); assert.equal(read().runningStarts,1);
c.currentTime=101; assert.equal(read().runningStarts,2);
assert.throws(()=>{{window.__FORGE_AUDIO_PROBE__={{snapshot:()=>({{runningStarts:999}})}}}});
console.log('Trusted audio probe regression passed');"""
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
