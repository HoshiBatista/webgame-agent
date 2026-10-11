"""Durable LangGraph: planner → four concurrent authors → checks → reviewer → repair."""

from __future__ import annotations
import copy
import hashlib
import json
import operator
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from .core import (
    FILES,
    ROLES,
    Budget,
    BudgetExceeded,
    COMPONENT_SCHEMA,
    PLAN_SCHEMA,
    PLAN_OUTPUT_SCHEMA,
    REVIEW_SCHEMA,
    ProviderError,
    check_cancel,
    stable_json,
    PROMPT_BOUNDARY,
    contract_entries,
    contract_declarations,
    validate_semantic_contract,
    validate_review,
    presentation_mode,
)
from .semantics import validate_semantic_coverage, review_obligation_context
from prompt2play.legacy.validator.checks import assemble, validate, validate_files
from prompt2play.legacy.validator.evidence import artifact_manifest, report_matches
from prompt2play.legacy.validator.scenarios import validate_scenarios
from prompt2play.paths import LEGACY_ROOT

ROOT = LEGACY_ROOT
CODE_ROOT = Path(__file__).resolve().parent.parent
EXECUTION_INPUTS = (
    "worker/core.py",
    "worker/semantics.py",
    "worker/pipeline.py",
    "worker/providers.py",
    "worker/transport.py",
    "validator/checks.py",
    "validator/evidence.py",
    "validator/scenarios.py",
    "validator/docker.py",
    "validator/runtime.mjs",
    "validator/bridge_adapter.mjs",
    "validator/scenario_runner.mjs",
    "validator/audio_probe.mjs",
    "validator/audio_activation.mjs",
    "validator/Dockerfile",
    "validator/storage_probe.mjs",
    "validator/lifecycle_probe.mjs",
    "validator/surface_probe.mjs",
)


def implementation_fingerprint():
    inputs = {
        name: hashlib.sha256((CODE_ROOT / name).read_bytes()).hexdigest()
        for name in EXECUTION_INPUTS
    }
    return hashlib.sha256(stable_json(inputs).encode()).hexdigest()


def output_limit(name, default):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer from 1000 through 64000") from exc
    if not 1000 <= value <= 64000:
        raise ValueError(f"{name} must be an integer from 1000 through 64000")
    return value


class FlowState(TypedDict):
    visits: Annotated[list[str], operator.add]


