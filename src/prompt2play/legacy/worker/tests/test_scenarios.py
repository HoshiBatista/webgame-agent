"""Declarative QA and final-byte regressions. Never executes generated game JS."""

import copy
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from prompt2play.legacy.validator.checks import assemble, static_validate, validate
from prompt2play.legacy.validator.docker import RUNTIME_CHECKS, checked_report, run_validation
from prompt2play.legacy.validator.evidence import artifact_manifest, check_record, report_matches
from prompt2play.legacy.validator.scenarios import validate_scenarios

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "engine.js": "class GameEngine {}",
    "renderer.js": "class GameRenderer {}",
    "audio.js": "class GameAudio {}",
    "ui.js": "function mountGame(root) { /* __GAME_TEST__ data-testid */ return {dispose(){}}; }",
}


def scenario(*steps, ident="progress"):
    return {
        "id": ident,
        "purpose": "Check observable game behavior",
        "category": "progress",
        "seed": "review-seed",
        "affected_files": ["engine.js", "ui.js"],
        "limitations": ["Authored sequence, not a complete gameplay proof"],
        "steps": [json.dumps(step) for step in steps],
    }


def progress():
    return scenario(
        {"op": "capture", "key": "before"},
        {"op": "act", "action": {"type": "move"}},
        {
            "op": "assert",
            "left": {"path": "/tick"},
            "cmp": "gt",
            "right": {"saved": "before", "path": "/tick"},
        },
    )


class ScenarioSchemaTests(unittest.TestCase):
    def test_scenarios_decode_without_mutating_the_specification(self):
        original = [progress()]
        saved = copy.deepcopy(original)
        decoded = validate_scenarios(original)
        self.assertEqual(original, saved)
        self.assertIsInstance(original[0]["steps"][0], str)
        self.assertIsInstance(decoded[0]["steps"][0], dict)
        self.assertEqual(validate_scenarios(decoded), decoded)

    def test_rejects_code_unsafe_paths_unknown_ops_and_unobserved_scenarios(self):
        bad_steps = [
            {"op": "eval", "source": "globalThis.pwned=true"},
            {"op": "act", "action": {"type": "move"}, "source": "anything"},
            {"op": "assert", "left": {"path": "/__proto__/value"}, "cmp": "exists"},
            {"op": "assert", "left": {"path": "/invalid~2escape"}, "cmp": "exists"},
            {
                "op": "assert",
                "left": {"saved": "missing", "path": "/tick"},
                "cmp": "eq",
                "right": {"value": 0},
            },
            {"op": "assert", "left": {"element": "#x", "property": "innerHTML"}, "cmp": "exists"},
            {"op": "act", "action": []},
            {"op": "advance", "frames": True},
            {"op": "advance", "frames": 3601},
            {"op": [], "action": {}},
            {"op": "assert", "left": {"saved": [], "path": "/tick"}, "cmp": "exists"},
            {"op": "assert", "left": {"element": "#x", "property": []}, "cmp": "exists"},
            {"op": "assert", "left": {"path": "/tick"}, "cmp": []},
            {"op": "assert", "left": {"value": float("nan")}, "cmp": "exists"},
        ]
        for step in bad_steps:
            with self.subTest(step=step), self.assertRaises(ValueError):
                validate_scenarios([scenario({"op": "act", "action": {"type": "move"}}, step)])
        for case in (
            scenario({"op": "act", "action": {"type": "move"}}),
            scenario({"op": "assert", "left": {"value": 1}, "cmp": "eq", "right": {"value": 1}}),
        ):
            with self.assertRaises(ValueError):
                validate_scenarios([case])

    def test_global_budgets_are_checked_across_all_scenarios(self):
        many = [
            scenario(
                *([{"op": "advance", "frames": 3600}] * 17),
                {"op": "assert", "left": {"path": "/tick"}, "cmp": "gte", "right": {"value": 0}},
                ident=f"run{i}",
            )
            for i in range(2)
        ]
        with self.assertRaisesRegex(ValueError, "frames"):
            validate_scenarios(many)
        many = [
            scenario(
                *([{"op": "act", "action": {"type": "move"}, "repeat": 120}] * 11),
                {"op": "assert", "left": {"path": "/tick"}, "cmp": "gte", "right": {"value": 0}},
            )
        ]
        with self.assertRaisesRegex(ValueError, "actions"):
            validate_scenarios(many)
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_scenarios([progress(), progress()])

    def test_accounting_sum_and_readonly_focus_are_representable(self):
        item = scenario(
            {"op": "focus", "selector": "#target"},
            {"op": "advance", "frames": 60},
            {
                "op": "assert",
                "left": {
                    "sum": [
                        {"path": "/kills"},
                        {"path": "/escaped"},
                        {"count": {"path": "/enemies"}},
                    ]
                },
                "cmp": "eq",
                "right": {"path": "/spawned"},
            },
            {
                "op": "assert",
                "left": {"element": "#target", "property": "focused"},
                "cmp": "eq",
                "right": {"value": True},
            },
        )
        self.assertEqual(len(validate_scenarios([item])[0]["steps"]), 4)


