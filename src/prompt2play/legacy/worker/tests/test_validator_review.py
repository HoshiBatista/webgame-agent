"""Review regressions for trusted validator code; no generated JS is executed."""

import copy
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from prompt2play.legacy.validator.docker import RUNTIME_CHECKS, checked_report
from prompt2play.legacy.validator.evidence import artifact_manifest, check_record
from prompt2play.legacy.validator.scenarios import validate_scenarios


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("node"), "Node unavailable for authored transport tests")
class BridgeAdapterReviewTests(unittest.TestCase):
    def run_node(self, body):
        # Import the same trusted transport used by runtime.mjs. The page double
        # invokes its callbacks on handwritten objects, with no browser or game.
        source = "\n".join(
            [
                "import assert from 'node:assert/strict';",
                "import {bridgeAdapter} from "
                + json.dumps((ROOT / "validator/bridge_adapter.mjs").as_uri())
                + ";",
                "const page={evaluate:async(fn,arg)=>await fn(arg)};",
                "const adapter=bridgeAdapter(page);",
                body,
            ]
        )
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", source],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_import_does_not_launder_invalid_outcomes_into_success(self):
        self.run_node(r"""
let imports=0, source;
globalThis.window={__GAME_TEST__:{importSave:async text=>{imports++;source=text;return {ok:false};}}};
assert.deepEqual(await adapter.importSave(''),{ok:false});
assert.equal(source,'','An empty import must reach the real importer unchanged');
assert.equal(imports,1);
for(const result of [{ok:true},{ok:false},Object.assign(Object.create(null),{ok:true})]) {
  window.__GAME_TEST__.importSave=async()=>result;
  assert.deepEqual(await adapter.importSave('real saved text'),{ok:result.ok});
}
for(const result of [null,true,'accepted',{}, {ok:1},Object.assign([],{ok:true}),Object.assign(()=>{}, {ok:true})]) {
  window.__GAME_TEST__.importSave=async()=>result;
  await assert.rejects(adapter.importSave('real saved text'),/importSave must return/);
}
window.__GAME_TEST__.importSave=async()=>{throw new Error('actual importer failure');};
await assert.rejects(adapter.importSave(''),/actual importer failure/);
delete window.__GAME_TEST__.importSave;
await assert.rejects(adapter.importSave(''),/Missing bridge method importSave/);
""")

    def test_snapshot_preserves_sync_json_contract_and_null_prototype_data(self):
        self.run_node(r"""
const state=Object.assign(Object.create(null),{bank:7,inventory:['ore'],flags:{claimed:true}});
globalThis.window={__GAME_TEST__:{snapshot:()=>state}};
const observed=await adapter.snapshot();
assert.deepEqual(observed,{bank:7,inventory:['ore'],flags:{claimed:true}});
observed.inventory.push('fabricated');
assert.deepEqual(state.inventory,['ore'],'Snapshot transport must detach nested game state');
for(const result of [null,[],1,'state',()=>({}),Promise.resolve({bank:7}),{then:()=>{}}]) {
  window.__GAME_TEST__.snapshot=()=>result;
  await assert.rejects(adapter.snapshot(),/synchronously return a JSON object/);
}
for(const result of [{bank:Infinity},{bank:NaN},{bank:undefined},{bank:1n},{bank:()=>7}]) {
  window.__GAME_TEST__.snapshot=()=>result;
  await assert.rejects(adapter.snapshot(),/non-finite|plain JSON/);
}
for(const result of [{toJSON:()=>[7]},{toJSON:()=>null},{toJSON:()=>7},new Date(0)]) {
  window.__GAME_TEST__.snapshot=()=>result;
  await assert.rejects(adapter.snapshot(),/plain JSON/);
}
window.__GAME_TEST__.snapshot=()=>({payload:'Ж'.repeat(256001)});
await assert.rejects(adapter.snapshot(),/oversized snapshot/);
""")

    def test_nested_non_json_values_are_not_hidden_by_json_stringify(self):
        self.run_node(
            r"""
const {runInNewContext}=await import('node:vm');
const {runScenario}=await import(RUNNER_URI);
const crossRealm=runInNewContext('({bank:7,nested:{items:[1,2]}})');
globalThis.window={__GAME_TEST__:{snapshot:()=>crossRealm}};
assert.deepEqual(await adapter.snapshot(),{bank:7,nested:{items:[1,2]}});
const scenario={seed:'json',category:'accounting',purpose:'Observe actual JSON state',steps:[
  {op:'act',action:{type:'read'}},{op:'assert',left:{path:'/bank'},cmp:'eq',right:{value:7}}]};
const direct={setManualMode:()=>{},reset:()=>{},act:()=>{},snapshot:()=>crossRealm};
assert.equal((await runScenario(direct,scenario)).ok,true,'Cross-realm authored JSON remains valid');
for(const nonJson of [Promise.resolve(7),new Map([['bank',7]]),new Set([7]),new Date(0),
  {toJSON:()=>({bank:7})},new (class State {constructor(){this.bank=7;}})()]) {
  const state={bank:7,nested:{value:nonJson}};
  window.__GAME_TEST__.snapshot=()=>state;
  await assert.rejects(adapter.snapshot(),/plain JSON/);
  const result=await runScenario({...direct,snapshot:()=>state},scenario);
  assert.equal(result.ok,false);assert.match(result.message,/plain JSON/);
}
""".replace("RUNNER_URI", json.dumps((ROOT / "validator/scenario_runner.mjs").as_uri()))
        )

    def test_serializer_rejects_invalid_bytes_before_transport(self):
        self.run_node(r"""
globalThis.window={__GAME_TEST__:{exportSave:()=>'{"bank":7}'}};
assert.equal(await adapter.exportSave(),'{"bank":7}');
for(const result of ['', '   ', '\0',null,{},'Ж'.repeat(256001)]) {
  window.__GAME_TEST__.exportSave=()=>result;
  await assert.rejects(adapter.exportSave(),/Invalid or oversized serialized save/);
}
window.__GAME_TEST__.exportSave=()=> 'x'.repeat(512000);
assert.equal((await adapter.exportSave()).length,512000);
""")


