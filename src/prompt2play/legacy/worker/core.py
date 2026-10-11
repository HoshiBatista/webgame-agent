"""Provider-independent contracts, bounded accounting, and cancellation."""

from __future__ import annotations
import copy
import json
import math
import re
import threading
from dataclasses import dataclass, field as dataclass_field

FILES = ("engine.js", "renderer.js", "audio.js", "ui.js")
ROLES = ("engine", "renderer", "audio", "ui")
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "calls")
PROMPT_BOUNDARY = "\n--- END OF STABLE CONTRACT; DYNAMIC TASK DATA FOLLOWS ---\n"


class Cancelled(Exception):
    pass


class LeaseLost(Cancelled):
    pass


class BudgetExceeded(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, message, *, usage=None):
        super().__init__(message)
        # A rejected structured answer can still have known billable usage.
        self.usage = usage


def empty_usage():
    return dict.fromkeys(USAGE_KEYS, 0)


def usage_record(raw=None):
    if not isinstance(raw, dict) or any(
        type(raw.get(key)) is not int or raw[key] < 0 for key in ("input_tokens", "output_tokens")
    ):
        raise ProviderError("Provider did not report valid usage; request spend is unknown")
    inp, out = raw["input_tokens"], raw["output_tokens"]
    details = raw.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        raise ProviderError("Provider reported malformed cached-token usage")
    cached = raw.get("cached_input_tokens", details.get("cached_tokens", 0)) or 0
    if type(cached) is not int or cached < 0:
        raise ProviderError("Provider reported malformed cached-token usage")
    return dict(
        input_tokens=inp,
        cached_input_tokens=min(inp, max(0, int(cached))),
        output_tokens=out,
        total_tokens=inp + out,
        calls=1,
    )


def check_cancel(event):
    if event.is_set():
        raise Cancelled("Job cancelled or lease lost")


@dataclass
class Reply:
    data: dict
    usage: dict = dataclass_field(default_factory=empty_usage)


class Budget:
    """Conservative UTF-8 upper-bound reservations; cached tokens still count.

    Successful calls use reported tokens. Unknown/failed request usage retains its
    reservation, so retries/restarts cannot turn unknown spend into free budget.
    """

    def __init__(self, limit, usage=None, uncertain=0, reserved=None):
        self.limit = int(limit)
        self.usage = {**empty_usage(), **(usage or {})}
        self.uncertain = int(uncertain) + sum((reserved or {}).values())
        self.reserved = {}
        self.lock = threading.RLock()

    @staticmethod
    def estimate(prompt, output):
        return len(prompt.encode("utf-8")) + int(output) + 1024

    def reserve_many(self, entries):
        with self.lock:
            needed = sum(entries.values())
            committed = self.usage["total_tokens"] + self.uncertain + sum(self.reserved.values())
            if committed + needed > self.limit:
                raise BudgetExceeded(
                    f"Token budget cannot reserve the next calls: conservative reservation {needed}, "
                    f"available {max(0, self.limit - committed)}, required total budget at least {committed + needed}. "
                    "This is a reservation estimate, not measured spend; increase budget or narrow the request"
                )
            if set(entries) & self.reserved.keys():
                raise RuntimeError("Duplicate budget reservation")
            self.reserved.update(entries)

    def settle(self, key, usage):
        with self.lock:
            amount = self.reserved.pop(key)
            if usage is None:
                self.uncertain += amount
            else:
                for k in USAGE_KEYS:
                    self.usage[k] += int(usage.get(k, 0))
            if self.usage["total_tokens"] + self.uncertain > self.limit:
                raise BudgetExceeded("Provider usage exceeded the reserved token budget")

    def snapshot(self):
        with self.lock:
            return {
                "usage": dict(self.usage),
                "uncertain": self.uncertain,
                "reserved": dict(self.reserved),
            }


