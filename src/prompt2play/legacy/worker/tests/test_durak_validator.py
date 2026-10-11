"""Durak-derived validator contracts; only trusted transports/doubles run here.

No generated game source is imported or evaluated on the host. Real Chromium,
OS visibility, BFCache, storage devices and audio playback are not exercised.
"""

import copy
import json
import shutil
import subprocess
import threading
import unittest
from pathlib import Path

from prompt2play.legacy.validator.checks import assemble, validate
from prompt2play.legacy.validator.docker import (
    RUNTIME_CHECKS,
    RUNTIME_CONTRACT_VERSION,
    checked_report,
    scenario_counters,
)
from prompt2play.legacy.validator.evidence import artifact_manifest, check_record
from prompt2play.legacy.validator.scenarios import validate_scenarios
from prompt2play.legacy.worker.tests.fixtures import SOURCES

ROOT = Path(__file__).resolve().parents[2]


def case(*steps, ident="lifecycle"):
    return {
        "id": ident,
        "purpose": "Observe lifecycle and persistence through real adapter paths",
        "category": "lifecycle",
        "seed": "review-seed",
        "steps": list(steps),
        "affected_files": ["engine.js", "ui.js"],
        "limitations": ["Trusted handwritten adapter; no generated game or browser execution"],
    }


def observed(path="/turn", value=1):
    return {"op": "assert", "left": {"path": path}, "cmp": "eq", "right": {"value": value}}


def lifecycle_case():
    return case(
        {"op": "act", "action": {"type": "play"}},
        {"op": "lifecycle", "event": "hide"},
        {"op": "act", "action": {"type": "play"}},
        observed(),
        {"op": "lifecycle", "event": "show"},
        {"op": "act", "action": {"type": "play"}},
        observed(value=2),
        {"op": "act", "action": {"type": "pause"}},
        {"op": "lifecycle", "event": "remount"},
        observed("/paused", False),
        {"op": "act", "action": {"type": "play"}},
        observed(value=3),
        {"op": "reload"},
        observed(value=3),
        {"op": "act", "action": {"type": "play"}},
        observed(value=4),
    )