@unittest.skipUnless(shutil.which("node"), "Node unavailable for authored interpreter tests")
class JsonPointerReviewTests(unittest.TestCase):
    def test_arrays_expose_elements_only_and_objects_keep_real_length_members(self):
        scenario = {
            "id": "pointer",
            "purpose": "Observe actual JSON members",
            "category": "accounting",
            "seed": "pointer",
            "affected_files": ["engine.js"],
            "limitations": ["Trusted handwritten snapshot; no browser execution"],
            "steps": [
                {"op": "act", "action": {"type": "read"}},
                {"op": "assert", "left": {"path": "/items/1"}, "cmp": "eq", "right": {"value": 2}},
                {
                    "op": "assert",
                    "left": {"count": {"path": "/items"}},
                    "cmp": "eq",
                    "right": {"value": 2},
                },
                {
                    "op": "assert",
                    "left": {"path": "/named/length"},
                    "cmp": "eq",
                    "right": {"value": 9},
                },
                {
                    "op": "assert",
                    "left": {"path": "/a~1b/~0key"},
                    "cmp": "eq",
                    "right": {"value": 4},
                },
            ],
        }
        normalized = validate_scenarios([scenario])[0]
        source = "\n".join(
            [
                "import assert from 'node:assert/strict';",
                "import {runScenario} from "
                + json.dumps((ROOT / "validator/scenario_runner.mjs").as_uri())
                + ";",
                "const scenario=" + json.dumps(normalized) + ";",
                r"""
const adapter={setManualMode:()=>{},reset:()=>{},act:()=>{},
  snapshot:()=>({items:[1,2],named:{length:9},'a/b':{'~key':4},'bad~2key':7})};
const valid=await runScenario(adapter,scenario);
assert.equal(valid.ok,true,valid.message);assert.equal(valid.evidence.assertions,4);
for(const path of ['/items/length','/items/01','/items/-','/items/2']) {
  const invalid={...scenario,steps:[scenario.steps[0],{op:'assert',left:{path},cmp:'exists'}]};
  const outcome=await runScenario(adapter,invalid);
  assert.equal(outcome.ok,false,'Not a JSON array member: '+path);
}
const invalid={...scenario,steps:[scenario.steps[0],{op:'assert',left:{path:'/bad~2key'},cmp:'exists'}]};
assert.match((await runScenario(adapter,invalid)).message,/Invalid JSON Pointer escape/);
for(const value of [[7],null,7,'invented snapshot']) {
  const transformed={...adapter,snapshot:()=>({toJSON:()=>value})};
  const result=await runScenario(transformed,scenario);
  assert.equal(result.ok,false);assert.match(result.message,/plain JSON/);
}
""",
            ]
        )
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", source],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RuntimeIdentityReviewTests(unittest.TestCase):
    def report(self):
        manifest = artifact_manifest({}, "<html>authored fixture</html>", {})
        checks = [
            check_record(
                f"{name}:{width}", "passed", "Authored observation", manifest, check_kind="browser"
            )
            for name in RUNTIME_CHECKS
            for width in (1280, 390)
        ]
        checks.extend(
            check_record(
                f"scenario:progress:{width}",
                "passed",
                "Authored scenario",
                manifest,
                check_kind="scenario",
                scenario_id="progress",
                evidence={"steps_completed": 2, "assertions": 1},
            )
            for width in (1280, 390)
        )
        return {
            "schema_version": 2,
            "artifact": manifest,
            "checks": checks,
            "errors": [],
            "warnings": [],
        }

    def test_browser_slots_cannot_masquerade_as_scenario_evidence(self):
        valid = self.report()
        self.assertEqual(checked_report(copy.deepcopy(valid), scenario_ids=["progress"]), valid)
        for kind, scenario_id in (("scenario", "progress"), ("browser", "progress")):
            invalid = copy.deepcopy(valid)
            invalid["checks"][0].update(check_kind=kind, scenario_id=scenario_id)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Mismatched|identity"):
                checked_report(invalid, scenario_ids=["progress"])

    def test_name_kind_id_and_viewport_stay_bound_even_for_partial_failures(self):
        valid = self.report()
        modifications = [
            {"name": "scenario:progress:800"},
            {"name": "scenario:progress:390:extra"},
            {"name": "scenario:other:1280"},
            {"check_kind": "browser"},
        ]
        for modification in modifications:
            for errors in ([], ["Separate runtime failure"]):
                invalid = copy.deepcopy(valid)
                invalid["errors"] = errors
                invalid["checks"][-2].update(modification)
                with (
                    self.subTest(modification=modification, failed=bool(errors)),
                    self.assertRaises(ValueError),
                ):
                    checked_report(invalid, scenario_ids=["progress"])
        partial = {
            **valid,
            "checks": [
                check_record(
                    "runtime_harness",
                    "failed",
                    "Actual harness error",
                    valid["artifact"],
                    check_kind="browser",
                )
            ],
            "errors": [],
        }
        self.assertEqual(
            checked_report(partial, scenario_ids=["progress"])["errors"], ["Actual harness error"]
        )
        partial["checks"][0]["status"] = "passed"
        with self.assertRaisesRegex(ValueError, "identity"):
            checked_report(partial, scenario_ids=["progress"])


if __name__ == "__main__":
    unittest.main()
