"""Camp-derived validator regressions; only trusted adapters execute on the host."""

import copy
import json
import shutil
import subprocess
import threading
import unittest
from pathlib import Path

from prompt2play.legacy.validator.checks import assemble, validate
from prompt2play.legacy.validator.scenarios import validate_scenarios
from prompt2play.legacy.worker.tests.fixtures import PLAN, SOURCES

ROOT = Path(__file__).resolve().parents[2]


def case(*steps, ident="persistence"):
    return {
        "id": ident,
        "purpose": "Exercise save/import through actual adapter methods",
        "category": "persistence",
        "seed": "save-test",
        "steps": list(steps),
        "affected_files": ["engine.js", "ui.js"],
        "limitations": ["Handwritten adapter test; no generated game or browser execution"],
    }


def roundtrip():
    return case(
        {"op": "act", "action": {"type": "train"}, "repeat": 2},
        {"op": "act", "action": {"type": "claim"}},
        {"op": "capture", "key": "earned"},
        {"op": "serialize", "key": "checkpoint"},
        {"op": "act", "action": {"type": "train"}},
        {"op": "restore", "saved": "checkpoint", "expect": "accepted"},
        {
            "op": "assert",
            "left": {"path": "/world"},
            "cmp": "eq",
            "right": {"saved": "earned", "path": "/world"},
        },
        {"op": "restore", "text": "", "expect": "rejected"},
        {
            "op": "assert",
            "left": {"path": "/world"},
            "cmp": "eq",
            "right": {"saved": "earned", "path": "/world"},
        },
        {"op": "act", "action": {"type": "claim"}, "repeat": 2},
        {"op": "assert", "left": {"path": "/world/bank"}, "cmp": "eq", "right": {"value": 7}},
        {"op": "act", "action": {"type": "new-run"}},
        {"op": "assert", "left": {"path": "/world/experience"}, "cmp": "eq", "right": {"value": 0}},
        {"op": "assert", "left": {"path": "/world/bank"}, "cmp": "eq", "right": {"value": 7}},
    )


class PersistenceSchemaTests(unittest.TestCase):
    def test_roundtrip_uses_separate_saved_bytes_and_snapshot_namespaces(self):
        declaration = roundtrip()
        before = copy.deepcopy(declaration)
        decoded = validate_scenarios([declaration])
        self.assertEqual(declaration, before)
        self.assertEqual(validate_scenarios(decoded), decoded)
        self.assertEqual(decoded[0]["steps"][7]["text"], "")

    def test_restore_requires_declared_save_or_bounded_literal_and_explicit_outcome(self):
        failures = [
            {"op": "restore", "saved": "future", "expect": "accepted"},
            {"op": "restore", "saved": "before", "text": "", "expect": "rejected"},
            {"op": "restore", "expect": "rejected"},
            {"op": "restore", "text": "", "expect": True},
            {"op": "restore", "text": None, "expect": "rejected"},
            {"op": "restore", "text": "x" * 8193, "expect": "rejected"},
            {"op": "restore", "text": "", "expect": "throws"},
            {"op": "restore", "text": '{"bank":999,"experience":100}', "expect": "accepted"},
            {"op": "restore", "text": "", "expect": "rejected", "evaluate": "bad()"},
            {"op": "storage_fault", "mode": "random"},
            {"op": "storage_fault", "mode": []},
            {"op": "serialize", "key": "bad/key"},
        ]
        observation = {"op": "assert", "left": {"path": "/world"}, "cmp": "exists"}
        for step in failures:
            with self.subTest(step=step), self.assertRaises(ValueError):
                validate_scenarios([case({"op": "capture", "key": "before"}, step, observation)])
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_scenarios(
                [
                    case(
                        {"op": "serialize", "key": "save"},
                        {"op": "serialize", "key": "save"},
                        observation,
                    )
                ]
            )

    def test_storage_and_serialization_have_independent_suite_and_memory_bounds(self):
        observation = {"op": "assert", "left": {"path": "/world"}, "cmp": "exists"}
        with self.assertRaisesRegex(ValueError, "at most 8"):
            validate_scenarios(
                [
                    case(
                        *[{"op": "serialize", "key": "save" + str(i)} for i in range(9)],
                        observation,
                    )
                ]
            )
        with self.assertRaisesRegex(ValueError, "8 storage fault"):
            validate_scenarios(
                [case(*[{"op": "storage_fault", "mode": "normal"} for _ in range(9)], observation)]
            )
        scenarios = [
            case(
                *[{"op": "restore", "text": "", "expect": "rejected"} for _ in range(33)],
                observation,
                ident="case" + str(i),
            )
            for i in range(2)
        ]
        with self.assertRaisesRegex(ValueError, "64 persistence"):
            validate_scenarios(scenarios)

    def test_literal_tautologies_do_not_count_as_observable_evidence(self):
        for value in (
            {"value": 1},
            {"sum": [{"value": 1}]},
            {"count": {"value": ["fixed"]}},
            {"value": {"path": "/fake", "element": "#also-fake"}},
        ):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "observable"):
                validate_scenarios(
                    [
                        case(
                            {"op": "act", "action": {"type": "train"}},
                            {"op": "assert", "left": value, "cmp": "eq", "right": {"value": 1}},
                        )
                    ]
                )
        with self.assertRaisesRegex(ValueError, "self-comparisons"):
            validate_scenarios(
                [
                    case(
                        {"op": "act", "action": {"type": "train"}},
                        {
                            "op": "assert",
                            "left": {"path": "/world"},
                            "cmp": "eq",
                            "right": {"path": "/world"},
                        },
                    )
                ]
            )