class LifecycleSchemaTests(unittest.TestCase):
    def test_new_operations_preserve_declarations_and_have_no_seed_or_code_injection(self):
        declaration = lifecycle_case()
        before = copy.deepcopy(declaration)
        decoded = validate_scenarios([declaration])
        self.assertEqual(declaration, before)
        self.assertEqual(validate_scenarios(decoded), decoded)
        for step in (
            {"op": "lifecycle", "event": "visibilitychange"},
            {"op": "lifecycle", "event": "hide", "execute": "bad()"},
            {"op": "lifecycle", "event": []},
            {"op": "reload", "seed": "fabricated"},
            {"op": "reload", "url": "https://external.invalid"},
            {"op": "lifecycle", "event": "remount", "state": {"gold": 999}},
        ):
            with self.subTest(step=step), self.assertRaises(ValueError):
                validate_scenarios([case(step, observed())])

    def test_every_lifecycle_transition_needs_a_subsequent_observation(self):
        sequences = [
            (observed(), {"op": "lifecycle", "event": "hide"}),
            (
                {"op": "lifecycle", "event": "hide"},
                {"op": "lifecycle", "event": "show"},
                observed(),
            ),
            ({"op": "reload"}, {"op": "reset"}, observed()),
            (
                {"op": "lifecycle", "event": "remount"},
                {
                    "op": "assert",
                    "left": {"value": {"path": "/fake"}},
                    "cmp": "ne",
                    "right": {"value": 0},
                },
                {"op": "reload"},
                observed(),
            ),
        ]
        for steps in sequences:
            with (
                self.subTest(steps=steps),
                self.assertRaisesRegex(ValueError, "subsequent observable"),
            ):
                validate_scenarios([case(*steps)])
        for first in (
            {"op": "lifecycle", "event": "hide"},
            {"op": "storage_fault", "mode": "quota"},
            {"op": "storage_fault", "mode": "denied"},
        ):
            with (
                self.subTest(first=first),
                self.assertRaisesRegex(ValueError, "normal storage and visible"),
            ):
                validate_scenarios([case(first, observed(), {"op": "reload"}, observed())])

    def test_new_operations_are_bounded_per_case_and_suite(self):
        lifecycle = [{"op": "lifecycle", "event": "show"}, observed()]
        reload = [{"op": "reload"}, observed()]
        for steps, message in ((lifecycle * 9, "8 lifecycle"), (reload * 3, "2 reloads")):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_scenarios([case(*steps)])
        for steps, cases in ((lifecycle * 7, 4), (reload * 2, 5)):
            with (
                self.subTest(cases=cases),
                self.assertRaisesRegex(ValueError, "24 lifecycle operations or 8 reloads"),
            ):
                validate_scenarios([case(*steps, ident="case" + str(i)) for i in range(cases)])

    def test_post_transition_assertions_need_live_operands_not_old_captures(self):
        prefix = [{"op": "act", "action": {"type": "play"}}, {"op": "capture", "key": "before"}]
        for event in ("hide", "remount", "reload"):
            transition = (
                {"op": "reload"} if event == "reload" else {"op": "lifecycle", "event": event}
            )
            for operand, value in (
                ({"saved": "before", "path": "/turn"}, 1),
                ({"sum": [{"saved": "before", "path": "/turn"}, {"value": 0}]}, 1),
                ({"count": {"saved": "before", "path": "/played"}}, 0),
            ):
                stale = {"op": "assert", "left": operand, "cmp": "eq", "right": {"value": value}}
                with (
                    self.subTest(event=event, operand=operand),
                    self.assertRaisesRegex(ValueError, "live path or DOM"),
                ):
                    validate_scenarios([case(*prefix, transition, stale)])
            live = {
                "op": "assert",
                "left": {"path": "/turn"},
                "cmp": "eq",
                "right": {"saved": "before", "path": "/turn"},
            }
            self.assertEqual(
                validate_scenarios([case(*prefix, transition, live)])[0]["steps"][-1], live
            )
            # A current observation may occur on either side of a comparison.
            reverse = {**live, "left": live["right"], "right": live["left"]}
            validate_scenarios([case(*prefix, transition, reverse)])
        # Saved observations remain valid ordinary assertions outside a lifecycle obligation.
        validate_scenarios(
            [
                case(
                    *prefix,
                    {
                        "op": "assert",
                        "left": {"saved": "before", "path": "/turn"},
                        "cmp": "eq",
                        "right": {"value": 1},
                    },
                )
            ]
        )

    def test_static_declarations_do_not_pass_unexecuted_dom_or_lifecycle_checks(self):
        declaration = lifecycle_case()
        spec = {
            "title": "DOM acceptance declaration",
            "presentation_mode": "dom",
            "qa_scenarios": [declaration],
        }
        report = validate(
            SOURCES,
            assemble(SOURCES, spec["title"]),
            threading.Event(),
            spec=spec,
            qa_scenarios=spec["qa_scenarios"],
        )
        self.assertEqual(report["status"], "partial")
        runtime_checks = [
            item for item in report["checks"] if item["check_kind"] in ("scenario", "browser")
        ]
        self.assertTrue(runtime_checks)
        self.assertTrue(all(item["status"] == "skipped" for item in runtime_checks))


NODE_FAKE = r"""
function fake(flags={}) {
  let state, persisted=0, manual=false, hidden=false, mode='normal', hides=0, shows=0, resets=0;
  const fresh=()=>({turn:persisted,paused:false,selected:null,played:[],focused:null});
  const adapter={
    setManualMode:async value=>{manual=value;},
    reset:async()=>{resets++;persisted=0;state=fresh();},
    snapshot:async()=>structuredClone(state),
    act:async action=>{
      if(action.type==='pause') state.paused=true;
      if(action.type==='play' && !state.paused && (!hidden || flags.ignoreHidden)) {state.turn++;persisted=state.turn;}
    },
    lifecycleSnapshot:async()=>({available:true,synthetic:true,mode,hidden,hides,shows}),
    lifecycle:async event=>{
      if(flags.ignoreEvent)return;
      mode=event==='hide'?'hidden':'visible';hidden=event==='hide';
      if(hidden)hides++;else shows++;
    },
    clearLifecycle:async()=>{
      if(flags.badCleanup)return;
      mode='normal';hidden=false;
    },
    remount:async()=>{
      if(!flags.stalePause) state=fresh();
      return flags.noAck ? undefined : {ok:true};
    },
    reload:async()=>{if(flags.loseSave) persisted=0;state=fresh();return {ok:true};},
    focus:async selector=>{state.focused=selector;},
    click:async selector=>{state.selected=selector;state.focused=selector;},
    key:async key=>{
      if(key==='Enter') {
        if(state.selected && (flags.staleSelection || state.selected===state.focused)) state.played.push(state.selected);
        else state.selected=state.focused;
      }
      if(key==='Escape'){state.selected=null;if(flags.loseFocus)state.focused=null;}
    },
    readElement:async(selector,property)=>property==='focused'&&state.focused===selector,
    inspection:()=>({manual,hidden,resets,mode}),
  };
  return adapter;
}
"""