def obj(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


STR = {"type": "string"}
STRINGS = {"type": "array", "items": STR}
FILE = {"type": "string", "enum": list(FILES)}
FILE_LIST = {"type": "array", "items": FILE}
PRESENTATION_MODE = {"type": "string", "enum": ["canvas", "dom", "hybrid"]}
REVIEW_OBLIGATION_KINDS = (
    "decision_protocol",
    "information_boundary",
    "alternative_choice",
    "deferred_task",
    "durable_conflict",
    "focus",
    "async_audio",
)
REVIEW_OBLIGATION_SCHEMA = obj(
    {
        "id": STR,
        "kind": {"type": "string", "enum": list(REVIEW_OBLIGATION_KINDS)},
        "owners": FILE_LIST,
        "contract_ids": STRINGS,
        "scenario_ids": STRINGS,
        "limitations": STRINGS,
    }
)

LEGACY_SEMANTIC_CONTRACT_SCHEMA = obj(
    {
        "version": {"type": "integer", "enum": [2]},
        "timing": obj(
            {
                "mode": {"type": "string", "enum": ["turn_based", "fixed_step"]},
                "step_action": STR,
                "step_seconds": {"type": "number"},
                "max_catchup_steps": {"type": "integer"},
                "pause_policy": STR,
            }
        ),
        "fields": {
            "type": "array",
            "items": obj(
                {
                    "id": STR,
                    "path": STR,
                    "type": {
                        "type": "string",
                        "enum": [
                            "string",
                            "number",
                            "integer",
                            "boolean",
                            "object",
                            "array",
                            "null",
                        ],
                    },
                    "unit": STR,
                    "meaning": STR,
                    "owner": FILE,
                    "consumers": FILE_LIST,
                    "example_json": STR,
                }
            ),
        },
        "events": {
            "type": "array",
            "items": obj(
                {
                    "type": STR,
                    "payload_schema": STR,
                    "example_json": STR,
                    "delivery": STR,
                    "owner": FILE,
                    "consumers": FILE_LIST,
                }
            ),
        },
        "state_machines": {
            "type": "array",
            "items": obj(
                {
                    "id": STR,
                    "owner": FILE,
                    "states": STRINGS,
                    "initial_state": STR,
                    "terminal_states": STRINGS,
                    "transitions": {
                        "type": "array",
                        "items": obj(
                            {
                                "from": STR,
                                "to": STR,
                                "trigger": STR,
                                "effect": STR,
                            }
                        ),
                    },
                }
            ),
        },
        "resources": {
            "type": "array",
            "items": obj(
                {
                    "name": STR,
                    "owner": FILE,
                    "acquire": STR,
                    "release": STR,
                    "stale_work_policy": STR,
                }
            ),
        },
        "invariants": {
            "type": "array",
            "items": obj(
                {
                    "id": STR,
                    "statement": STR,
                    "owners": FILE_LIST,
                    "check_strategy": STR,
                }
            ),
        },
    }
)

# v2 remains readable for historical artifacts. Every newly planned game uses v3;
# optional mechanics are empty arrays, not a mandatory campaign/save template.
SEMANTIC_CONTRACT_SCHEMA = obj(
    {
        **LEGACY_SEMANTIC_CONTRACT_SCHEMA["properties"],
        "version": {"type": "integer", "enum": [3]},
        "state_domains": {
            "type": "array",
            "items": obj(
                {
                    "id": STR,
                    "owner": FILE,
                    "field_ids": STRINGS,
                    "lifetime": {
                        "type": "string",
                        "enum": ["action", "phase", "attempt", "session", "persistent", "derived"],
                    },
                    "reset_policy": STR,
                    "preserve_policy": STR,
                }
            ),
        },
        "transactions": {
            "type": "array",
            "items": obj(
                {
                    "id": STR,
                    "owner": FILE,
                    "action_json": STR,
                    "domain_ids": STRINGS,
                    "preconditions": STRINGS,
                    "commit": STRINGS,
                    "rejection_policy": STR,
                    "repeat_policy": STR,
                    "scenario_ids": STRINGS,
                }
            ),
        },
        "progression": {
            "type": "array",
            "items": obj(
                {
                    "id": STR,
                    "owner": FILE,
                    "source_field_id": STR,
                    "unit": STR,
                    "starts_when": STR,
                    "completion": STR,
                    "prerequisites": STRINGS,
                    "reward_policy": STR,
                    "scenario_ids": STRINGS,
                }
            ),
        },
        "persistence": {
            "type": "array",
            "items": obj(
                {
                    "id": STR,
                    "owner": FILE,
                    "domain_ids": STRINGS,
                    "storage": {"type": "string", "enum": ["local_storage", "export_only"]},
                    "format_version": STR,
                    "validation_rules": STRINGS,
                    "migration_policy": STR,
                    "write_policy": STR,
                    "conflict_policy": STR,
                    "failure_policy": STR,
                    "scenario_ids": STRINGS,
                }
            ),
        },
        "first_playable_loop": obj({"description": STR, "scenario_id": STR}),
    }
)
# Optional extensions retain readable v3 artifacts and selective revisions.
# The live-provider output schema below requires explicit [] and presentation
# mode, while the historical/declaration schema keeps their previous defaults.
SEMANTIC_CONTRACT_SCHEMA["properties"]["review_obligations"] = {
    "type": "array",
    "items": REVIEW_OBLIGATION_SCHEMA,
    "maxItems": 8,
}

QA_SCENARIO_SCHEMA = obj(
    {
        "id": STR,
        "purpose": STR,
        "category": {
            "type": "string",
            "enum": [
                "progress",
                "lifecycle",
                "accounting",
                "strategy",
                "integration",
                "persistence",
            ],
        },
        "seed": STR,
        "steps": STRINGS,
        "affected_files": FILE_LIST,
        "limitations": STRINGS,
    }
)

PLAN_SCHEMA = obj(
    {
        "title": STR,
        "summary": STR,
        "genre": STR,
        "rules": STRINGS,
        "state_schema": STR,
        "action_schema": STR,
        "event_schema": STR,
        "visual_direction": STR,
        "audio_direction": STR,
        "controls": STRINGS,
        "win_condition": STR,
        "lose_condition": STR,
        "smoke_actions": {"type": "array", "items": STR},
        "affected_files": FILE_LIST,
        "acceptance_criteria": STRINGS,
        "semantic_contract": SEMANTIC_CONTRACT_SCHEMA,
        "qa_scenarios": {"type": "array", "items": QA_SCENARIO_SCHEMA},
    }
)
PLAN_SCHEMA["properties"]["presentation_mode"] = PRESENTATION_MODE

# All object properties must be required in a strict provider response. Keep
# this distinct from historical validation rather than silently upgrading saved
# games, or making every existing v3 fixture acquire new mechanics/interfaces.
PLAN_OUTPUT_SCHEMA = copy.deepcopy(PLAN_SCHEMA)
PLAN_OUTPUT_SCHEMA["required"].append("presentation_mode")
PLAN_OUTPUT_SCHEMA["properties"]["semantic_contract"]["required"].append("review_obligations")
COMPONENT_SCHEMA = obj({"source": STR, "summary": STR})
REVIEW_SCHEMA = obj(
    {
        "approved": {"type": "boolean"},
        "summary": STR,
        "issues": {
            "type": "array",
            "items": obj(
                {
                    "file": FILE,
                    "severity": {"type": "string", "enum": ["error", "warning"]},
                    "message": STR,
                    "scope": {"type": "string", "enum": ["local", "integration", "contract"]},
                    "affected_files": FILE_LIST,
                    "contract_ids": STRINGS,
                    "reproduction": STR,
                    "expected": STR,
                    "observed": STR,
                    "regression_scenario_id": STR,
                }
            ),
        },
    }
)


def stable_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def presentation_mode(spec):
    """Historical v3 and earlier plans used a canvas without a mode field."""
    return spec.get("presentation_mode", "canvas")


def contract_entries(contract):
    """Stable semantic identifiers and their module dependency sets."""
    entries = {"timing": {"engine.js", "ui.js"}}
    for item in contract.get("fields", []):
        entries[item["id"]] = {item["owner"], *item["consumers"]}
    for item in contract.get("events", []):
        entries["event:" + item["type"]] = {item["owner"], *item["consumers"]}
    for item in contract.get("state_machines", []):
        entries[item["id"]] = {item["owner"]}
    for item in contract.get("resources", []):
        entries["resource:" + item["name"]] = {item["owner"]}
    for item in contract.get("invariants", []):
        entries[item["id"]] = set(item["owners"])
    for item in contract.get("state_domains", []):
        entries[item["id"]] = {item["owner"]}.union(
            *(entries.get(field, set()) for field in item["field_ids"])
        )
    for item in contract.get("progression", []):
        entries[item["id"]] = {item["owner"]} | entries.get(item["source_field_id"], set())
    for collection in ("transactions", "persistence"):
        for item in contract.get(collection, []):
            entries[item["id"]] = {item["owner"]}.union(
                *(entries.get(domain, set()) for domain in item["domain_ids"])
            )
    # Obligations may reference ordinary contracts, never one another. Resolve
    # them from a fixed baseline so list order cannot change dependencies.
    base_entries = dict(entries)
    for item in contract.get("review_obligations", []):
        entries[item["id"]] = set(item["owners"]).union(
            *(base_entries.get(key, set()) for key in item["contract_ids"])
        )
    return entries


def contract_declarations(contract):
    """Canonical declarations used to select actual revision dependencies."""
    data = {"timing": contract["timing"]}
    for collection, key, prefix in (
        ("fields", "id", ""),
        ("events", "type", "event:"),
        ("state_machines", "id", ""),
        ("resources", "name", "resource:"),
        ("invariants", "id", ""),
        ("state_domains", "id", ""),
        ("transactions", "id", ""),
        ("progression", "id", ""),
        ("persistence", "id", ""),
        ("review_obligations", "id", ""),
    ):
        data.update({prefix + item[key]: item for item in contract.get(collection, [])})
    return data


def validate_semantic_contract(contract):
    """Validate declarations before authors spend tokens, without running JS.

    Examples and ownership can be checked structurally; prose invariants still
    need executable scenarios/model review and do not become proven here.
    """
    import jsonschema

    try:
        schema = (
            LEGACY_SEMANTIC_CONTRACT_SCHEMA
            if isinstance(contract, dict) and contract.get("version") == 2
            else SEMANTIC_CONTRACT_SCHEMA
        )
        jsonschema.validate(contract, schema)
    except (jsonschema.ValidationError, TypeError) as exc:
        raise ProviderError("Planner semantic_contract has an invalid structure") from exc
    try:
        contract_bytes = len(stable_json(contract).encode())
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise ProviderError("Planner semantic contract must contain finite bounded JSON") from exc
    if contract_bytes > 64_000:
        raise ProviderError("Planner semantic contract exceeds 64 KB")

    def json_value(text, label):
        try:
            value = json.loads(
                text, parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant))
            )
            # JSON's decimal syntax can overflow the host number type without
            # invoking parse_constant (for example 1e999). Validate the decoded
            # value as well as its syntax before giving the contract to authors.
            stable_json(value).encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
            raise ProviderError(label + " must contain valid finite JSON") from exc
        return value

    timing = contract["timing"]
    step_action = json_value(timing["step_action"], "timing.step_action")
    if not isinstance(step_action, dict):
        raise ProviderError("timing.step_action must encode a JSON action object")
    seconds = timing["step_seconds"]
    if not math.isfinite(seconds):
        raise ProviderError("timing.step_seconds must be finite")
    if timing["mode"] == "fixed_step":
        if (
            not 0 < seconds <= 0.1
            or not isinstance(step_action.get("type"), str)
            or not step_action["type"]
        ):
            raise ProviderError(
                "Fixed-step timing needs a named action and a step of at most 0.1 seconds"
            )
        if (
            type(timing["max_catchup_steps"]) is not int
            or not 1 <= timing["max_catchup_steps"] <= 12
        ):
            raise ProviderError("Fixed-step max_catchup_steps must be from 1 through 12")
    elif seconds != 0 or timing["max_catchup_steps"] != 0 or step_action:
        raise ProviderError(
            "Turn-based timing uses step_action {}, zero seconds and zero catch-up steps"
        )
    if not timing["pause_policy"].strip():
        raise ProviderError("Timing must state what pauses and how hidden-tab time is discarded")
    for name, limit in (
        ("fields", 48),
        ("events", 24),
        ("state_machines", 8),
        ("resources", 16),
        ("invariants", 24),
    ):
        if not contract[name] or len(contract[name]) > limit:
            raise ProviderError(f"Semantic {name} requires 1 through {limit} entries")
    identifiers = {"timing"}

    def identifier(value):
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}", value)
            or value in identifiers
        ):
            raise ProviderError("Semantic contract identifiers must be unique bounded names")
        identifiers.add(value)

    def owners(values, allow_empty=False):
        if (not values and not allow_empty) or len(values) != len(set(values)):
            raise ProviderError(
                "Semantic dependency lists must be nonempty and contain no duplicates"
            )

    for field in contract["fields"]:
        identifier(field["id"])
        if (
            not field["path"].startswith("/")
            or not field["unit"].strip()
            or not field["meaning"].strip()
        ):
            raise ProviderError("Shared fields require a /path, explicit unit and meaning")
        owners(field["consumers"], allow_empty=True)
        value = json_value(field["example_json"], "Field example")
        try:
            jsonschema.validate(value, {"type": field["type"]})
        except jsonschema.ValidationError as exc:
            raise ProviderError("Shared field example does not match its declared type") from exc
    for event in contract["events"]:
        identifier("event:" + event["type"])
        owners(event["consumers"], allow_empty=True)
        schema = json_value(event["payload_schema"], "Event payload schema")
        example = json_value(event["example_json"], "Event example")
        if (
            not isinstance(schema, dict)
            or not isinstance(example, dict)
            or example.get("type") != event["type"]
            or not isinstance(example.get("id"), str)
        ):
            raise ProviderError(
                "Events require an object schema and an example with matching type and string id"
            )
        if event["owner"] != "engine.js" or not event["delivery"].strip():
            raise ProviderError(
                "Engine owns gameplay events; delivery and deduplication must be specified"
            )
        pending = [schema]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if {"$ref", "$dynamicRef", "$recursiveRef"} & node.keys():
                    raise ProviderError(
                        "Event payload schemas must be self-contained without schema references"
                    )
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(example)
        except (jsonschema.SchemaError, jsonschema.ValidationError) as exc:
            raise ProviderError(
                "Event example does not match its valid payload JSON Schema"
            ) from exc
    for machine in contract["state_machines"]:
        identifier(machine["id"])
        states = machine["states"]
        if (
            not states
            or len(states) > 16
            or len(states) != len(set(states))
            or machine["initial_state"] not in states
        ):
            raise ProviderError("State machines require unique states and a declared initial state")
        if not set(machine["terminal_states"]).issubset(states) or len(
            machine["terminal_states"]
        ) != len(set(machine["terminal_states"])):
            raise ProviderError("State machine terminal states must be declared")
        if not machine["transitions"] or len(machine["transitions"]) > 32:
            raise ProviderError("State machines require a bounded transition list")
        for transition in machine["transitions"]:
            if (
                transition["from"] not in states
                or transition["to"] not in states
                or not transition["trigger"].strip()
                or not transition["effect"].strip()
            ):
                raise ProviderError(
                    "Transitions need known states, a trigger and its exact side effects"
                )
            if transition["from"] in machine["terminal_states"]:
                raise ProviderError(
                    "Terminal states cannot transition in the same entity/session; reset creates a new instance"
                )
    for resource in contract["resources"]:
        identifier("resource:" + resource["name"])
        if any(not resource[key].strip() for key in ("acquire", "release", "stale_work_policy")):
            raise ProviderError("Each resource needs acquisition, release and stale-work policy")
    for invariant in contract["invariants"]:
        identifier(invariant["id"])
        owners(invariant["owners"])
        if not invariant["statement"].strip() or not invariant["check_strategy"].strip():
            raise ProviderError("Each invariant needs an observable statement and check strategy")
    if contract["version"] == 3:
        from .semantics import validate_lifetimes, validate_review_obligations

        validate_lifetimes(contract, identifier)
        validate_review_obligations(contract, identifier)
    return contract