NODE_ADAPTER = r"""
import assert from 'node:assert/strict';
import {runScenario} from RUNNER_URI;
function fake(flags = {}) {
  let state, manual = false, mode = 'normal';
  const counts = {blocked_reads:0,blocked_writes:0,blocked_removals:0,denied_accesses:0};
  function persist() {
    if (mode !== 'normal' && !flags.ignoreFault) {
      if (mode === 'quota') counts.blocked_writes++;
      else counts.denied_accesses++;
      state.persistence = flags.falseDurable ? 'saved' : 'memory';
    } else state.persistence = flags.ignoreFault ? 'memory' : 'saved';
  }
  return {
    reset: async () => {state = {world:{bank:0,experience:0,claimed:false},notice:'',persistence:'saved'};},
    setManualMode: async value => {if (!value && flags.badCleanup) throw new Error('cleanup failed'); manual=value;},
    snapshot: async () => flags.nonfinite ? {world:{bank:Infinity}} : structuredClone(state),
    act: async action => {
      if (action.type === 'train') state.world.experience++;
      if (action.type === 'claim' && (!state.world.claimed || flags.doubleClaim)) {state.world.bank+=7;state.world.claimed=true;}
      if (action.type === 'new-run') state.world.experience=0;
      persist();
    },
    exportSave: async () => flags.largeSave ? 'Ж'.repeat(256001) : flags.manyBytes ? 'x'.repeat(512000) : JSON.stringify(state.world),
    importSave: async text => {
      if (flags.badResult) return true;
      try {
        if (!text.trim()) {
          if (flags.throwBlank) throw null;
          if (flags.acceptBlank) return {ok:true};
          if (flags.mutateRejected) state.world.bank=999;
          state.notice='Import rejected without changing the live game';
          return {ok:false};
        }
        state.world = JSON.parse(text);
        if (flags.loseBank) state.world.bank=0;
        persist();
        return {ok:true};
      } catch (error) {
        if (flags.throwBlank) throw error;
        return {ok:false};
      }
    },
    setStorageFault: async value => {if (!(flags.stuckFault && value === 'normal' && mode !== 'normal')) mode=value;},
    storageSnapshot: async () => ({available:true,mode,...counts}),
    manual: () => manual, mode: () => mode,
  };
}
"""


