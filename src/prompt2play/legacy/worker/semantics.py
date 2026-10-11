"""Cross-field and QA obligations learned from multi-session games.

This validates declarations and evidence bindings, not the truth of prose or fun.
Only the bounded scenario interpreter can produce execution evidence.
"""

from __future__ import annotations
import json
from .core import ProviderError, stable_json, contract_entries


# Trusted process guidance, selected by explicit, validated declarations. Never
# infer features from a genre label or paste example game code into every role.
REVIEW_OBLIGATION_GUIDANCE = {
    "decision_protocol": [
        "Name the decision owner and legal choices in each phase, including voluntary alternatives and system settlement.",
        "Commit rule/accounting transitions once; display delays cannot own rules. Distinguish legal actions, policy liveness and terminal reachability.",
    ],
    "information_boundary": [
        "Give each human/bot only its declared observer view and legal actions; copy the view and exclude hidden data from DOM, events and histories.",
        "A full-state rule oracle is privileged test evidence, not permission for a bot or UI to inspect opponents or future randomness.",
    ],
    "alternative_choice": [
        "Exercise legal human choices omitted by the usual bot policy, with independent expected consequences and no fabricated state.",
        "Different commands are only declared coverage: legality, comparable decision states and meaningful branch effects still need execution/review.",
    ],
    "deferred_task": [
        "Fence pending work by session, state revision and independently invalidated task ticket; check before clearing the live timer handle.",
        "Cancel/reschedule at unchanged state, pause all mutation entry points, and distinguish reinitialization from restoring transient old UI state.",
    ],
    "durable_conflict": [
        "Compare the actual durable envelope to the observed baseline before every write; equal revision numbers do not identify the same branch.",
        "Reread storage on notification/return, keep divergent live progress and truthful status, and require an explicit replace decision. This is not atomic cross-tab CAS.",
    ],
    "focus": [
        "Keep selection, focused control identity and original modal return target separate; preserve them appropriately across DOM updates.",
        "Native Enter/Space activates the focused control, never a different previously selected item. Check mixed keyboard/pointer/modal sequences.",
    ],
    "async_audio": [
        "Cancel/disconnect one-shot sources and their complete gain/filter chains on mute/hide; discard events until the context is running.",
        "Reconcile completion of both resume and suspend against current desired state, visibility and instance identity; no stale promise or resume backlog.",
    ],
}


def validate_review_obligations(contract, identifier):
    """Bound an optional review scope; it never certifies source behavior."""
    obligations = contract.get("review_obligations", [])
    obligation_ids = {item["id"] for item in obligations}
    entries = {
        key: owners
        for key, owners in contract_entries(contract).items()
        if key not in obligation_ids
    }
    for item in obligations:
        identifier(item["id"])
        _references(item["contract_ids"], entries, "Review obligation contracts", maximum=12)
        dependencies = set().union(*(entries[key] for key in item["contract_ids"]))
        _references(item["owners"], dependencies, "Review obligation owners", maximum=4)
        if len(item["limitations"]) > 4:
            raise ProviderError("Review obligation limitations require at most four entries")
        for limitation in item["limitations"]:
            _nonempty(limitation, "Review obligation limitation")
            if len(limitation) > 600:
                raise ProviderError("Review obligation limitation exceeds 600 characters")
        if not item["scenario_ids"] and not item["limitations"]:
            raise ProviderError(
                "Review-only obligations must explain why execution evidence is not declared"
            )
        if item["kind"] == "durable_conflict" and not any(
            saved["id"] in item["contract_ids"] and saved["storage"] == "local_storage"
            for saved in contract["persistence"]
        ):
            raise ProviderError(
                "Durable conflict obligations require a referenced local_storage contract"
            )


def review_obligation_context(contract, filename=None):
    """Stable, role-scoped guidance; source/evidence stays in the dynamic tail."""
    entries = contract_entries(contract)
    selected = [
        item
        for item in contract.get("review_obligations", [])
        if filename is None or filename in entries[item["id"]]
    ]
    if not selected:
        return None
    kinds = sorted({item["kind"] for item in selected})
    return {
        "status": "declared",
        "obligation_ids": [item["id"] for item in selected],
        "guidance": [{"kind": kind, "checks": REVIEW_OBLIGATION_GUIDANCE[kind]} for kind in kinds],
        "limitation": "Review focus and scenario bindings, not executed tests or a model approval result",
    }


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ProviderError(label + " must be explicit")


def _references(values, known, label, *, empty=False, maximum=24):
    if (
        (not values and not empty)
        or len(values) > maximum
        or len(values) != len(set(values))
        or not set(values).issubset(known)
    ):
        raise ProviderError(label + " must contain unique known references within its bound")