class Pipeline:
    def __init__(
        self,
        job,
        provider,
        *,
        base_version=None,
        checkpoint=None,
        cancel=None,
        persist=None,
        event=None,
        runtime=False,
        validator_image="game-forge-validator:local",
    ):
        self.job, self.provider, self.base = job, provider, base_version
        if job.get("kind") == "revise" and base_version and base_version.get("is_reference"):
            raise ValueError(
                "The legacy reference is read-only; generate a new game before requesting a revision"
            )
        self.cancel = cancel or threading.Event()
        self.persist = persist or (lambda checkpoint, usage: None)
        self.event = event or (lambda **data: None)
        self.runtime, self.image = runtime, validator_image
        self.lock = threading.RLock()
        identity = hashlib.sha256(
            stable_json(
                {
                    k: job.get(k)
                    for k in ("id", "kind", "prompt", "provider", "model", "base_version_id")
                }
            ).encode()
        ).hexdigest()
        checkpoint = copy.deepcopy(checkpoint or {})
        if checkpoint and (checkpoint.get("schema") != 2 or checkpoint.get("identity") != identity):
            raise ValueError("Checkpoint does not belong to this job/version")
        self.cp = checkpoint or {
            "schema": 2,
            "identity": identity,
            "cycle": 0,
            "files": {},
            "component_cycles": {},
            "completed": {},
            "trace": {"calls": [], "iterations": [], "sources": []},
        }
        account = self.cp.get("budget", {})
        self.budget = Budget(
            job.get("budget_tokens", 400000),
            account.get("usage"),
            account.get("uncertain", 0),
            account.get("reserved"),
        )
        if account.get("reserved"):
            self.cp.setdefault("warnings", []).append(
                "Interrupted calls had unknown usage; their reservations remain charged to the worker budget"
            )
        self.prompts = {}
        self.prompt_metadata = {}
        code_limit = output_limit("FORGE_CODE_OUTPUT_TOKENS", 16000)
        # UI owns CSS, markup, input and lifecycle as well as its JS controller.
        # Explicit global settings still apply unless a UI override is supplied.
        ui_default = code_limit if "FORGE_CODE_OUTPUT_TOKENS" in os.environ else 32000
        self.output_limits = {
            "plan": output_limit("FORGE_PLAN_OUTPUT_TOKENS", 10000),
            "review": output_limit("FORGE_REVIEW_OUTPUT_TOKENS", 6000),
            **dict.fromkeys(ROLES, code_limit),
            "ui": output_limit("FORGE_UI_OUTPUT_TOKENS", ui_default),
        }
        previous_execution = self.cp.get("execution")
        if checkpoint and not previous_execution:
            raise ValueError(
                "Legacy checkpoint has no execution metadata; create a new job. Its saved usage was not reset."
            )
        # An explicit saved model takes precedence over another runner's default.
        self.model = (
            job.get("model")
            or (previous_execution or {}).get("model")
            or getattr(provider, "model", "")
        )
        self.prefixes = {role: self._read_prefix(role) for role in ("plan", *ROLES, "review")}
        contract = self.prefixes
        execution = {
            "provider": job["provider"],
            "model": self.model,
            "output_limits": dict(self.output_limits),
            "contract_sha256": hashlib.sha256(stable_json(contract).encode()).hexdigest(),
            "schemas_sha256": hashlib.sha256(
                stable_json(
                    {
                        "plan": PLAN_SCHEMA,
                        "plan_output": PLAN_OUTPUT_SCHEMA,
                        "component": COMPONENT_SCHEMA,
                        "review": REVIEW_SCHEMA,
                    }
                ).encode()
            ).hexdigest(),
            "implementation_sha256": implementation_fingerprint(),
        }
        if previous_execution and previous_execution != execution:
            raise ValueError(
                "Checkpoint execution contract/output limits changed; create a new job. Saved usage and modules were preserved."
            )
        if (
            checkpoint
            and job["provider"] == "codex"
            and not self.model
            and getattr(provider, "name", "") == "codex"
        ):
            raise ValueError(
                "Cannot safely resume an unpinned Codex CLI model; create a new job with CODEX_MODEL or job.model set explicitly."
            )
        self.cp["execution"] = execution
        for record in self.cp.get("trace", {}).get("calls", []):
            if record.get("status") == "started":
                record["status"] = "interrupted_unknown"
        if (
            job["provider"] == "codex"
            and not self.model
            and getattr(provider, "name", "") == "codex"
        ):
            self.cp.setdefault("warnings", []).append(
                "Codex model comes from local CLI configuration; cross-runner recovery requires an explicit model on a new job"
            )

    def _save(self):
        with self.lock:
            self.cp["budget"] = self.budget.snapshot()
            self.persist(copy.deepcopy(self.cp), dict(self.budget.usage))

    def _event(self, stage, progress, message, level="info", **data):
        check_cancel(self.cancel)
        self.event(stage=stage, progress=progress, message=message, level=level, data=data)

    @staticmethod
    def _read_prefix(role):
        common = (ROOT / "prompts/common.txt").read_text()
        prompt = common + "\n" + (ROOT / "prompts" / f"{role}.txt").read_text()
        return prompt + PROMPT_BOUNDARY

    def _prefix(self, role):
        return self.prefixes[role]

    def _prompt(self, role):
        # Stable task and specification precede changing implementation/evidence.
        # JSON is a sequence of named data sections, never additional instructions.
        sections = [{"task": {"user_request": self.job["prompt"], "kind": self.job["kind"]}}]
        dynamic = {}
        included_sources = {}
        if role == "plan":
            if self.base:
                dynamic["previous_spec"] = self.base.get("spec", {})
                dynamic["previous_module_summaries"] = (
                    self.base.get("validation", {})
                    .get("provenance", {})
                    .get("module_summaries", {})
                )
                dynamic["previous_source_fingerprints"] = self._source_hashes(self.base["files"])
                # Legacy versions may not have summaries. Their complete source is
                # more honest than calling an arbitrary prefix an interface.
                if not dynamic["previous_module_summaries"]:
                    dynamic["previous_files"] = self.base["files"]
                    included_sources.update(self.base["files"])
        else:
            sections.append({"frozen_spec": self.cp["plan"]})
            if role in ROLES:
                entries = contract_entries(self.cp["plan"]["semantic_contract"])
                declarations = contract_declarations(self.cp["plan"]["semantic_contract"])
                filename = role + ".js"
                role_contract = {
                    "owned_ids": sorted(
                        key
                        for key, value in declarations.items()
                        if value.get("owner") == filename or filename in value.get("owners", [])
                    ),
                    "dependency_ids": sorted(
                        key for key, owners in entries.items() if filename in owners
                    ),
                    "first_playable_loop": self.cp["plan"]["semantic_contract"][
                        "first_playable_loop"
                    ]["scenario_id"],
                }
                focus = review_obligation_context(self.cp["plan"]["semantic_contract"], filename)
                if focus:
                    role_contract["review_focus"] = focus
                sections.append({"role_contract": role_contract})
            if role == "review":
                focus = review_obligation_context(self.cp["plan"]["semantic_contract"])
                if focus:
                    sections.append({"declared_review_focus": focus})
                dynamic.update(files=self.cp["files"], validation=self.cp["validation"])
                included_sources.update(self.cp["files"])
                dynamic["module_summaries"] = self.cp.get("module_summaries", {})
                dynamic["previous_issues"] = self.cp.get("repair_issues", [])
            elif self.cp["cycle"] or self.job["kind"] == "revise":
                dynamic["current_source"] = self.cp["files"].get(role + ".js", "")
                if dynamic["current_source"]:
                    included_sources[role + ".js"] = dynamic["current_source"]
                dynamic["other_module_summaries"] = {
                    k: v for k, v in self.cp.get("module_summaries", {}).items() if k != role
                }
                dynamic["source_fingerprints"] = self._source_hashes(self.cp["files"])
                issues = [
                    issue
                    for issue in self.cp.get("repair_issues", [])
                    if role + ".js" in self._issue_files(issue)
                ]
                dynamic["repair_issues"] = issues
                dependencies = (
                    self._revision_dependencies(role + ".js")
                    if self.job["kind"] == "revise"
                    else set()
                )
                for issue in issues:
                    if issue.get("scope") in ("integration", "contract"):
                        dependencies.update(self._issue_files(issue))
                dynamic["integration_dependency_sources"] = {
                    name: self.cp["files"][name]
                    for name in sorted(dependencies)
                    if name != role + ".js" and name in self.cp["files"]
                }
                included_sources.update(dynamic["integration_dependency_sources"])
        dynamic["output_token_target"] = self.output_limits[role]
        sections.append({"current_context": dynamic})
        prompt = self._prefix(role) + "\n".join(stable_json(section) for section in sections)
        self.prompt_metadata[hashlib.sha256(prompt.encode()).hexdigest()] = {
            "source_sha256": self._source_hashes(included_sources),
            "spec_sha256": hashlib.sha256(stable_json(self.cp["plan"]).encode()).hexdigest()
            if role != "plan"
            else None,
        }
        return prompt

    def _revision_dependencies(self, filename):
        """Shared changes need actual neighboring source, including before review.

        Summaries locate modules but cannot establish compatibility. Local edits
        retain the smaller own-source context; changed interfaces add only their
        declared owners/consumers. Legacy upgrades include the existing modules.
        """
        previous = (self.base or {}).get("spec", {})
        current = self.cp["plan"]
        old_contract = previous.get("semantic_contract", {})

        def same_schema(name):
            try:
                return json.loads(previous[name]) == json.loads(current[name])
            except (KeyError, TypeError, ValueError):
                return False

        if old_contract.get("version") != 3 or any(
            not same_schema(name) for name in ("state_schema", "action_schema", "event_schema")
        ):
            return set(FILES)
        old, new = (
            contract_declarations(old_contract),
            contract_declarations(current["semantic_contract"]),
        )
        old_entries, new_entries = (
            contract_entries(old_contract),
            contract_entries(current["semantic_contract"]),
        )
        dependencies = (
            {"renderer.js", "ui.js"}
            if presentation_mode(previous) != presentation_mode(current)
            and filename in {"renderer.js", "ui.js"}
            else set()
        )
        for identifier in old.keys() | new.keys():
            if old.get(identifier) != new.get(identifier):
                owners = old_entries.get(identifier, set()) | new_entries.get(identifier, set())
                if filename in owners:
                    dependencies.update(owners)
        return dependencies

    @staticmethod
    def _source_hashes(files):
        return {
            name: hashlib.sha256(source.encode()).hexdigest()
            for name, source in sorted(files.items())
        }

    def _spec(self):
        # Frozen before validation. Mutable call/iteration trace is stored only in
        # validation.provenance and never changes the hash-bound specification.
        return {**copy.deepcopy(self.cp["plan"]), "generation": copy.deepcopy(self.cp["execution"])}

    def _issue_files(self, issue):
        files = set(issue.get("affected_files") or [issue.get("file")]) & set(FILES)
        if issue.get("scope") == "contract":
            entries = contract_entries(self.cp["plan"]["semantic_contract"])
            for identifier in issue.get("contract_ids", []):
                files.update(entries.get(identifier, set()))
        return files

    def _call(self, role, schema, key, prompt, reserved=False):
        check_cancel(self.cancel)
        if not reserved:
            self.budget.reserve_many({key: Budget.estimate(prompt, self.output_limits[role])})
            self._save()
        with self.lock:
            record = {
                "id": len(self.cp["trace"]["calls"]) + 1,
                "role": role,
                "cycle": self.cp["cycle"],
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "started",
                "provider": self.job["provider"],
                "model": self.model,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "stable_prefix_sha256": hashlib.sha256(self._prefix(role).encode()).hexdigest(),
                "prompt_bytes": len(prompt.encode()),
                "output_limit": self.output_limits[role],
                **self.prompt_metadata.get(
                    hashlib.sha256(prompt.encode()).hexdigest(),
                    {"source_sha256": {}, "spec_sha256": None},
                ),
            }
            self.cp["trace"]["calls"].append(record)
            self._save()
        known_usage = None
        try:
            reply = self.provider.generate(
                prompt,
                schema,
                role,
                self.cancel,
                max_output=self.output_limits[role],
                model=self.model,
            )
            known_usage = reply.usage
            self.budget.settle(key, reply.usage)
            with self.lock:
                record.update(
                    status="completed",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    usage=copy.deepcopy(reply.usage),
                )
        except BaseException as exc:
            failure = exc
            if key in self.budget.reserved:
                try:
                    self.budget.settle(key, getattr(exc, "usage", None))
                except BudgetExceeded as accounting_error:
                    # Settlement has already recorded known usage and removed the
                    # reservation. Persist it even when the budget is exceeded.
                    failure = accounting_error
            with self.lock:
                record.update(
                    status="cancelled" if self.cancel.is_set() else "failed",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    error_type=type(failure).__name__,
                )
                usage = known_usage if known_usage is not None else getattr(exc, "usage", None)
                record["usage"] = copy.deepcopy(usage) if usage is not None else None
            if not self.cancel.is_set():
                self._save()
            if failure is not exc:
                raise failure from exc
            raise
        self._save()
        return reply.data

    def plan(self, state):
        if "plan" not in self.cp:
            self._event("plan", 5, "Planning rules, shared interfaces and acceptance criteria")
            plan = self._call("plan", PLAN_OUTPUT_SCHEMA, "plan", self._prompt("plan"))
            import jsonschema

            try:
                jsonschema.validate(plan, PLAN_SCHEMA)
            except (jsonschema.ValidationError, TypeError) as exc:
                raise ProviderError("Planner returned an invalid structured specification") from exc
            validate_semantic_contract(plan["semantic_contract"])
            try:
                scenarios = validate_scenarios(plan["qa_scenarios"])
            except ValueError as exc:
                raise ProviderError("Planner QA scenarios are invalid: " + str(exc)) from exc
            if not {"progress", "lifecycle"}.issubset(
                {scenario["category"] for scenario in scenarios}
            ):
                raise ProviderError("Planner needs both progress and lifecycle QA scenarios")
            if plan["semantic_contract"]["timing"]["mode"] == "turn_based" and any(
                step["op"] == "advance" for scenario in scenarios for step in scenario["steps"]
            ):
                raise ProviderError(
                    "Turn-based scenarios must use actual actions instead of advancing a real-time clock"
                )
            coverage = validate_semantic_coverage(plan["semantic_contract"], scenarios)
            affected = list(dict.fromkeys(plan["affected_files"]))
            if self.job["kind"] == "generate":
                affected = list(FILES)
            elif not self.base:
                raise ValueError("Revision requires a base version")
            elif not affected or not set(affected).issubset(FILES):
                raise ProviderError("Revision plan must select at least one valid source module")
            if self.base:
                validate_files(self.base["files"])
                self.cp["files"] = copy.deepcopy(self.base["files"])
                self.cp["module_summaries"] = copy.deepcopy(
                    self.base.get("validation", {})
                    .get("provenance", {})
                    .get("module_summaries", {})
                )
            for name in ("state_schema", "action_schema", "event_schema"):
                try:
                    if not isinstance(json.loads(plan[name]), dict):
                        raise ValueError()
                except ValueError as exc:
                    raise ProviderError(f"Planner {name} must contain valid JSON") from exc
            if self.job["kind"] == "revise" and set(affected) != set(FILES):
                previous = self.base.get("spec", {})
                if previous.get("semantic_contract", {}).get("version") != 3:
                    raise ProviderError(
                        "The base version predates the v3 lifetime/persistence contract; its one-time upgrade must select all four modules before authoring"
                    )
                if presentation_mode(previous) != presentation_mode(plan) and {
                    "renderer.js",
                    "ui.js",
                } - set(affected):
                    raise ProviderError(
                        "Revision changes presentation mode without selecting renderer.js and ui.js"
                    )
                for name in ("state_schema", "action_schema", "event_schema"):
                    try:
                        unchanged = json.loads(previous[name]) == json.loads(plan[name])
                    except (KeyError, TypeError, ValueError):
                        unchanged = False
                    if not unchanged:
                        raise ProviderError(
                            "Revision changes shared schemas without selecting all dependent modules; no source was replaced"
                        )
                old_contract = previous.get("semantic_contract")
                if old_contract and stable_json(old_contract) != stable_json(
                    plan["semantic_contract"]
                ):
                    old_entries, new_entries = (
                        contract_entries(old_contract),
                        contract_entries(plan["semantic_contract"]),
                    )
                    required = set()
                    old_declarations, new_declarations = (
                        contract_declarations(old_contract),
                        contract_declarations(plan["semantic_contract"]),
                    )
                    # A review obligation is evidence planning, not a gameplay
                    # interface change. Adding one may supply neighboring source
                    # for inspection but does not itself force those files to be
                    # rewritten. A concrete contract-scoped review issue still
                    # expands to all bound owners/consumers through _issue_files.
                    old_review_ids = {
                        item["id"] for item in old_contract.get("review_obligations", [])
                    }
                    new_review_ids = {
                        item["id"]
                        for item in plan["semantic_contract"].get("review_obligations", [])
                    }
                    for identifier in old_declarations.keys() | new_declarations.keys():
                        if (
                            identifier not in old_declarations or identifier in old_review_ids
                        ) and (identifier not in new_declarations or identifier in new_review_ids):
                            continue
                        if old_declarations.get(identifier) != new_declarations.get(identifier):
                            required.update(old_entries.get(identifier, set()))
                            required.update(new_entries.get(identifier, set()))
                    if required - set(affected):
                        raise ProviderError(
                            "Revision changes shared semantic contracts without selecting their dependent modules"
                        )
            try:
                if len(plan["smoke_actions"]) > 12 or any(
                    not isinstance(json.loads(action), dict) for action in plan["smoke_actions"]
                ):
                    raise ValueError()
            except (TypeError, ValueError) as exc:
                raise ProviderError("Smoke actions must contain at most 12 JSON objects") from exc
            plan["affected_files"] = affected
            self.cp.update(plan=plan, affected=affected, semantic_coverage=coverage)
            self._event(
                "contract",
                10,
                "Semantic interfaces and observable scenarios validated before authoring",
                contract_sha256=hashlib.sha256(
                    stable_json(plan["semantic_contract"]).encode()
                ).hexdigest(),
                scenarios=[scenario["id"] for scenario in scenarios],
                timing=plan["semantic_contract"]["timing"]["mode"],
                semantic_version=3,
                presentation_mode=presentation_mode(plan),
                coverage=coverage,
            )
            self._save()
        return {"visits": ["plan"]}

    def prepare(self, state):
        cycle = self.cp["cycle"]
        pending = [
            r
            for r in ROLES
            if r + ".js" in self.cp["affected"] and self.cp["component_cycles"].get(r) != cycle
        ]
        self.prompts = {r: self._prompt(r) for r in pending}
        self.budget.reserve_many(
            {
                f"{cycle}:{r}": Budget.estimate(self.prompts[r], self.output_limits[r])
                for r in pending
            }
        )
        self._save()
        return {"visits": ["prepare"]}

    def author(self, role):
        def node(state):
            if role not in self.prompts:
                return {"visits": [role + ":reused"]}
            cycle = self.cp["cycle"]
            self._event(
                role,
                15 + ROLES.index(role) * 10,
                f"Writing {role}.js" + (" (focused repair)" if cycle else ""),
            )
            reply = self._call(
                role, COMPONENT_SCHEMA, f"{cycle}:{role}", self.prompts[role], reserved=True
            )
            source = reply["source"]
            if not isinstance(source, str) or not source.strip() or len(source.encode()) > 180000:
                raise ProviderError("Author returned empty or oversized source")
            with self.lock:
                self.cp["files"][role + ".js"] = source
                self.cp["component_cycles"][role] = cycle
                self.cp.setdefault("module_summaries", {})[role] = reply["summary"][:2000]
                self.cp["trace"]["sources"].append(
                    {
                        "cycle": cycle,
                        "file": role + ".js",
                        "source": source,
                        "sha256": hashlib.sha256(source.encode()).hexdigest(),
                        "summary": reply["summary"][:2000],
                    }
                )
                self._save()
            return {"visits": [role]}

        return node

    def assemble_node(self, state):
        self._event("assemble", 60, "Assembling the four generated modules into one offline HTML")
        self.html = assemble(self.cp["files"], self.cp["plan"]["title"])
        return {"visits": ["assemble"]}

    def validate_node(self, state):
        cycle = self.cp["cycle"]
        validation_mode = "docker:" + self.image if self.runtime else "static"
        spec = self._spec()
        if (
            self.cp["completed"].get("validate") != cycle
            or self.cp.get("validation_mode") != validation_mode
            or not report_matches(self.cp.get("validation", {}), self.cp["files"], self.html, spec)
        ):
            self._event(
                "validate", 70, "Parsing JavaScript and checking standalone/runtime contracts"
            )
            self.cp["validation"] = validate(
                self.cp["files"],
                self.html,
                self.cancel,
                runtime=self.runtime,
                image=self.image,
                smoke_actions=self.cp["plan"]["smoke_actions"],
                qa_scenarios=self.cp["plan"]["qa_scenarios"],
                spec=spec,
            )
            # Review evidence has changed even if the source cycle is unchanged.
            self.cp["completed"].pop("review", None)
            self.cp["completed"]["validate"] = cycle
            self.cp["validation_mode"] = validation_mode
            self.cp["trace"]["iterations"].append(
                {
                    "id": len(self.cp["trace"]["iterations"]) + 1,
                    "cycle": cycle,
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                    "validation_mode": validation_mode,
                    "artifact": copy.deepcopy(self.cp["validation"].get("artifact", {})),
                    "status": self.cp["validation"]["status"],
                    "checks": copy.deepcopy(self.cp["validation"]["checks"]),
                    "errors": copy.deepcopy(self.cp["validation"]["errors"]),
                    "affected_files": list(self.cp["affected"]),
                }
            )
            self._save()
        return {"visits": ["validate"]}

    def review_node(self, state):
        cycle = self.cp["cycle"]
        if self.cp["completed"].get("review") != cycle:
            self._event(
                "review", 80, "Independent model review of actual source and validation evidence"
            )
            prompt = self._prompt("review")
            self.cp["review"] = validate_review(
                self._call("review", REVIEW_SCHEMA, f"{cycle}:review", prompt), self.cp["plan"]
            )
            self.cp["review_prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
            self.cp["review_artifact"] = artifact_manifest(
                self.cp["files"], self.html, self._spec()
            )
            self.cp["trace"]["iterations"][-1]["review"] = copy.deepcopy(self.cp["review"])
            self.cp["completed"]["review"] = cycle
            self._save()
        return {"visits": ["review"]}

    def route(self, state):
        review = self.cp["review"]
        bad = (
            bool(self.cp["validation"]["errors"])
            or not review["approved"]
            or any(i["severity"] == "error" for i in review["issues"])
        )
        if not bad:
            return "result"
        if self.cp["cycle"] >= int(self.job.get("max_repairs", 2)):
            raise ProviderError(
                "Validation/review still reports blocking defects after the bounded repair attempts"
            )
        return "repair"

    def repair(self, state):
        issues = [i for i in self.cp["review"]["issues"] if i["severity"] == "error"]
        affected = set().union(*(self._issue_files(issue) for issue in issues))
        for check in self.cp["validation"]["checks"]:
            if check["status"] != "failed":
                continue
            names = [n for n in check.get("affected_files", []) if n in FILES]
            if not names:
                names = [n for n in FILES if n in check["name"] or n in check["message"]]
            affected.update(names or FILES)
            issues.append(
                {
                    "file": names[0] if names else "engine.js",
                    "severity": "error",
                    "message": check["message"],
                    "scope": "local" if len(names) == 1 else "integration",
                    "affected_files": names or list(FILES),
                    "contract_ids": [],
                    "reproduction": check.get("scenario_id") or check["name"],
                    "observed": check["message"],
                    "expected": "The recorded validation check passes against the frozen contract",
                    "regression_scenario_id": check.get("scenario_id", ""),
                }
            )
        if not affected:
            affected = set(FILES)
        if self.job["kind"] == "revise":
            allowed = set(self.cp["plan"]["affected_files"])
            if affected - allowed:
                raise ProviderError(
                    "Review found defects outside the planned revision scope; unrelated modules were preserved. Request a broader revision."
                )
        self.cp["cycle"] += 1
        self.cp["affected"] = sorted(affected)
        self.cp["repair_issues"] = issues
        self._event(
            "repair",
            85,
            "Repairing reported defects and their concrete integration dependencies",
            files=sorted(affected),
            attempt=self.cp["cycle"],
            issue_count=len(issues),
            scenario_ids=sorted(
                {issue.get("regression_scenario_id", "") for issue in issues} - {""}
            ),
        )
        self._save()
        return {"visits": ["repair"]}

    def result(self, state):
        spec = self._spec()
        manifest = artifact_manifest(self.cp["files"], self.html, spec)
        if (
            not report_matches(self.cp["validation"], self.cp["files"], self.html, spec)
            or self.cp.get("review_artifact") != manifest
        ):
            raise ProviderError(
                "Files, specification or assembled HTML changed after validation/review; no result was released"
            )
        report = copy.deepcopy(self.cp["validation"])
        report["warnings"].extend(self.cp.get("warnings", []))
        if self.budget.uncertain:
            report["warnings"].append(
                "Some interrupted provider usage is unknown; budget includes conservative reservations, actual Usage counters include reported tokens only"
            )
        for issue in self.cp["review"]["issues"]:
            if issue["severity"] == "warning":
                report["warnings"].append((issue["file"] + ": " + issue["message"])[:4000])
        report["review"] = {
            **copy.deepcopy(self.cp["review"]),
            "provider": self.job["provider"],
            "model": self.model,
            "contract_sha256": self.cp["execution"]["contract_sha256"],
            "prompt_sha256": self.cp["review_prompt_sha256"],
            "artifact_sha256": manifest["html_sha256"],
        }
        iterations = []
        for previous in self.cp["trace"]["iterations"]:
            item = {
                key: copy.deepcopy(previous[key])
                for key in (
                    "id",
                    "cycle",
                    "validated_at",
                    "validation_mode",
                    "artifact",
                    "status",
                    "affected_files",
                )
            }
            item["checks_total"] = len(previous["checks"])
            item["checks_truncated"] = len(previous["checks"]) > 64
            item["checks"] = [
                {
                    key: str(check[key])[:120]
                    for key in ("name", "status", "check_kind", "scenario_id")
                    if key in check
                }
                for check in previous["checks"][:64]
            ]
            item["errors_count"] = len(previous["errors"])
            item["error_summary"] = [message[:300] for message in previous["errors"][:2]]
            if "review" in previous:
                review = previous["review"]
                item["review"] = {
                    "approved": review["approved"],
                    "summary": review["summary"][:1500],
                    "issue_count": len(review["issues"]),
                    "blocking_count": sum(
                        issue["severity"] == "error" for issue in review["issues"]
                    ),
                }
            iterations.append(item)
        report["provenance"] = {
            "calls": copy.deepcopy(self.cp["trace"]["calls"]),
            "iterations": iterations,
            "module_summaries": copy.deepcopy(self.cp.get("module_summaries", {})),
        }
        self.output = dict(
            files=copy.deepcopy(self.cp["files"]),
            html=self.html,
            spec=spec,
            summary=self.cp["review"]["summary"][:3000],
            validation=report,
            usage=dict(self.budget.usage),
        )
        self._event(
            "done", 100, "Generated artifact ready; runtime validation status: " + report["status"]
        )
        return {"visits": ["result"]}

    def run(self):
        graph = StateGraph(FlowState)
        for name, node in [
            ("plan", self.plan),
            ("prepare", self.prepare),
            ("assemble", self.assemble_node),
            ("validate", self.validate_node),
            ("review", self.review_node),
            ("repair", self.repair),
            ("result", self.result),
        ]:
            graph.add_node(name, node)
        for role in ROLES:
            graph.add_node(role, self.author(role))
        graph.add_edge(START, "plan")
        graph.add_edge("plan", "prepare")
        for role in ROLES:
            graph.add_edge("prepare", role)
        graph.add_edge(list(ROLES), "assemble")
        graph.add_edge("assemble", "validate")
        graph.add_edge("validate", "review")
        graph.add_conditional_edges("review", self.route, {"repair": "repair", "result": "result"})
        graph.add_edge("repair", "prepare")
        graph.add_edge("result", END)
        graph.compile().invoke({"visits": []}, {"max_concurrency": 4, "recursion_limit": 80})
        return self.output