@unittest.skipUnless(shutil.which("node"), "Node unavailable for trusted validator doubles")
class TrustedTransportTests(unittest.TestCase):
    def run_node(self, body, fake=False):
        imports = "\n".join(
            "import {" + name + "} from " + json.dumps((ROOT / "validator" / file).as_uri()) + ";"
            for name, file in (
                ("runScenario", "scenario_runner.mjs"),
                ("installLifecycleProbe", "lifecycle_probe.mjs"),
                ("inspectSurface", "surface_probe.mjs"),
                ("bridgeAdapter", "bridge_adapter.mjs"),
            )
        )
        source = (
            "import assert from 'node:assert/strict';\n"
            + imports
            + "\n"
            + (NODE_FAKE if fake else "")
            + body
        )
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", source],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lifecycle_remount_reload_detect_transient_and_durable_state_regressions(self):
        scenario = validate_scenarios([lifecycle_case()])[0]
        expected = scenario_counters(scenario)
        self.run_node(
            "const scenario="
            + json.dumps(scenario)
            + ";const expected="
            + json.dumps(expected)
            + r""";
const adapter=fake(), result=await runScenario(adapter,scenario);
assert.equal(result.ok,true,result.message);
for(const [name,value] of Object.entries(expected)) assert.deepEqual(result.evidence[name],value,name);
assert.deepEqual(result.evidence.cleanup,{manual_clock:true,storage:true,lifecycle:true});
assert.deepEqual(adapter.inspection(),{manual:false,hidden:false,resets:1,mode:'normal'});
for(const flag of ['ignoreHidden','stalePause','loseSave','noAck','ignoreEvent','badCleanup']) {
  const invalid=await runScenario(fake({[flag]:true}),scenario);
  assert.equal(invalid.ok,false,flag+' must not pass');
}
""",
            fake=True,
        )

    def test_missing_lifecycle_paths_unobserved_transitions_and_empty_cases_fail(self):
        scenario = validate_scenarios([lifecycle_case()])[0]
        self.run_node(
            "const scenario="
            + json.dumps(scenario)
            + r""";
for(const method of ['remount','reload','lifecycle','lifecycleSnapshot','clearLifecycle']) {
  const adapter=fake();delete adapter[method];
  const result=await runScenario(adapter,scenario);assert.equal(result.ok,false,method);
}
for(const steps of [[],[{op:'act',action:{type:'play'}}],
  [{op:'assert',left:{path:'/turn'},cmp:'eq',right:{value:0}},{op:'lifecycle',event:'hide'}],
  [{op:'lifecycle',event:'hide'},{op:'lifecycle',event:'show'},{op:'assert',left:{path:'/turn'},cmp:'eq',right:{value:0}}]]) {
  const result=await runScenario(fake(),{...scenario,steps});assert.equal(result.ok,false);
}
""",
            fake=True,
        )

    def test_interpreter_rejects_stale_post_transition_capture_even_if_schema_is_bypassed(self):
        self.run_node(
            r"""
for(const event of ['hide','remount','reload']) {
  const transition=event==='reload'?{op:'reload'}:{op:'lifecycle',event};
  const scenario={id:event,seed:'stale-capture',category:'lifecycle',purpose:'Compare current state with the baseline',steps:[
    {op:'act',action:{type:'play'}},{op:'capture',key:'before'},transition,
    {op:'assert',left:{saved:'before',path:'/turn'},cmp:'eq',right:{value:1}}]};
  const broken=fake();
  if(event==='hide') {
    const original=broken.lifecycle;
    broken.lifecycle=async value=>{await original(value);await broken.reset();};
  } else broken[event]=async()=>{await broken.reset();return {ok:true};};
  const result=await runScenario(broken,scenario);
  assert.equal(result.ok,false,event+' must observe the current post-transition state');
  assert.match(result.message,/live path or DOM/);assert.equal((await broken.snapshot()).turn,0);
  const live={...scenario,steps:[...scenario.steps.slice(0,-1),
    {op:'assert',left:{path:'/turn'},cmp:'eq',right:{saved:'before',path:'/turn'}}]};
  const accepted=await runScenario(fake(),live);assert.equal(accepted.ok,true,accepted.message);
}
""",
            fake=True,
        )

    def test_existing_dom_operations_express_focus_and_selected_card_as_distinct_state(self):
        scenario = case(
            {"op": "click", "selector": "#A"},
            {"op": "focus", "selector": "#B"},
            {"op": "key", "key": "Enter"},
            observed("/selected", "#B"),
            observed("/played", []),
            {"op": "key", "key": "Escape"},
            observed("/selected", None),
            {
                "op": "assert",
                "left": {"element": "#B", "property": "focused"},
                "cmp": "eq",
                "right": {"value": True},
            },
            ident="focus",
        )
        scenario = validate_scenarios([scenario])[0]
        self.run_node(
            "const scenario="
            + json.dumps(scenario)
            + r""";
assert.equal((await runScenario(fake(),scenario)).ok,true);
for(const flag of ['staleSelection','loseFocus']) assert.equal((await runScenario(fake({[flag]:true}),scenario)).ok,false);
""",
            fake=True,
        )

    def test_synthetic_probe_delivers_real_events_and_restores_native_visibility(self):
        self.run_node(r"""
globalThis.window=new EventTarget();globalThis.document=new EventTarget();
Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});
Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});
const events=[];
for(const type of ['pagehide','pageshow']) window.addEventListener(type,event=>events.push([event.type,document.hidden,document.visibilityState]));
document.addEventListener('visibilitychange',event=>events.push([event.type,document.hidden,document.visibilityState]));
installLifecycleProbe();const probe=window.__FORGE_LIFECYCLE_PROBE__;
assert.equal(probe.snapshot().available,true);
probe.dispatch('hide');assert.equal(document.hidden,true);assert.equal(document.visibilityState,'hidden');
probe.dispatch('show');assert.equal(document.hidden,false);
assert.deepEqual(events,[['visibilitychange',true,'hidden'],['pagehide',true,'hidden'],['pageshow',false,'visible'],['visibilitychange',false,'visible']]);
assert.deepEqual(probe.snapshot(),{available:true,synthetic:true,mode:'visible',hidden:false,hides:1,shows:1});
probe.dispatch('hide');probe.clear();assert.equal(probe.snapshot().mode,'normal');assert.equal(document.hidden,false);
assert.throws(()=>probe.dispatch('destroy'),/Unsupported/);
assert.throws(()=>{window.__FORGE_LIFECYCLE_PROBE__={};});
""")

    def test_unavailable_probe_cannot_pretend_to_deliver_lifecycle(self):
        self.run_node(r"""
globalThis.window=new EventTarget();globalThis.document=new EventTarget();
Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});
Object.defineProperty(document,'visibilityState',{configurable:false,get:()=> 'visible'});
const old=Object.getOwnPropertyDescriptor(document,'hidden').get;
installLifecycleProbe();const probe=window.__FORGE_LIFECYCLE_PROBE__;
assert.equal(probe.snapshot().available,false);assert.equal(Object.getOwnPropertyDescriptor(document,'hidden').get,old);
assert.throws(()=>probe.dispatch('hide'),/unavailable/);assert.throws(()=>probe.clear(),/unavailable/);
""")

    def test_remount_ack_and_reload_transport_do_not_silently_reset_or_start(self):
        self.run_node(r"""
let resets=0,remounts=0,reloads=0,readyChecks=0;
globalThis.window={__GAME_TEST__:{ready:true,reset:()=>{resets++;},remount:async()=>{remounts++;return {ok:true};}}};
const page={evaluate:async(fn,arg)=>fn(arg),waitForFunction:async fn=>{readyChecks++;if(!fn())throw new Error('not ready');}};
const adapter=bridgeAdapter(page,{reload:async()=>{reloads++;window.__GAME_TEST__={...window.__GAME_TEST__,ready:true};}});
assert.deepEqual(await adapter.remount(),{ok:true});assert.deepEqual(await adapter.reload(),{ok:true});
assert.equal(remounts,1);assert.equal(reloads,1);assert.equal(readyChecks,1);assert.equal(resets,0);
for(const result of [undefined,null,true,'ok',[],{ok:false},Object.assign([],{ok:true})]) {
  window.__GAME_TEST__.remount=async()=>result;await assert.rejects(adapter.remount(),/acknowledge/);
}
window.__GAME_TEST__.remount=async()=>{window.__GAME_TEST__.ready=false;return {ok:true};};
await assert.rejects(adapter.remount(),/not ready/);
delete window.__GAME_TEST__.remount;await assert.rejects(adapter.remount(),/Missing/);
assert.equal(bridgeAdapter(page).reload,undefined,'Missing transport is not an apparent successful reload');
""")

    def test_surface_transport_accepts_dom_and_canvas_and_rejects_dummy_surfaces(self):
        self.run_node(r"""
class ElementDouble {
  constructor(tag='div',children=1){this.tagName=tag.toUpperCase();this.children=children;this.width=640;this.height=480;this.visible=true;this.canvases=[];}
  getBoundingClientRect(){return {width:this.width,height:this.height};}
  querySelectorAll(selector){return selector==='canvas'?this.canvases:Array.from({length:this.children},()=>({}));}
}
class CanvasDouble extends ElementDouble {constructor(){super('canvas',0);}}
globalThis.HTMLCanvasElement=CanvasDouble;globalThis.getComputedStyle=()=>({display:'block',visibility:'visible',opacity:'1'});
function pageFor(nodes,canvases=[]) {
  const queried=[];
  const locator=items=>({count:async()=>items.length,first:()=>locator(items.slice(0,1)),
    isVisible:async()=>items[0]?.visible,evaluate:async(fn,arg)=>fn(items[0],arg)});
  return {queried,locator:selector=>{queried.push(selector);return locator(selector.includes('game-surface')?nodes:canvases);}};
}
let page=pageFor([new ElementDouble()]);
const dom=await inspectSurface(page,'dom');assert.equal(dom.evidence.presentation_mode,'dom');assert.equal(dom.evidence.visible_canvases,0);
assert.deepEqual(page.queried,['[data-testid="game-surface"]','#p2p-surface'],'DOM selects donor/native surfaces without requiring a canvas');
const canvas=new CanvasDouble();page=pageFor([], [canvas]);assert.equal((await inspectSurface(page)).evidence.tag,'canvas');
const hybrid=new ElementDouble('section',3);hybrid.canvases=[canvas];
assert.equal((await inspectSurface(pageFor([hybrid]),'hybrid')).evidence.visible_canvases,1);
for(const [nodes,mode,canvases] of [[[],'dom',[canvas]],[[canvas],'dom',[]],[[new ElementDouble('div',0)],'dom',[]],
  [[new ElementDouble()],'canvas',[]],[[new ElementDouble()],'hybrid',[]],[[new ElementDouble(),new ElementDouble()],'dom',[]]]) {
  await assert.rejects(inspectSurface(pageFor(nodes,canvases),mode));
}
canvas.width=0;await assert.rejects(inspectSurface(pageFor([canvas]),'canvas'),/empty geometry|nonzero/);
await assert.rejects(inspectSurface(pageFor([]),'magic'),/Unsupported/);
""")

    def test_opacity_chain_rejects_transparent_dom_and_canvas_ancestors(self):
        self.run_node(r"""
class ElementDouble {
  constructor(tag='main',parent=null,opacity='1') {
    this.tagName=tag.toUpperCase();this.parentElement=parent;this.opacity=opacity;
    this.width=640;this.height=480;this.canvases=[];
  }
  getBoundingClientRect(){return {width:this.width,height:this.height};}
  querySelectorAll(selector){return selector==='canvas'?this.canvases:[{},{}];}
}
class CanvasDouble extends ElementDouble {constructor(parent){super('canvas',parent);}}
globalThis.HTMLCanvasElement=CanvasDouble;
globalThis.getComputedStyle=node=>({display:'block',visibility:'visible',opacity:node.opacity});
// Keep Playwright-style visibility true: the separate opacity inspection must
// reject invisible content, rather than relying on the locator precheck.
const pageFor=node=>({locator:()=>({count:async()=>1,isVisible:async()=>true,evaluate:async(fn,arg)=>fn(node,arg)})});
const hiddenParent=new ElementDouble('section',null,'0');
for(const [node,mode] of [[new ElementDouble('main',null,'0'),'dom'],
  [new ElementDouble('main',hiddenParent),'dom'],[new CanvasDouble(hiddenParent),'canvas']]) {
  await assert.rejects(inspectSurface(pageFor(node),mode),/fully transparent/);
}
const hybrid=new ElementDouble(), transparentWrapper=new ElementDouble('div',hybrid,'0');
hybrid.canvases=[new CanvasDouble(transparentWrapper)];
await assert.rejects(inspectSurface(pageFor(hybrid),'hybrid'),/visible canvas/);
const partiallyVisible=new ElementDouble('main',new ElementDouble('div',null,'0.25'),'0.5');
assert.equal((await inspectSurface(pageFor(partiallyVisible),'dom')).evidence.opacity_chain_visible,true);
const visibleCanvas=new CanvasDouble(partiallyVisible);
assert.equal((await inspectSurface(pageFor(visibleCanvas),'canvas')).evidence.visible_canvases,1);
""")