def validate_lifetimes(contract, identifier):
    fields = {field["id"]: field for field in contract["fields"]}
    for collection, minimum, maximum in (
        ("state_domains", 1, 16),
        ("transactions", 0, 12),
        ("progression", 0, 16),
        ("persistence", 0, 1),
    ):
        if not minimum <= len(contract[collection]) <= maximum:
            raise ProviderError(
                f"Semantic {collection} requires {minimum} through {maximum} entries"
            )
        for item in contract[collection]:
            identifier(item["id"])
    domains = {item["id"]: item for item in contract["state_domains"]}
    assigned = []
    for domain in domains.values():
        _references(domain["field_ids"], fields, "Domain fields", maximum=48)
        if any(fields[name]["owner"] != domain["owner"] for name in domain["field_ids"]):
            raise ProviderError(
                "A state domain must have the same authoritative owner as its fields"
            )
        for policy in ("reset_policy", "preserve_policy"):
            _nonempty(domain[policy], "Domain " + policy)
        assigned.extend(domain["field_ids"])
    if len(assigned) != len(set(assigned)) or set(assigned) != set(fields):
        raise ProviderError("Every declared shared field must belong to exactly one state domain")
    for transaction in contract["transactions"]:
        _references(transaction["domain_ids"], domains, "Transaction domains", maximum=16)
        if any(
            domains[name]["owner"] != transaction["owner"] for name in transaction["domain_ids"]
        ):
            raise ProviderError("A transaction must own all of its atomic state domains")
        try:
            action = json.loads(
                transaction["action_json"],
                parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
            )
            if (
                not isinstance(action, dict)
                or not action
                or len(stable_json(action).encode()) > 4096
            ):
                raise ValueError()
        except (ValueError, TypeError, RecursionError) as exc:
            raise ProviderError(
                "Transaction action_json must encode a bounded finite action object"
            ) from exc
        for policy in ("rejection_policy", "repeat_policy"):
            _nonempty(transaction[policy], "Transaction " + policy)
        for entries in ("preconditions", "commit"):
            if not 1 <= len(transaction[entries]) <= 16:
                raise ProviderError(
                    "Transaction conditions and effects must be nonempty and bounded"
                )
            for text in transaction[entries]:
                _nonempty(text, "Transaction " + entries)
    goals = {goal["id"]: goal for goal in contract["progression"]}
    for goal in goals.values():
        if (
            goal["source_field_id"] not in fields
            or fields[goal["source_field_id"]]["owner"] != goal["owner"]
        ):
            raise ProviderError("Progression needs a declared authoritative source field")
        for key in ("unit", "starts_when", "completion", "reward_policy"):
            _nonempty(goal[key], "Progression " + key)
        _references(
            goal["prerequisites"], goals, "Progression prerequisites", empty=True, maximum=16
        )
    # Prerequisites express unlock dependencies, not repeatable runtime phases.
    seen, visiting = set(), set()

    def visit(name):
        if name in visiting:
            raise ProviderError("Progression prerequisites contain an unreachable dependency cycle")
        if name in seen:
            return
        visiting.add(name)
        for prerequisite in goals[name]["prerequisites"]:
            visit(prerequisite)
        visiting.remove(name)
        seen.add(name)

    for name in goals:
        visit(name)
    for persistence in contract["persistence"]:
        _references(persistence["domain_ids"], domains, "Persistence domains", maximum=16)
        for key in (
            "format_version",
            "migration_policy",
            "write_policy",
            "conflict_policy",
            "failure_policy",
        ):
            _nonempty(persistence[key], "Persistence " + key)
        if not 1 <= len(persistence["validation_rules"]) <= 16:
            raise ProviderError(
                "Persistence needs bounded semantic validation rules, not just a JSON shape"
            )
        for rule in persistence["validation_rules"]:
            _nonempty(rule, "Persistence validation rule")
    _nonempty(contract["first_playable_loop"]["description"], "First playable loop")


def _operand_leaves(value):
    """Walk only the closed operand grammar: literal JSON is never code/paths."""
    if not isinstance(value, dict) or "value" in value:
        return
    if "path" in value or "element" in value:
        yield value
    elif "sum" in value:
        for item in value["sum"]:
            yield from _operand_leaves(item)
    elif "count" in value:
        yield from _operand_leaves(value["count"])


def _meaningful(step):
    if (
        step["op"] != "assert"
        or step.get("cmp") == "exists"
        or step.get("left") == step.get("right")
    ):
        return False
    return any(
        "saved" not in value
        for side in ("left", "right")
        for value in _operand_leaves(step.get(side))
    )


def _tokens(path):
    return (
        []
        if path == ""
        else [token.replace("~1", "/").replace("~0", "~") for token in path[1:].split("/")]
    )