@unittest.skipUnless(shutil.which("node"), "Node unavailable for trusted interpreter tests")
class PersistenceInterpreterTests(unittest.TestCase):
    def run_node(self, body):
        helper = NODE_ADAPTER.replace(
            "RUNNER_URI", json.dumps((ROOT / "validator/scenario_runner.mjs").as_uri())
        )
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", helper + "\n" + body],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_roundtrip_rejection_and_duplicate_claim_use_actual_adapter_paths(self):
        item = validate_scenarios([roundtrip()])[0]
        self.run_node(
            "const scenario="
            + json.dumps(item)
            + r""";
const good=fake();const result=await runScenario(good,scenario);
assert.equal(result.ok,true,result.message);assert.equal(result.evidence.assertions,5);
assert.equal(result.evidence.serializations,1);assert.equal(result.evidence.imports_accepted,1);
assert.equal(result.evidence.imports_rejected,1);assert.equal(good.manual(),false);
for (const flag of ['loseBank','acceptBlank','mutateRejected','doubleClaim','badResult','throwBlank']) {
  const outcome=await runScenario(fake({[flag]:true}),scenario);
  assert.equal(outcome.ok,false,flag+' must be rejected');
}
"""
        )

    def test_missing_persistence_bridge_methods_are_failures_not_silent_skips(self):
        item = validate_scenarios([roundtrip()])[0]
        self.run_node(
            "const scenario="
            + json.dumps(item)
            + r""";
for(const method of ['exportSave','importSave']) {
  const adapter=fake();delete adapter[method];
  const result=await runScenario(adapter,scenario);assert.equal(result.ok,false);
  assert.match(result.message,new RegExp(method));assert.equal(adapter.manual(),false);
}
"""
        )

    def test_literal_accepted_restore_cannot_install_fabricated_state(self):
        item = roundtrip()
        item["steps"] = [
            {"op": "restore", "text": '{"bank":999,"experience":100}', "expect": "accepted"},
            {"op": "assert", "left": {"path": "/world/bank"}, "cmp": "eq", "right": {"value": 999}},
        ]
        self.run_node(
            "const scenario="
            + json.dumps(item)
            + r""";
const adapter=fake();let imports=0;
const original=adapter.importSave;adapter.importSave=async text=>{imports++;return original(text);};
const result=await runScenario(adapter,scenario);
assert.equal(result.ok,false);assert.match(result.message,/accepted restore requires a serialized save/);
assert.equal(imports,0,'A rejected DSL declaration must not call the game importer');
assert.equal((await adapter.snapshot()).world.bank,0);assert.equal(adapter.manual(),false);
"""
        )

    def test_faults_need_a_real_blocked_operation_and_recover_before_the_next_scenario(self):
        items = []
        for mode in ("quota", "denied"):
            items.append(
                case(
                    {"op": "storage_fault", "mode": mode},
                    {"op": "act", "action": {"type": "claim"}},
                    {
                        "op": "assert",
                        "left": {"path": "/persistence"},
                        "cmp": "eq",
                        "right": {"value": "memory"},
                    },
                    {
                        "op": "assert",
                        "left": {"path": "/world/bank"},
                        "cmp": "eq",
                        "right": {"value": 7},
                    },
                    {"op": "storage_fault", "mode": "normal"},
                    {"op": "act", "action": {"type": "save"}},
                    {
                        "op": "assert",
                        "left": {"path": "/persistence"},
                        "cmp": "eq",
                        "right": {"value": "saved"},
                    },
                    ident=mode,
                )
            )
        items = validate_scenarios(items)
        self.run_node(
            "const scenarios="
            + json.dumps(items)
            + r""";
for(const scenario of scenarios) {
  const adapter=fake();const result=await runScenario(adapter,scenario);
  assert.equal(result.ok,true,result.message);assert.equal(adapter.mode(),'normal');
  assert.equal(result.evidence.storage_faults.length,1);
  assert.equal(result.evidence.storage_faults[0].exercised,true);
  assert.equal((await runScenario(fake({falseDurable:true}),scenario)).ok,false);
  const ignored=await runScenario(fake({ignoreFault:true}),scenario);
  assert.equal(ignored.ok,false);assert.match(ignored.message,/not exercised/);
}
const unused={...scenarios[0],steps:[{op:'storage_fault',mode:'quota'},
  {op:'assert',left:{path:'/world/bank'},cmp:'eq',right:{value:0}}]};
const adapter=fake();const result=await runScenario(adapter,unused);
assert.equal(result.ok,false);assert.match(result.message,/not exercised/);assert.equal(adapter.mode(),'normal');
const cleanup={...scenarios[0],steps:scenarios[0].steps.slice(0,4)};
const stuck=await runScenario(fake({stuckFault:true}),cleanup);
assert.equal(stuck.ok,false);assert.match(stuck.message,/did not restore normal mode/);
"""
        )

    def test_utf8_save_budgets_finite_snapshots_and_cleanup_fail_closed(self):
        item = validate_scenarios([roundtrip()])[0]
        self.run_node(
            "const scenario="
            + json.dumps(item)
            + r""";
for(const flag of ['largeSave','nonfinite','badCleanup']) {
  const result=await runScenario(fake({[flag]:true}),scenario);assert.equal(result.ok,false,flag);
}
const many={...scenario,steps:[...Array.from({length:5},(_,i)=>({op:'serialize',key:'s'+i})),
  {op:'assert',left:{path:'/world/bank'},cmp:'eq',right:{value:0}}]};
const result=await runScenario(fake({manyBytes:true}),many);
assert.equal(result.ok,false);assert.match(result.message,/2048000/);
"""
        )