def complete_report(scenario, mode="dom"):
    """A handwritten container transport fixture, not a game execution result."""
    manifest = artifact_manifest({}, "<html>trusted report fixture</html>", {})
    counters = scenario_counters(scenario)
    evidence = {
        **counters,
        "seed": scenario["seed"],
        "category": scenario["category"],
        "cleanup": {"manual_clock": True, "storage": True, "lifecycle": True},
        "serialized_bytes": 1 if counters["serializations"] else 0,
        "storage_faults": [],
        "lifecycle_observations": [],
    }
    for step in scenario["steps"]:
        if step["op"] == "lifecycle":
            evidence["lifecycle_observations"].append(
                {
                    "event": step["event"],
                    **(
                        {"acknowledged": True}
                        if step["event"] == "remount"
                        else {"synthetic": True, "hidden": step["event"] == "hide"}
                    ),
                }
            )
    checks = []
    for name in RUNTIME_CHECKS:
        for width in (1280, 390):
            observation = {}
            if name == "surface_size":
                observation = {
                    "presentation_mode": mode,
                    "width": 600,
                    "height": 400,
                    "tag": "canvas" if mode == "canvas" else "main",
                    "markup_elements": 3,
                    "opacity_chain_visible": True,
                    "canvas_backing_valid": mode == "canvas",
                    "visible_canvases": 0 if mode == "dom" else 1,
                }
            if name == "surface_frames":
                observation = {
                    "presentation_mode": mode,
                    "first_sha256": "a" * 64,
                    "second_sha256": "b" * 64,
                    "first_bytes": 3000,
                    "second_bytes": 4000,
                    "changed": True,
                    "sample_interval_ms": 750,
                }
            checks.append(
                check_record(
                    f"{name}:{width}",
                    "passed",
                    "Handwritten transport observation",
                    manifest,
                    check_kind="browser",
                    evidence=observation,
                )
            )
    for width in (1280, 390):
        checks.append(
            check_record(
                f"scenario:{scenario['id']}:{width}",
                "passed",
                "Handwritten scenario report",
                manifest,
                check_kind="scenario",
                scenario_id=scenario["id"],
                evidence=copy.deepcopy(evidence),
            )
        )
    return {
        "schema_version": 2,
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "artifact": manifest,
        "request_sha256": "c" * 64,
        "checks": checks,
        "errors": [],
        "warnings": [],
    }


class RequestBoundEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.scenario = validate_scenarios([lifecycle_case()])[0]
        self.report = complete_report(self.scenario)

    def checked(self, report):
        return checked_report(
            report,
            expected_manifest=self.report["artifact"],
            expected_request_sha256="c" * 64,
            scenario_ids=[self.scenario["id"]],
            expected_scenarios=[self.scenario],
            expected_runtime_contract_version=RUNTIME_CONTRACT_VERSION,
            expected_presentation_mode="dom",
        )

    def test_complete_counts_and_dom_samples_match_the_exact_request(self):
        self.assertEqual(self.checked(copy.deepcopy(self.report)), self.report)

    def test_zero_absent_partial_or_boolean_execution_counts_do_not_pass(self):
        for field in (
            "steps_completed",
            "assertions",
            "actions",
            "simulation_frames",
            "reloads",
            "resets",
            "clicks",
            "snapshots_captured",
            "imports_attempted",
            "imports_accepted",
            "imports_rejected",
            "storage_fault_changes",
        ):
            for value in (None, True, self.report["checks"][-1]["evidence"][field] + 1):
                report = copy.deepcopy(self.report)
                report["checks"][-1]["evidence"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.checked(report)
        report = copy.deepcopy(self.report)
        report["checks"][-1]["evidence"].update(steps_completed=0, assertions=0)
        with self.assertRaisesRegex(ValueError, "actual executed"):
            checked_report(report, scenario_ids=[self.scenario["id"]])

    def test_lifecycle_ack_cleanup_and_seed_cannot_be_fabricated_by_empty_success(self):
        changes = [
            lambda data: data.update(lifecycle={"hide": 1, "show": 1, "remount": 0}),
            lambda data: data.update(lifecycle_observations=[]),
            lambda data: data["lifecycle_observations"][0].update(synthetic=False),
            lambda data: data["lifecycle_observations"][2].update(acknowledged=False),
            lambda data: data.update(
                cleanup={"manual_clock": True, "storage": True, "lifecycle": False}
            ),
            lambda data: data.update(
                cleanup={"manual_clock": 1, "storage": True, "lifecycle": True}
            ),
            lambda data: data.update(seed="stale-seed"),
        ]
        for change in changes:
            report = copy.deepcopy(self.report)
            change(report["checks"][-1]["evidence"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.checked(report)

    def test_old_runtime_images_and_wrong_surface_modes_fail_instead_of_passing_legacy_canvas_slots(
        self,
    ):
        for version in (None, 1, "2", True, 2.0):
            report = copy.deepcopy(self.report)
            report["runtime_contract_version"] = version
            with (
                self.subTest(version=version),
                self.assertRaisesRegex(ValueError, "outdated runtime"),
            ):
                self.checked(report)
        for modification in (
            {"presentation_mode": "canvas"},
            {"width": 0},
            {"tag": "canvas"},
            {"markup_elements": 0},
            {"opacity_chain_visible": False},
            {"opacity_chain_visible": 1},
            {"opacity_chain_visible": None},
        ):
            report = copy.deepcopy(self.report)
            check = next(item for item in report["checks"] if item["name"] == "surface_size:1280")
            check["evidence"].update(modification)
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                self.checked(report)
        report = copy.deepcopy(self.report)
        next(item for item in report["checks"] if item["name"] == "surface_frames:1280")["name"] = (
            "canvas_frames:1280"
        )
        with self.assertRaisesRegex(ValueError, "identity"):
            self.checked(report)

    def test_frame_sample_claims_and_unexercised_storage_faults_are_rejected(self):
        for modification in (
            {"first_bytes": 0},
            {"changed": False},
            {"sample_interval_ms": 0},
            {"first_sha256": "missing"},
        ):
            report = copy.deepcopy(self.report)
            next(item for item in report["checks"] if item["name"] == "surface_frames:1280")[
                "evidence"
            ].update(modification)
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                self.checked(report)
        scenario = validate_scenarios(
            [
                case(
                    {"op": "storage_fault", "mode": "quota"},
                    {"op": "act", "action": {"type": "play"}},
                    observed(),
                    {"op": "storage_fault", "mode": "normal"},
                )
            ]
        )[0]
        report = complete_report(scenario)
        with self.assertRaisesRegex(ValueError, "storage fault intervals"):
            checked_report(report, scenario_ids=[scenario["id"]], expected_scenarios=[scenario])


if __name__ == "__main__":
    unittest.main()