def _overlaps(path, declared):
    actual, field = _tokens(path), _tokens(declared)
    return all(a == b or b == "*" for a, b in zip(actual, field))


def _observed_domains(step, contract):
    if not _meaningful(step):
        return set()
    paths = [
        value["path"]
        for side in ("left", "right")
        for value in _operand_leaves(step.get(side))
        if "path" in value and "saved" not in value
    ]
    fields = {field["id"]: field["path"] for field in contract["fields"]}
    return {
        domain["id"]
        for domain in contract["state_domains"]
        if any(_overlaps(path, fields[field]) for path in paths for field in domain["field_ids"])
    }


def _has_observed_comparison(steps, start=0):
    return any(_meaningful(step) for step in steps[start:])


OBSERVATION_OPS = {"assert", "capture", "serialize"}
PLAY_OPS = {"act", "click", "advance", "key"}


def _play_observations(steps):
    """Observe actual play within its state interval, not a later reset/import."""
    played = False
    for step in steps:
        if step["op"] in PLAY_OPS:
            played = True
        elif step["op"] not in OBSERVATION_OPS:
            played = False
        elif played and _meaningful(step):
            yield step


def _same_action(left, right):
    """JSON equality with distinct booleans and ordinary numeric equivalence."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _same_action(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_action(a, b) for a, b in zip(left, right))
    return left == right


def _path_capture_comparisons(step, comparisons):
    if not _meaningful(step) or step.get("cmp") not in comparisons:
        return
    for current, previous in (
        (step.get("left", {}), step.get("right", {})),
        (step.get("right", {}), step.get("left", {})),
    ):
        if (
            "path" in current
            and "saved" not in current
            and "saved" in previous
            and current["path"] == previous.get("path")
        ):
            yield current["path"], previous["saved"]


def _capture_matches_at(steps, boundary, path, key):
    """A capture or an equality must establish the baseline after any mutation.

    Reusing the same snapshot across rejected imports is valid when the earlier
    equality re-established its live value. A stale snapshot before intervening
    progress is not a preservation baseline for an import or serialized save.
    """
    matches = False
    for step in steps[:boundary]:
        if step["op"] == "capture" and step["key"] == key:
            matches = True
        elif step["op"] not in OBSERVATION_OPS:
            matches = False
        elif (path, key) in _path_capture_comparisons(step, {"eq"}):
            matches = True
    return matches


def _restore_evidence(steps, index, contract, domain_ids):
    """Bind baseline, divergence and restoration to the same path and capture.

    A rejected import preserves the current live state even when its input is an
    older real save. Accepted imports compare against the serialized baseline;
    at least one saved path must still differ immediately before restoration.
    """
    restore = steps[index]
    boundary = index
    if restore["expect"] == "accepted":
        serialized = [
            i
            for i, step in enumerate(steps[:index])
            if step["op"] == "serialize" and step["key"] == restore.get("saved")
        ]
        if not serialized:
            return set(), False
        boundary = serialized[-1]
    equalities, covered, post_restore_captures = set(), set(), set()
    for step in _following_observations(steps, index):
        if step["op"] == "capture":
            post_restore_captures.add(step["key"])
        for path, key in _path_capture_comparisons(step, {"eq"}):
            if key not in post_restore_captures and _capture_matches_at(steps, boundary, path, key):
                equalities.add((path, key))
                covered.update(_observed_domains(step, contract))
    divergent = set()
    for step in steps[boundary + 1 : index]:
        if step["op"] not in OBSERVATION_OPS:
            divergent.clear()
        elif set(domain_ids) & _observed_domains(step, contract):
            divergent.update(_path_capture_comparisons(step, {"ne", "gt", "lt"}))
    return covered, bool(divergent & equalities)


def _following_observations(steps, index):
    for step in steps[index + 1 :]:
        if step["op"] not in OBSERVATION_OPS:
            break
        yield step


def validate_semantic_coverage(contract, scenarios):
    """Reject missing evidence plans before the four author calls spend tokens.

    Returns references suitable for the UI/log. This is a declaration check ONLY.
    Every referenced scenario must still execute against the exact output artifact.
    """
    if contract.get("version") != 3:
        raise ProviderError("New generation requires semantic contract v3")
    by_id = {scenario["id"]: scenario for scenario in scenarios}
    loop = contract["first_playable_loop"]["scenario_id"]
    loop_steps = by_id.get(loop, {}).get("steps", [])
    if (
        loop not in by_id
        or by_id[loop]["category"] != "progress"
        or not any(_play_observations(loop_steps))
    ):
        raise ProviderError(
            "First playable loop must reference a progress scenario with observable consequences"
        )
    entries = []
    for collection in ("transactions", "progression", "persistence"):
        for item in contract[collection]:
            _references(item["scenario_ids"], by_id, collection + " scenarios", maximum=8)
            related = [by_id[name] for name in item["scenario_ids"]]
            if any(item["owner"] not in scenario["affected_files"] for scenario in related):
                raise ProviderError("An obligation's QA scenarios must include its owning module")
            entries.append(
                {
                    "contract_id": item["id"],
                    "kind": collection,
                    "scenario_ids": item["scenario_ids"],
                }
            )
            if collection == "transactions":
                action = json.loads(item["action_json"])
                replay = []
                for scenario in related:
                    if scenario["category"] != "accounting":
                        continue
                    commands = 0
                    for i, step in enumerate(scenario["steps"]):
                        if (
                            step["op"] in {"reset", "reload"}
                            or step["op"] == "restore"
                            and step.get("expect") == "accepted"
                            or step["op"] == "lifecycle"
                            and step.get("event") == "remount"
                        ):
                            commands = 0
                        elif step["op"] == "act" and _same_action(step["action"], action):
                            commands += step.get("repeat", 1)
                            observed = set().union(
                                *(
                                    _observed_domains(observation, contract)
                                    for observation in _following_observations(scenario["steps"], i)
                                )
                            )
                            if commands >= 2 and set(item["domain_ids"]).issubset(observed):
                                replay.append(scenario)
                                break
                if not replay:
                    raise ProviderError(
                        "Each transaction needs an accounting scenario that repeats its real command and observes effects"
                    )
            elif collection == "progression":
                field_path = next(
                    field["path"]
                    for field in contract["fields"]
                    if field["id"] == item["source_field_id"]
                )
                observed = False
                for scenario in related:
                    if scenario["category"] not in {"progress", "accounting"}:
                        continue
                    for step in _play_observations(scenario["steps"]):
                        if any(
                            "path" in operand
                            and "saved" not in operand
                            and _overlaps(operand["path"], field_path)
                            for side in ("left", "right")
                            for operand in _operand_leaves(step.get(side))
                        ):
                            observed = True
                if not observed:
                    raise ProviderError(
                        "Progression needs an observable progress/accounting scenario"
                    )
            else:
                persistence = [
                    scenario for scenario in related if scenario["category"] == "persistence"
                ]
                accepted = rejected = faults = False
                for scenario in persistence:
                    steps = scenario["steps"]
                    for i, step in enumerate(steps):
                        if step["op"] == "restore":
                            covered, diverged = _restore_evidence(
                                steps, i, contract, item["domain_ids"]
                            )
                            if set(item["domain_ids"]).issubset(covered):
                                if step["expect"] == "accepted" and "saved" in step and diverged:
                                    accepted = True
                                elif step["expect"] == "rejected":
                                    rejected = True
                        if (
                            step["op"] == "storage_fault"
                            and step["mode"] != "normal"
                            and _has_observed_comparison(steps, i + 1)
                        ):
                            faults = True
                if not accepted or not rejected:
                    raise ProviderError(
                        "Persistence needs accepted save/restore and rejected import scenarios with subsequent state observations"
                    )
                if item["storage"] == "local_storage" and not faults:
                    raise ProviderError("Local storage needs an observable denied/quota scenario")
    for item in contract.get("review_obligations", []):
        _references(
            item["scenario_ids"], by_id, "Review obligation scenarios", empty=True, maximum=8
        )
        related = [by_id[name] for name in item["scenario_ids"]]
        for scenario in related:
            if not set(item["owners"]).issubset(scenario["affected_files"]):
                raise ProviderError("Review obligation scenarios must include all named owners")
            if not _has_observed_comparison(scenario["steps"]):
                raise ProviderError("Review obligation scenarios need nontrivial observations")
        if item["kind"] == "alternative_choice" and related:
            strategy = [scenario for scenario in related if scenario["category"] == "strategy"]
            commands = {
                stable_json({key: value for key, value in step.items() if key != "repeat"})
                for scenario in strategy
                for step in scenario["steps"]
                if step["op"] in {"act", "click", "key"}
            }
            if len(commands) < 2 or not any(
                any(_play_observations(scenario["steps"])) for scenario in strategy
            ):
                raise ProviderError(
                    "Alternative choices need a strategy scenario with different real commands and observed consequences"
                )
        entries.append(
            {
                "contract_id": item["id"],
                "kind": "review_obligations",
                "review_kind": item["kind"],
                "owners": item["owners"],
                "scenario_ids": item["scenario_ids"],
                "limitations": item["limitations"],
                "evidence_scope": "declared_scenarios" if related else "review_only",
            }
        )
    return {
        "version": 1,
        "status": "declared",
        "first_playable_loop": loop,
        "obligations": entries,
        "limitation": "Bindings and bounded operations checked; execution and semantic correctness are separate evidence",
    }