@unittest.skipUnless(shutil.which("node"), "Node unavailable for trusted storage probe tests")
class StorageProbeTests(unittest.TestCase):
    def test_quota_denied_cached_access_and_session_isolation_with_storage_double(self):
        module = (ROOT / "validator/storage_probe.mjs").as_uri()
        body = r"""
import assert from 'node:assert/strict';
import {installStorageProbe} from MODULE_URI;
class StorageDouble {
  constructor(){this.data=new Map();}
  get length(){return this.data.size;}
  getItem(key){return this.data.has(String(key))?this.data.get(String(key)):null;}
  setItem(key,value){this.data.set(String(key),String(value));}
  removeItem(key){this.data.delete(String(key));}
  clear(){this.data.clear();}
  key(index){return [...this.data.keys()][index]??null;}
}
const local=new StorageDouble(),session=new StorageDouble();
globalThis.window={sessionStorage:session};
Object.defineProperty(window,'localStorage',{configurable:true,enumerable:true,get:()=>local});
installStorageProbe();
const probe=window.__FORGE_STORAGE_PROBE__,cached=window.localStorage;
assert.equal(probe.snapshot().available,true);
cached.setItem('save','accepted-before-failure');
probe.setMode('quota');
assert.equal(window.localStorage.getItem('save'),'accepted-before-failure');
assert.throws(()=>cached.setItem('save','lost-new-write'),{name:'QuotaExceededError'});
assert.equal(cached.getItem('save'),'accepted-before-failure');
assert.equal(cached.length,1);cached.removeItem('save');assert.equal(cached.length,0);
session.setItem('save','separate-session');assert.equal(session.getItem('save'),'separate-session');
probe.setMode('denied');
assert.throws(()=>window.localStorage,{name:'SecurityError'});
assert.throws(()=>cached.getItem('save'),{name:'SecurityError'});
assert.throws(()=>cached.setItem('save','bad'),{name:'SecurityError'});
assert.throws(()=>cached.removeItem('save'),{name:'SecurityError'});
assert.throws(()=>cached.clear(),{name:'SecurityError'});
assert.throws(()=>cached.length,{name:'SecurityError'});
assert.throws(()=>cached.key(0),{name:'SecurityError'});
assert.equal(session.getItem('save'),'separate-session');
probe.setMode('normal');cached.setItem('save','recovered');assert.equal(cached.getItem('save'),'recovered');
const result=probe.snapshot();assert.equal(result.blocked_writes,2);assert.equal(result.successful_writes,2);
assert.equal(result.blocked_reads,3);assert.equal(result.denied_accesses,1);assert.equal(result.blocked_removals,2);
assert.throws(()=>{window.__FORGE_STORAGE_PROBE__={};});
globalThis.window={};
Object.defineProperty(window,'localStorage',{configurable:true,get(){throw new DOMException('Opaque origin','SecurityError');}});
installStorageProbe();assert.equal(window.__FORGE_STORAGE_PROBE__.snapshot().available,false);
assert.throws(()=>window.__FORGE_STORAGE_PROBE__.setMode('quota'),/unavailable/);
console.log('Trusted storage method probe passed; no browser or real storage device executed.');
""".replace("MODULE_URI", json.dumps(module))
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", body],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class SemanticCoverageEvidenceTests(unittest.TestCase):
    def test_v3_coverage_binds_declarations_without_claiming_execution(self):
        spec = copy.deepcopy(PLAN)
        report = validate(
            SOURCES,
            assemble(SOURCES, spec["title"]),
            threading.Event(),
            spec=spec,
            qa_scenarios=spec["qa_scenarios"],
        )
        coverage = next(item for item in report["checks"] if item["name"] == "semantic_coverage")
        self.assertEqual(coverage["status"], "passed")
        self.assertEqual(coverage["check_kind"], "static")
        self.assertEqual(coverage["evidence"]["status"], "declared")
        self.assertEqual(coverage["evidence"]["first_playable_loop"], "progress")
        self.assertEqual(report["status"], "partial")
        self.assertTrue(
            all(
                item["status"] == "skipped"
                for item in report["checks"]
                if item["check_kind"] == "scenario"
            )
        )

    def test_broken_v3_coverage_is_a_failure_and_legacy_is_not_silently_upgraded(self):
        for broken in ("unknown-loop", "missing-fields"):
            spec = copy.deepcopy(PLAN)
            if broken == "unknown-loop":
                spec["semantic_contract"]["first_playable_loop"]["scenario_id"] = "missing"
            else:
                spec["semantic_contract"].pop("state_domains")
            report = validate(
                SOURCES,
                assemble(SOURCES, spec["title"]),
                threading.Event(),
                spec=spec,
                qa_scenarios=spec["qa_scenarios"],
            )
            self.assertEqual(report["status"], "failed")
            self.assertTrue(
                any(
                    item["name"] == "semantic_coverage" and item["status"] == "failed"
                    for item in report["checks"]
                )
            )
        spec = {"title": "Legacy reference", "semantic_contract": {"version": 2}}
        report = validate(SOURCES, assemble(SOURCES, spec["title"]), threading.Event(), spec=spec)
        self.assertFalse(any(item["name"] == "semantic_coverage" for item in report["checks"]))


if __name__ == "__main__":
    unittest.main()