class ArtifactEvidenceTests(unittest.TestCase):
    def test_exact_import_keyword_does_not_reject_css_important_or_prose_imports(self):
        permitted = {
            **SOURCES,
            "audio.js": SOURCES["audio.js"]
            + "\n// This original audio implementation needs no imports.\n",
            "ui.js": SOURCES["ui.js"]
            + '\nconst UiFixtureStyle = ".game { color: red !important; }";',
        }
        self.assertFalse(
            static_validate(
                permitted, assemble(permitted, "Import keyword boundary"), threading.Event()
            )["errors"]
        )
        for source in (
            'import("./external.js");',
            'import x from "./external.js";',
            'import{thing}from"./external.js";',
        ):
            forbidden = {**SOURCES, "engine.js": SOURCES["engine.js"] + "\n" + source}
            report = static_validate(
                forbidden, assemble(forbidden, "Real import"), threading.Event()
            )
            self.assertTrue(
                any(
                    check["name"] == "offline:engine.js" and check["status"] == "failed"
                    for check in report["checks"]
                )
            )

    def test_backend_and_validator_manifest_canonicalization_agree(self):
        from prompt2play.adapters.django.forge import artifacts as backend

        spec = {"title": "Стражи", "nested": {"float": 1 / 60, "null": None, "a": ["ёж", True, 7]}}
        html = assemble(SOURCES, spec["title"])
        self.assertEqual(
            artifact_manifest(SOURCES, html, spec), backend.artifact_manifest(SOURCES, html, spec)
        )

    def test_validation_is_bound_to_sources_html_spec_and_individual_checks(self):
        spec = {"title": "Evidence fixture"}
        html = assemble(SOURCES, spec["title"])
        report = static_validate(SOURCES, html, threading.Event(), spec=spec)
        self.assertFalse(report["errors"])
        self.assertTrue(report_matches(report, SOURCES, html, spec))
        for files, content, plan in (
            ({**SOURCES, "engine.js": SOURCES["engine.js"] + "\n"}, html, spec),
            (SOURCES, html + " ", spec),
            (SOURCES, html, {**spec, "genre": "changed"}),
        ):
            self.assertFalse(report_matches(report, files, content, plan))
        stale = copy.deepcopy(report)
        stale["checks"][0]["artifact_sha256"] = "0" * 64
        self.assertFalse(report_matches(stale, SOURCES, html, spec))

    def test_unrelated_or_modified_assembled_script_is_rejected(self):
        spec = {"title": "Evidence fixture"}
        html = assemble(SOURCES, spec["title"]).replace(
            "class GameEngine {}", "class GameEngine {constructor(){}}"
        )
        report = static_validate(SOURCES, html, threading.Event(), spec=spec)
        failures = {check["name"] for check in report["checks"] if check["status"] == "failed"}
        self.assertIn("artifact_sources", failures)
        self.assertIn("artifact_assembly", failures)

    def test_static_mode_records_each_declared_scenario_as_unexecuted(self):
        spec = {"title": "Evidence fixture", "qa_scenarios": [progress()]}
        report = validate(
            SOURCES,
            assemble(SOURCES, spec["title"]),
            threading.Event(),
            spec=spec,
            qa_scenarios=spec["qa_scenarios"],
        )
        self.assertEqual(report["status"], "partial")
        item = next(check for check in report["checks"] if check["check_kind"] == "scenario")
        self.assertEqual(item["status"], "skipped")
        self.assertEqual(item["scenario_id"], "progress")
        self.assertTrue(report_matches(report, SOURCES, assemble(SOURCES, spec["title"]), spec))

    @unittest.skipUnless(shutil.which("node"), "Node syntax parser unavailable")
    def test_generated_source_is_parsed_without_host_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "should-not-exist"
            files = {
                **SOURCES,
                "engine.js": SOURCES["engine.js"]
                + '\nrequire("node:fs").writeFileSync('
                + json.dumps(str(sentinel))
                + ', "executed");',
            }
            report = static_validate(files, assemble(files, "Parse only"), threading.Event())
            self.assertFalse(report["errors"])
            self.assertFalse(
                sentinel.exists(),
                "Generated JavaScript must never be host-executed by static validation",
            )


class RuntimeEvidenceTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "Node unavailable for trusted activation decision tests"
    )
    def test_audio_activation_observes_state_and_never_blindly_toggles(self):
        module = (ROOT / "validator/audio_activation.mjs").as_uri()
        script = f"""import assert from 'node:assert/strict';
import {{activateAudioControl}} from {json.dumps(module)};
function adapter(initial,after='on'){{let state=initial,clicks=0,waits=0;return {{readState:async()=>state,click:async()=>{{clicks++;state=after;}},waitForEnabled:async()=>{{waits++;}},counts:()=>[clicks,waits]}};}}
let fake=adapter('on');let result=await activateAudioControl(fake);assert.equal(result.status,'passed');assert.deepEqual(fake.counts(),[0,0]);assert.equal(result.evidence.clicked,false);
fake=adapter('off');result=await activateAudioControl(fake);assert.equal(result.status,'passed');assert.deepEqual(fake.counts(),[1,1]);assert.equal(result.evidence.final_state,'on');
fake=adapter('unknown');assert.equal((await activateAudioControl(fake)).status,'failed');assert.deepEqual(fake.counts(),[0,0]);assert.equal((await activateAudioControl(fake,{{required:false}})).status,'skipped');assert.deepEqual(fake.counts(),[0,0]);
fake=adapter('off','off');assert.equal((await activateAudioControl(fake)).status,'failed');assert.deepEqual(fake.counts(),[1,1]);
fake=adapter('off');fake.click=async()=>{{throw new Error('Control hidden');}};assert.equal((await activateAudioControl(fake)).status,'failed');
console.log('Trusted audio activation decisions passed; no browser or real audio executed.');"""
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def full_report(self):
        manifest = artifact_manifest({}, "<html>fixture</html>", {})
        return {
            "schema_version": 2,
            "artifact": manifest,
            "request_sha256": "a" * 64,
            "checks": [
                check_record(
                    f"{name}:{width}",
                    "passed",
                    "Fixture observation",
                    manifest,
                    check_kind="browser",
                )
                for name in RUNTIME_CHECKS
                for width in (1280, 390)
            ],
            "errors": [],
            "warnings": [],
        }

    def test_stale_duplicate_or_missing_scenario_evidence_fails(self):
        valid = self.full_report()
        self.assertEqual(
            checked_report(
                copy.deepcopy(valid),
                expected_manifest=valid["artifact"],
                expected_request_sha256="a" * 64,
            ),
            valid,
        )
        with self.assertRaisesRegex(ValueError, "different QA request"):
            checked_report(copy.deepcopy(valid), expected_request_sha256="b" * 64)
        with self.assertRaisesRegex(ValueError, "different artifact"):
            checked_report(copy.deepcopy(valid), expected_manifest={})
        duplicate = copy.deepcopy(valid)
        duplicate["checks"].append(copy.deepcopy(duplicate["checks"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            checked_report(duplicate)
        with self.assertRaisesRegex(ValueError, "omitted"):
            checked_report(copy.deepcopy(valid), scenario_ids=["progress"])
        forged = copy.deepcopy(valid)
        forged["checks"][0]["check_kind"] = "model_review"
        with self.assertRaisesRegex(ValueError, "kind"):
            checked_report(forged)

    def test_no_docker_keeps_scenarios_skipped_with_exact_artifact_binding(self):
        manifest = artifact_manifest(SOURCES, "game bytes", {})
        with patch("prompt2play.legacy.validator.docker.shutil.which", return_value=None):
            report = run_validation(
                "game bytes", [], threading.Event(), manifest=manifest, qa_scenarios=[progress()]
            )
        self.assertEqual(len(report["checks"]), 2)
        for check in report["checks"]:
            self.assertEqual(check["status"], "skipped")
            self.assertEqual(check["artifact_sha256"], manifest["html_sha256"])

    @unittest.skipUnless(shutil.which("node"), "Node unavailable for trusted interpreter tests")
    def test_trusted_interpreter_catches_terminal_accounting_focus_and_pause_regressions(self):
        # Only handwritten harness code and an explicit fake adapter execute here.
        # No generated source is imported, evaluated or loaded through Node VM.
        runner = (ROOT / "validator/scenario_runner.mjs").as_uri()
        item = scenario(
            {"op": "capture", "key": "before"},
            {"op": "focus", "selector": "#target"},
            {"op": "act", "action": {"type": "resolve"}},
            {
                "op": "assert",
                "left": {
                    "sum": [
                        {"path": "/killed"},
                        {"path": "/escaped"},
                        {"count": {"path": "/active"}},
                    ]
                },
                "cmp": "eq",
                "right": {"path": "/spawned"},
            },
            {
                "op": "assert",
                "left": {"element": "#target", "property": "focused"},
                "cmp": "eq",
                "right": {"value": True},
            },
            {"op": "act", "action": {"type": "pause"}},
            {"op": "capture", "key": "paused"},
            {"op": "advance", "frames": 60},
            {
                "op": "assert",
                "left": {"path": "/tick"},
                "cmp": "eq",
                "right": {"saved": "paused", "path": "/tick"},
            },
        )
        decoded = validate_scenarios([item])[0]
        script = f"""import assert from 'node:assert/strict';
import {{runScenario}} from {json.dumps(runner)};
const scenario={json.dumps(decoded)};
function fake({{doubleCount=false,loseFocus=false,brokenPause=false}}={{}}){{
 let state,manual=false,focused=false;
 return {{
  setManualMode:async value=>{{manual=value;}},
  reset:async()=>{{state={{tick:0,killed:0,escaped:0,active:[1,2],spawned:2,paused:false}};}},
  snapshot:async()=>structuredClone(state),
  act:async action=>{{if(action.type==='resolve'){{state.killed=doubleCount?2:1;state.escaped=1;state.active=[];state.tick++;if(loseFocus)focused=false;}}if(action.type==='pause')state.paused=true;}},
  advance:async frames=>{{assert.equal(manual,true);if(!state.paused||brokenPause)state.tick+=frames;}},
  focus:async()=>{{focused=true;}},readElement:async()=>focused,
  click:async()=>{{}},key:async()=>{{}},manual:()=>manual
 }};
}}
const good=fake();const passed=await runScenario(good,scenario);assert.equal(passed.ok,true,passed.message);assert.equal(passed.evidence.assertions,3);assert.equal(good.manual(),false);
for(const flag of ['doubleCount','loseFocus','brokenPause']){{const adapter=fake({{[flag]:true}});const result=await runScenario(adapter,scenario);assert.equal(result.ok,false,flag);assert.match(result.message,/Assertion/);assert.equal(adapter.manual(),false);}}
const missing=structuredClone(scenario);missing.steps[3]={{op:'assert',left:{{path:'/absent'}},cmp:'ne',right:{{value:123}}}};assert.equal((await runScenario(fake(),missing)).ok,false);
console.log('Trusted DSL interpreter: correct sequence passed; double counting, focus loss, broken pause and missing observations rejected.');"""
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