def validate_review(review, plan):
    import jsonschema

    try:
        jsonschema.validate(review, REVIEW_SCHEMA)
    except (jsonschema.ValidationError, TypeError) as exc:
        raise ProviderError("Reviewer returned an invalid issue structure") from exc
    if len(review["issues"]) > 32 or len(stable_json(review).encode()) > 64_000:
        raise ProviderError("Reviewer issue report exceeds its bounded size")
    if len(review["summary"]) > 6000:
        raise ProviderError("Reviewer summary exceeds 6000 characters")
    if not review["approved"] and not any(
        issue["severity"] == "error" for issue in review["issues"]
    ):
        raise ProviderError(
            "An unapproved review must identify at least one actionable blocking issue"
        )
    contracts = contract_entries(plan["semantic_contract"])
    scenarios = {scenario["id"] for scenario in plan["qa_scenarios"]}
    for issue in review["issues"]:
        if not issue["message"].strip() or any(
            len(issue[key]) > 4000 for key in ("message", "reproduction", "expected", "observed")
        ):
            raise ProviderError("Review issue descriptions must be bounded to 4000 characters")
        if len(issue["contract_ids"]) > 50 or len(issue["contract_ids"]) != len(
            set(issue["contract_ids"])
        ):
            raise ProviderError("Review semantic references must be unique and bounded")
        files = issue["affected_files"]
        if not files or issue["file"] not in files or len(files) != len(set(files)):
            raise ProviderError(
                "Review issue must name its primary file within unique affected_files"
            )
        if issue["scope"] == "local" and len(files) != 1:
            raise ProviderError("Local review issue must affect exactly one file")
        if not set(issue["contract_ids"]).issubset(contracts):
            raise ProviderError("Review issue references an unknown semantic contract id")
        if issue["scope"] == "contract" and not issue["contract_ids"]:
            raise ProviderError(
                "Contract repair must identify the frozen semantic contracts to align"
            )
        if issue["regression_scenario_id"] and issue["regression_scenario_id"] not in scenarios:
            raise ProviderError("Reviewer cannot claim an unknown executable regression scenario")
        if issue["severity"] == "error" and any(
            not issue[key].strip() for key in ("message", "reproduction", "expected", "observed")
        ):
            raise ProviderError(
                "Blocking review issues require observable reproduction, expected and observed behavior"
            )
    return review
