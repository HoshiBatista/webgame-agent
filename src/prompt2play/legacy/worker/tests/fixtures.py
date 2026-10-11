"""Test-only deterministic model double. Never registered by CLI or server."""

import copy
import json
import threading
from prompt2play.legacy.worker.core import Reply, ProviderError, usage_record, FILES

SOURCES = {
    "engine.js": "class GameEngine {constructor(){this.reset();}act(a){if(a.type==='pause'){this.state.paused=!this.state.paused;return true;}if(this.state.paused||this.state.status!=='playing')return false;this.state.tick++;this.state.score++;this.state.events=[{id:String(this.state.tick),type:'score',points:1}];if(this.state.score>=10)this.state.status='won';return true;}snapshot(){return JSON.parse(JSON.stringify(this.state));}reset(){this.state={status:'playing',tick:0,score:0,paused:false,events:[]};}dispose(){}}",
    "renderer.js": "class GameRenderer {constructor(c){this.canvas=c;}draw(s,t){const c=this.canvas.getContext('2d');c.fillStyle=t%2?'red':'blue';c.fillRect(0,0,20,20);}dispose(){}}",
    "audio.js": "class GameAudio {constructor(ctx,d){this.ctx=ctx;}setState(s){}handleEvents(events){}tick(){}dispose(){}}",
    "ui.js": "function mountGame(root){const e=new GameEngine();const start=document.createElement('button');start.setAttribute('data-testid','start');start.textContent='Start';root.append(start);window.__GAME_TEST__={ready:true,snapshot:()=>e.snapshot(),act:a=>e.act(a),reset:o=>e.reset(o),setManualMode:()=>{},advance:()=>false};return {dispose(){e.dispose();}};}",
}


