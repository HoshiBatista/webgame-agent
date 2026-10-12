"""Controlled live old/new comparison with one durable dollar ledger.

Run this file with either frozen snapshot on PYTHONPATH. Never host-executes
model source. A result is mechanically accepted only by the isolated validator;
rendered and human verdicts remain separate. Completed or ambiguous calls never
silently replay. Manifest and run folders are operator-owned input.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from prompt2play.application.policy import decide
from prompt2play.contracts.models import digest, stable
from prompt2play.evaluation import FileJournal, write_json
from prompt2play.generation import (
    GenerationControl,
    GenerationHarness,
    GenerationRequest,
    ProviderGateway,
)
from prompt2play.generation.runtime import assemble_runtime
from prompt2play.generation.workspace import GenerationStopped
from prompt2play.pricing import cost_bounds, nano_usd, usd
from prompt2play.validation import IsolatedValidator


@contextmanager
def locked(path):
    with path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


class SharedJournal(FileJournal):
    def __init__(self, folder, shared, limit, pricing, namespace=""):
        super().__init__(folder / "invocations.json")
        self.shared, self.limit, self.pricing = shared, limit, pricing
        self.prefix = namespace + folder.name

    def totals(self):
        rows = json.loads(self.shared.read_text()) if self.shared.exists() else {}
        return sum(r.get("upper_nano", 0) for r in rows.values()), sum(
            r.get("reserved_nano", 0) for r in rows.values()
        )

    def reserve(self, key, reserved_tokens, operation, request_sha256, *, estimate=None):
        with locked(self.shared.with_suffix(".lock")):
            existing = self.records.get(key)
            if existing:
                return super().reserve(
                    key, reserved_tokens, operation, request_sha256, estimate=estimate
                )
            if estimate is None:
                raise ValueError("Frozen comparison requires a monetary reservation")
            reserved = cost_bounds(estimate, self.pricing)[1]
            spent, uncertain = self.totals()
            if spent + uncertain + reserved > self.limit:
                raise GenerationStopped("Shared comparison dollar budget exhausted")
            rows = json.loads(self.shared.read_text()) if self.shared.exists() else {}
            rows[self.prefix + ":" + key] = {
                "operation": operation,
                "state": "reserved",
                "reserved_nano": reserved,
                "upper_nano": 0,
                "pricing": self.pricing,
            }
            write_json(self.shared, rows)

            return super().reserve(
                key, reserved_tokens, operation, request_sha256, estimate=estimate
            )

    def settle(self, key, *, data, usage, status):
        # Local receipt is durable before shared reconciliation; recovery can
        # safely retain the conservative reservation if the latter write fails.
        super().settle(key, data=data, usage=usage, status=status)
        with locked(self.shared.with_suffix(".lock")):
            rows = json.loads(self.shared.read_text())
            row = rows[self.prefix + ":" + key]
            row.update(state=status, usage=usage)
            if usage is not None:
                low, high = cost_bounds(usage, self.pricing)
                row.update(lower_nano=low, upper_nano=high, reserved_nano=0)
            write_json(self.shared, rows)


def preflight_validator(validator):
    if hasattr(validator, "preflight"):
        return validator.preflight()
    # Baseline adapter did not expose preflight. The operator checks the same
    # trusted inventory here without modifying its frozen implementation.
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Validator environment unavailable before comparison")
    expected = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(validator.runtime_path.parent.glob("*.mjs"))
    }
    script = (
        "const fs=require('fs'),crypto=require('crypto');let result={};"
        "for(const name of fs.readdirSync('/validator').filter(p=>p.endsWith('.mjs')).sort())"
        "result[name]=crypto.createHash('sha256').update(fs.readFileSync('/validator/'+name))"
        ".digest('hex');process.stdout.write(JSON.stringify(result));"
    )
    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=10001:10001",
            "--memory=128m",
            "--pids-limit=32",
            validator.image,
            "node",
            "-e",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode or json.loads(result.stdout) != expected:
        raise ValueError("Frozen validator source does not match its image")
    return {"image": validator.image, "harness_files": expected}


def run(args):
    manifest = json.loads(args.manifest.read_text())
    branch = manifest["variants"][args.variant]
    case = next(c for c in manifest["cases"] if c["id"] == args.case)
    folder = args.output / (
        args.variant + "-" + args.case + ("-revision" if args.revision else "-new")
    )
    folder.mkdir(parents=True, exist_ok=True)
    identity = digest(
        {
            "manifest": manifest,
            "variant": args.variant,
            "case": args.case,
            "revision": args.revision,
        }
    )
    result_file = folder / "result.json"
    if result_file.exists():
        result = json.loads(result_file.read_text())
        assert result["identity"] == identity
        print(json.dumps(result, ensure_ascii=False))
        return
    state_file = folder / "state.json"
    state = (
        json.loads(state_file.read_text())
        if state_file.exists()
        else {
            "identity": identity,
            "started": time.time(),
            "draft": {},
            "planning": {},
            "candidate": None,
            "attempts": [],
        }
    )
    assert state["identity"] == identity
    base = {}
    if args.revision:
        parent = args.output / (args.variant + "-" + args.case + "-new")
        previous = json.loads((parent / "result.json").read_text())
        if not previous.get("mechanically_accepted"):
            result = {
                "identity": identity,
                "outcome": "blocked_parent",
                "reason": "Parent did not pass mandatory mechanics",
                "mechanically_accepted": False,
                "paid_calls": 0,
            }
            write_json(result_file, result)
            print(json.dumps(result))
            return
        base = json.loads((parent / "candidate.json").read_text())
    journal = SharedJournal(
        folder,
        (args.output / manifest.get("shared_ledger", "budget-ledger.json")).resolve(),
        nano_usd(manifest["budget_usd"]),
        manifest["pricing"],
        manifest.get("ledger_namespace", ""),
    )
    usage, unknown = journal.accounting()
    local_spend = sum(
        cost_bounds(r["usage"], manifest["pricing"])[1]
        for r in journal.records.values()
        if r.get("usage")
    )
    shared_rows = json.loads(journal.shared.read_text()) if journal.shared.exists() else {}
    local_reserved = sum(
        r.get("reserved_nano", 0)
        for key, r in shared_rows.items()
        if key.startswith(journal.prefix + ":")
    )
    control = GenerationControl.bounded(
        cost_limit_nano=nano_usd(manifest["per_case_budget_usd"]),
        pricing=manifest["pricing"],
        usage=usage,
        spent_nano=local_spend,
        uncertain_cost_nano=local_reserved,
        uncertain_tokens=unknown,
    )
    gateway = ProviderGateway(
        manifest["provider"], manifest["model"], executable=manifest["codex"], journal=journal
    )
    validator = IsolatedValidator(branch["validator_image"], timeout=manifest["validator_seconds"])
    images = []

    def save_draft(value):
        state["draft"] = value
        write_json(state_file, state)

    def save_planning(value):
        state["planning"] = value
        write_json(state_file, state)

    def browser(files, spec):
        nonlocal images
        directory = folder / ("browser-" + str(time.time_ns()))
        html = assemble_runtime(files, spec)
        report = validator.validate(
            files, html, spec, control.cancel, directory, require_completion=False
        )
        write_json(directory / "report.json", report)
        images = []
        if args.variant == "adaptive":
            from prompt2play.generation.images import ImageInput

            for width in (1280, 390):
                interactions = sorted(directory.glob(f"interaction-*-{width}.png"))
                for name in (
                    f"start-{width}.png",
                    interactions[-1].name if interactions else f"control-after-{width}.png",
                    f"final-{width}.png",
                ):
                    path = directory / name
                    if path.is_file():
                        images.append(ImageInput(name, path.read_bytes()))
        unavailable = any(
            c["name"] == "isolated_browser_runtime" and c["status"] != "passed"
            for c in report["checks"]
        )
        return {
            **report,
            "scope": "infrastructure" if unavailable else "browser",
            "diagnostic_key": str(directory / "report.json"),
            "release_eligible": False,
        }

    def rendered(files, spec, plan):
        from prompt2play.generation.images import image_metadata
        from prompt2play.generation.rendered_quality import (
            RENDERED_INSTRUCTIONS,
            RENDERED_SCHEMA,
            validate_rendered,
        )
        from prompt2play.legacy.worker.core import PROMPT_BOUNDARY

        if not gateway.image_preflight():
            return {"status": "human_required", "reason": "Image transport unavailable"}
        report = browser(files, spec)
        if report["status"] != "passed":
            raise GenerationStopped("Fresh rendered evidence unavailable")
        if len(images) < 4:
            return {"status": "human_required", "reason": "Frames incomplete"}
        metadata = image_metadata(images)
        response = gateway.generate(
            RENDERED_INSTRUCTIONS
            + PROMPT_BOUNDARY
            + stable(
                {
                    "request": case["revision"] if args.revision else case["prompt"],
                    "visual_design": plan["visual_design"],
                    "review_feedback": plan.get("review_feedback", []),
                    "frames": metadata,
                    "artifact": report["artifact"],
                }
            ),
            RENDERED_SCHEMA,
            "rendered_review",
            control,
            max_output=6000,
            images=images,
        )
        return {
            "status": validate_rendered(response.data, {i.name for i in images}),
            "review": response.data,
            "frames": metadata,
            "receipt": response.invocation_key,
            "diagnostic_key": report["diagnostic_key"],
            "review_sha256": digest(response.data),
        }

    kwargs = {
        "on_checkpoint": save_draft,
        "on_planning": save_planning,
        "on_browser_check": browser,
        "require_completion": False,
    }
    if args.variant == "adaptive":
        kwargs.update(on_rendered_check=rendered, browser_identity=validator.cache_identity())
    harness = GenerationHarness(**kwargs)
    outcome, reason, mechanical, candidate = "incomplete", "", False, state.get("candidate")
    try:
        write_json(folder / "validator-preflight.json", preflight_validator(validator))
        gateway.preflight()
        while True:
            if candidate is None:
                request_values = {
                    "kind": "revise" if args.revision else "generate",
                    "base_files": base.get("files", {}),
                    "base_spec": base.get("spec", {}),
                    "base_plan": base.get("plan", {}),
                    "resume_state": state.get("draft") or {},
                    "planning_state": state.get("planning") or {},
                    "attempt_id": folder.name + ":" + str(len(state["attempts"]) + 1),
                }
                if state["attempts"]:
                    request_values.update(
                        kind="repair",
                        base_files=base["files"],
                        base_spec=base["spec"],
                        base_plan=base["plan"],
                        findings=[
                            c
                            for c in state["attempts"][-1]["report"]["checks"]
                            if c["status"] == "failed"
                        ],
                    )
                if args.variant == "adaptive":
                    request_values.update(
                        pipeline_version="adaptive-v1",
                        project_format=base.get("format", branch["project_format"]),
                        controller_state=state.get("controller") or {},
                    )
                candidate = harness.attempt(
                    GenerationRequest(
                        case["revision"] if args.revision else case["prompt"], **request_values
                    ),
                    gateway,
                    control,
                ).as_dict()
                state.update(candidate=candidate)
                write_json(state_file, state)
                write_json(folder / "candidate.json", candidate)
                (folder / "index.html").write_text(candidate["html"])
            directory = folder / ("independent-" + str(time.time_ns()))
            report = validator.validate(
                candidate["files"],
                candidate["html"],
                candidate["spec"],
                control.cancel,
                directory,
                require_completion=False,
            )
            write_json(directory / "report.json", report)
            decision = decide(report, 1, 1)
            state["attempts"].append(
                {"report": report, "artifact": digest(candidate), "path": str(directory)}
            )
            write_json(state_file, state)
            if decision.action == "promote":
                mechanical, outcome = True, "mechanically_accepted"
                break
            if decision.action == "stop":
                outcome, reason = "unverified", decision.reason
                break
            if args.variant == "adaptive":
                from prompt2play.application.progress import observe

                controller = candidate["provenance"]["adaptive"]
                observe(
                    controller,
                    "independent_validation",
                    report,
                    source_id=digest(candidate["files"]),
                    suite_id=report.get("suite_sha256", ""),
                    cost=control.snapshot(),
                )
                controller["supervisor_due"] = (
                    "Independent acceptance failed; diagnose retained source before next correction"
                )
                state["controller"] = controller
            elif len(state["attempts"]) >= manifest["legacy_candidate_limit"]:
                outcome, reason = "failed", "Frozen legacy repair policy exhausted"
                break
            base, candidate = candidate, None
            state.update(candidate=None, draft={}, planning={})
            write_json(state_file, state)
    except Exception as exc:
        outcome, reason = type(exc).__name__, str(exc)[:2000]
    finally:
        gateway.close()
    spent, reserved = journal.totals()
    result = {
        "identity": identity,
        "variant": args.variant,
        "case": args.case,
        "revision": args.revision,
        "outcome": outcome,
        "reason": reason,
        "mechanically_accepted": mechanical,
        "visual_status": (candidate or {})
        .get("provenance", {})
        .get("visual_quality", {})
        .get("rendered_visual_review", "not_performed"),
        "human_visual_assessment": "pending",
        "elapsed_seconds": time.time() - state["started"],
        "accounting": control.snapshot(),
        "paid_calls": control.usage["calls"],
        "attempts": len(state["attempts"]),
        "shared_spent_usd": usd(spent),
        "shared_reserved_usd": usd(reserved),
        "source_kept": bool(state.get("draft", {}).get("files")) or bool(candidate),
    }
    write_json(result_file, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=["legacy", "adaptive"], required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--revision", action="store_true")
    args = parser.parse_args()
    with locked(
        args.output
        / (args.variant + "-" + args.case + ("-revision" if args.revision else "-new") + ".lock")
    ):
        run(args)