def fixture_plan(mode="turn_based"):
    """A small valid protocol spec, NOT an authored game or quality benchmark."""
    event_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "type": {"const": "score"},
            "points": {"type": "integer"},
        },
        "required": ["id", "type", "points"],
        "additionalProperties": False,
    }
    contract = {
        "version": 3,
        "timing": {
            "mode": mode,
            "step_action": json.dumps({"type": "step", "dt": 1 / 60})
            if mode == "fixed_step"
            else "{}",
            "step_seconds": 1 / 60 if mode == "fixed_step" else 0,
            "max_catchup_steps": 6 if mode == "fixed_step" else 0,
            "pause_policy": "Paused state rejects progress; reset creates a fresh run; hidden time is discarded.",
        },
        "fields": [
            {
                "id": "tick",
                "path": "/tick",
                "type": "integer",
                "unit": "simulation steps" if mode == "fixed_step" else "turns",
                "meaning": "Accepted progress actions since reset",
                "owner": "engine.js",
                "consumers": ["ui.js"],
                "example_json": "1",
            },
            {
                "id": "score",
                "path": "/score",
                "type": "integer",
                "unit": "points",
                "meaning": "Earned game points",
                "owner": "engine.js",
                "consumers": ["ui.js", "renderer.js"],
                "example_json": "1",
            },
        ],
        "events": [
            {
                "type": "score",
                "payload_schema": json.dumps(event_schema),
                "example_json": '{"id":"1","type":"score","points":1}',
                "delivery": "Latest real event retained in snapshots; id unique per run; consumers deduplicate.",
                "owner": "engine.js",
                "consumers": ["audio.js", "ui.js"],
            }
        ],
        "state_machines": [
            {
                "id": "run",
                "owner": "engine.js",
                "states": ["playing", "won", "lost"],
                "initial_state": "playing",
                "terminal_states": ["won", "lost"],
                "transitions": [
                    {
                        "from": "playing",
                        "to": "won",
                        "trigger": "score reaches ten",
                        "effect": "stop accepting progress once",
                    }
                ],
            }
        ],
        "resources": [
            {
                "name": "raf",
                "owner": "ui.js",
                "acquire": "mount creates one loop",
                "release": "dispose cancels it",
                "stale_work_policy": "Session identity rejects callbacks after disposal",
            }
        ],
        "invariants": [
            {
                "id": "nonnegative-score",
                "statement": "Score cannot become negative",
                "owners": ["engine.js", "ui.js"],
                "check_strategy": "Real progress increases score; a reset returns it to zero.",
            }
        ],
    }
    contract.update(
        state_domains=[
            {
                "id": "attempt-data",
                "owner": "engine.js",
                "field_ids": ["tick", "score"],
                "lifetime": "attempt",
                "reset_policy": "New run resets score and accepted step count to zero",
                "preserve_policy": "Pause and repeated snapshots preserve both values",
            }
        ],
        transactions=[],
        progression=[],
        persistence=[],
        first_playable_loop={
            "description": "One accepted wait earns a point visible to the player",
            "scenario_id": "progress",
        },
    )
    scenarios = [
        {
            "id": "progress",
            "purpose": "Protocol fixture: one real action earns a point",
            "category": "progress",
            "seed": "fixture",
            "steps": [
                json.dumps(x)
                for x in [
                    {"op": "capture", "key": "before"},
                    {"op": "act", "action": {"type": "wait"}},
                    {
                        "op": "assert",
                        "left": {"path": "/score"},
                        "cmp": "gt",
                        "right": {"saved": "before", "path": "/score"},
                    },
                ]
            ],
            "affected_files": ["engine.js", "ui.js"],
            "limitations": ["Test-only fixture; no generated-game quality claim"],
        },
        {
            "id": "restart",
            "purpose": "Protocol fixture: restart clears earned score",
            "category": "lifecycle",
            "seed": "fixture",
            "steps": [
                json.dumps(x)
                for x in [
                    {"op": "act", "action": {"type": "wait"}},
                    {"op": "reset", "seed": "fixture"},
                    {
                        "op": "assert",
                        "left": {"path": "/score"},
                        "cmp": "eq",
                        "right": {"value": 0},
                    },
                ]
            ],
            "affected_files": ["engine.js", "ui.js"],
            "limitations": ["Reset only; no full browser lifecycle coverage"],
        },
    ]
    return dict(
        title="Fixture game",
        summary="Only for automated pipeline tests",
        genre="test",
        rules=["earn points"],
        state_schema='{"status":"playing|won|lost","tick":"integer","score":"integer"}',
        action_schema='{"type":"wait|step|pause"}',
        event_schema=json.dumps(event_schema),
        visual_direction="test",
        audio_direction="test",
        controls=["wait"],
        win_condition="ten points",
        lose_condition="test-only",
        smoke_actions=['{"type":"wait"}'],
        affected_files=list(FILES),
        acceptance_criteria=["A point is earned by a real action"],
        semantic_contract=contract,
        qa_scenarios=scenarios,
    )


PLAN = fixture_plan()


def fixture_issue(
    file="engine.js", *, scope="local", affected_files=None, contract_ids=None, scenario="progress"
):
    return {
        "file": file,
        "severity": "error",
        "message": "Fixture injected defect",
        "scope": scope,
        "affected_files": affected_files or [file],
        "contract_ids": contract_ids or [],
        "reproduction": "Fixture-only controlled review sequence",
        "expected": "Recorded expected result",
        "observed": "Recorded fixture defect",
        "regression_scenario_id": scenario,
    }


class FixtureProvider:
    name = "fixture-tests-only"

    def __init__(self, *, affected=None, invalid_engine_once=False, fail_once=None):
        self.calls = []
        self.lock = threading.Lock()
        self.affected = affected
        self.invalid = invalid_engine_once
        self.fail_once = fail_once

    def generate(self, prompt, schema, role, cancel, max_output=0, model=""):
        with self.lock:
            self.calls.append(role)
            count = self.calls.count(role)
        if role == self.fail_once and count == 1:
            raise ProviderError("Synthetic interrupted call")
        if role == "plan":
            data = copy.deepcopy(PLAN)
            if self.affected is not None:
                data["affected_files"] = self.affected
        elif role == "review":
            data = {
                "approved": True,
                "summary": "Fixture review, not a quality claim",
                "issues": [],
            }
        else:
            data = {
                "source": "class GameEngine {"
                if role == "engine" and self.invalid and count == 1
                else SOURCES[role + ".js"],
                "summary": role,
            }
        return Reply(
            data,
            usage_record({"input_tokens": 100, "cached_input_tokens": 25, "output_tokens": 100}),
        )
