"""Optional explicit container execution boundary; never host-evaluate game JS."""

import contextlib
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from prompt2play.legacy.worker.core import check_cancel
from .evidence import artifact_manifest, canonical_json, check_record
from .scenarios import validate_scenarios


RUNTIME_CONTRACT_VERSION = 2
RUNTIME_CHECKS = (
    "state_progress",
    "surface_frames",
    "surface_size",
    "audio_activation",
    "audio_activity",
    "reset",
    "javascript_errors",
    "external_requests",
    "screenshot",
    "bridge_contract",
)


def scenario_counters(scenario):
    """Expected completed operations, derived from validated data, never model prose."""
    steps = scenario["steps"]
    count = lambda op: sum(step["op"] == op for step in steps)
    return {
        "steps_completed": len(steps),
        "assertions": count("assert"),
        "actions": sum(step.get("repeat", 1) for step in steps if step["op"] == "act"),
        "simulation_frames": sum(step["frames"] for step in steps if step["op"] == "advance"),
        "serializations": count("serialize"),
        "imports_attempted": count("restore"),
        "imports_accepted": sum(
            step["op"] == "restore" and step["expect"] == "accepted" for step in steps
        ),
        "imports_rejected": sum(
            step["op"] == "restore" and step["expect"] == "rejected" for step in steps
        ),
        "storage_fault_changes": count("storage_fault"),
        "snapshots_captured": count("capture"),
        "clicks": count("click"),
        "focuses": count("focus"),
        "keys": count("key"),
        "resets": count("reset"),
        "reloads": count("reload"),
        "lifecycle": {
            event: sum(step["op"] == "lifecycle" and step["event"] == event for step in steps)
            for event in ("hide", "show", "remount")
        },
    }


def _checked_scenario_evidence(evidence, scenario=None):
    for name in ("assertions", "steps_completed"):
        if type(evidence.get(name)) is not int or evidence[name] <= 0:
            raise ValueError("Passing scenario omitted actual executed steps or assertions")
    if evidence["steps_completed"] <= evidence["assertions"]:
        raise ValueError("Passing scenario did not execute a gameplay or lifecycle operation")
    if scenario is None:
        return
    for name, expected in scenario_counters(scenario).items():
        actual = evidence.get(name)
        if name == "lifecycle":
            if (
                not isinstance(actual, dict)
                or set(actual) != set(expected)
                or any(
                    type(actual[key]) is not int or actual[key] != value
                    for key, value in expected.items()
                )
            ):
                raise ValueError(
                    "Passing scenario lifecycle counts do not match the requested sequence"
                )
        elif type(actual) is not int or actual != expected:
            raise ValueError("Passing scenario execution count differs from the request: " + name)
    if evidence.get("seed") != scenario["seed"] or evidence.get("category") != scenario["category"]:
        raise ValueError("Passing scenario identity evidence differs from the request")
    cleanup = evidence.get("cleanup")
    if (
        not isinstance(cleanup, dict)
        or set(cleanup) != {"manual_clock", "storage", "lifecycle"}
        or any(value is not True for value in cleanup.values())
    ):
        raise ValueError("Passing scenario omitted successful cleanup evidence")
    save_bytes = evidence.get("serialized_bytes")
    if (
        type(save_bytes) is not int
        or not 0 <= save_bytes <= 2_048_000
        or (evidence["serializations"] > 0 and save_bytes <= 0)
    ):
        raise ValueError("Passing scenario has invalid serialized-byte evidence")
    events = [step["event"] for step in scenario["steps"] if step["op"] == "lifecycle"]
    observations = evidence.get("lifecycle_observations")
    if not isinstance(observations, list) or len(observations) != len(events):
        raise ValueError("Passing scenario omitted lifecycle observations")
    for event, observation in zip(events, observations):
        if not isinstance(observation, dict) or observation.get("event") != event:
            raise ValueError("Lifecycle observation is bound to a different operation")
        if event == "remount":
            if observation.get("acknowledged") is not True:
                raise ValueError("Remount completion was not acknowledged")
        elif observation.get("synthetic") is not True or observation.get("hidden") is not (
            event == "hide"
        ):
            raise ValueError("Synthetic lifecycle evidence lacks its actual visibility state")
    modes = [
        step["mode"]
        for step in scenario["steps"]
        if step["op"] == "storage_fault" and step["mode"] != "normal"
    ]
    faults = evidence.get("storage_faults")
    if not isinstance(faults, list) or len(faults) != len(modes):
        raise ValueError("Passing scenario omitted exercised storage fault intervals")
    for mode, fault in zip(modes, faults):
        if (
            not isinstance(fault, dict)
            or fault.get("mode") != mode
            or fault.get("exercised") is not True
        ):
            raise ValueError("Passing scenario did not exercise its storage fault")
        names = ("blocked_reads", "blocked_writes", "blocked_removals", "denied_accesses")
        if any(type(fault.get(name)) is not int or fault[name] < 0 for name in names):
            raise ValueError("Invalid storage fault operation counts")
        if (
            fault["blocked_writes"] if mode == "quota" else sum(fault[name] for name in names)
        ) <= 0:
            raise ValueError("Passing scenario storage fault has no actual blocked operation")


def _checked_surface_evidence(check, presentation_mode):
    evidence = check["evidence"]
    if evidence.get("presentation_mode") != presentation_mode:
        raise ValueError("Surface evidence belongs to a different presentation mode")
    if check["name"].startswith("surface_frames:"):
        if (
            any(
                not isinstance(evidence.get(name), str)
                or not re.fullmatch("[0-9a-f]{64}", evidence[name])
                for name in ("first_sha256", "second_sha256")
            )
            or any(
                type(evidence.get(name)) is not int or evidence[name] <= 0
                for name in ("first_bytes", "second_bytes")
            )
            or type(evidence.get("changed")) is not bool
            or evidence.get("sample_interval_ms") != 750
        ):
            raise ValueError("Surface frame samples are incomplete")
        if evidence["changed"] != (evidence["first_sha256"] != evidence["second_sha256"]):
            raise ValueError("Surface change claim contradicts the captured samples")
    else:
        if evidence.get("opacity_chain_visible") is not True:
            raise ValueError("Surface visibility evidence omitted the actual opacity chain")
        if (
            not isinstance(evidence.get("tag"), str)
            or not re.fullmatch("[a-z][a-z0-9-]{0,31}", evidence["tag"])
            or type(evidence.get("visible_canvases")) is not int
            or evidence["visible_canvases"] < 0
        ):
            raise ValueError("Surface type evidence is incomplete")
        if any(
            type(evidence.get(name)) not in (int, float)
            or not math.isfinite(evidence[name])
            or evidence[name] <= 0
            for name in ("width", "height")
        ):
            raise ValueError("Surface geometry evidence is empty or invalid")
        if presentation_mode == "canvas" and (
            evidence.get("tag") != "canvas" or evidence.get("canvas_backing_valid") is not True
        ):
            raise ValueError("Canvas presentation lacks a real canvas surface")
        if presentation_mode in ("dom", "hybrid") and (
            evidence.get("tag") == "canvas"
            or type(evidence.get("markup_elements")) is not int
            or evidence["markup_elements"] < 1
        ):
            raise ValueError("DOM presentation lacks rendered markup")
        if presentation_mode == "hybrid" and (
            evidence["visible_canvases"] < 1
            or evidence["markup_elements"] <= evidence["visible_canvases"]
        ):
            raise ValueError("Hybrid presentation lacks a visible canvas")


def skipped(message, manifest, scenarios=()):
    checks = [
        check_record("isolated_browser_runtime", "skipped", message, manifest, check_kind="browser")
    ]
    for scenario in scenarios:
        checks.append(
            check_record(
                "scenario:" + scenario["id"],
                "skipped",
                "Declared scenario was not executed: " + message,
                manifest,
                check_kind="scenario",
                scenario_id=scenario["id"],
                affected_files=scenario["affected_files"],
                limitations=scenario["limitations"],
            )
        )
    return {"checks": checks, "errors": [], "warnings": [message]}


def failed(message, manifest):
    return {
        "checks": [
            check_record(
                "isolated_browser_runtime", "failed", message, manifest, check_kind="browser"
            )
        ],
        "errors": [message],
        "warnings": [],
    }


def checked_report(
    value,
    *,
    expected_manifest=None,
    expected_request_sha256=None,
    scenario_ids=(),
    expected_scenarios=None,
    expected_runtime_contract_version=None,
    expected_presentation_mode=None,
):
    """Malformed, stale, truncated, duplicate or incomplete successes cannot pass."""
    if not isinstance(value, dict) or any(
        not isinstance(value.get(k), list) or len(value[k]) > 100
        for k in ("checks", "errors", "warnings")
    ):
        raise ValueError("Invalid container report shape")
    if value.get("schema_version") != 2 or not isinstance(value.get("artifact"), dict):
        raise ValueError("Container did not return versioned artifact evidence")
    if expected_runtime_contract_version is not None and (
        type(value.get("runtime_contract_version")) is not int
        or value["runtime_contract_version"] != expected_runtime_contract_version
    ):
        raise ValueError("Container uses an outdated runtime contract; rebuild the validator image")
    if expected_manifest is not None and value["artifact"] != expected_manifest:
        raise ValueError("Container report belongs to a different artifact")
    if (
        expected_request_sha256 is not None
        and value.get("request_sha256") != expected_request_sha256
    ):
        raise ValueError("Container report belongs to a different QA request")
    digest = value["artifact"].get("html_sha256")
    scenarios_by_id = (
        {scenario["id"]: scenario for scenario in validate_scenarios(expected_scenarios)}
        if expected_scenarios
        else {}
    )
    if expected_scenarios is not None and set(scenario_ids) != set(scenarios_by_id):
        raise ValueError("Expected scenario IDs do not match their requested sequences")
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("Invalid artifact digest")
    if not value["checks"]:
        raise ValueError("Container returned no runtime evidence")
    browser_names = {f"{name}:{width}" for name in RUNTIME_CHECKS for width in (1280, 390)}
    scenario_names = {
        f"scenario:{scenario_id}:{width}": scenario_id
        for scenario_id in scenario_ids
        for width in (1280, 390)
    }
    names = set()
    for check in value["checks"]:
        if not isinstance(check, dict) or check.get("status") not in (
            "passed",
            "failed",
            "skipped",
        ):
            raise ValueError("Invalid runtime check")
        if any(
            not isinstance(check.get(k), str) or len(check[k]) > limit
            for k, limit in (("name", 160), ("message", 2000))
        ):
            raise ValueError("Invalid runtime check text")
        if check["name"] in names:
            raise ValueError("Duplicate runtime check")
        names.add(check["name"])
        if (
            check.get("check_kind") not in {"browser", "scenario"}
            or check.get("artifact_sha256") != digest
        ):
            raise ValueError("Runtime check kind/artifact mismatch")
        if (
            not isinstance(check.get("limitations"), list)
            or len(check["limitations"]) > 12
            or any(not isinstance(s, str) or len(s) > 500 for s in check["limitations"])
        ):
            raise ValueError("Invalid runtime limitations")
        if (
            not isinstance(check.get("evidence"), dict)
            or len(canonical_json(check["evidence"]).encode()) > 16000
        ):
            raise ValueError("Invalid bounded runtime observations")
        if check["check_kind"] == "scenario" and check.get("scenario_id") not in scenario_ids:
            raise ValueError("Unexpected scenario evidence")
        if check["name"].startswith("scenario:") and check["check_kind"] != "scenario":
            raise ValueError("Scenario result has the wrong check kind")
        if check["check_kind"] == "scenario":
            if scenario_names.get(check["name"]) != check.get("scenario_id"):
                raise ValueError("Mismatched scenario name, id or viewport")
            if check["status"] == "passed":
                _checked_scenario_evidence(
                    check["evidence"], scenarios_by_id.get(check["scenario_id"])
                )
        elif (
            check["name"] not in browser_names | {"runtime_harness"}
            or "scenario_id" in check
            or (check["name"] == "runtime_harness" and check["status"] != "failed")
        ):
            raise ValueError("Invalid browser check identity or kind")
        if (
            expected_presentation_mode is not None
            and check["status"] == "passed"
            and check["name"].startswith(("surface_frames:", "surface_size:"))
        ):
            _checked_surface_evidence(check, expected_presentation_mode)
    if any(
        not isinstance(s, str) or len(s) > 4000 for k in ("errors", "warnings") for s in value[k]
    ):
        raise ValueError("Invalid runtime report message")
    for check in value["checks"]:
        if check["status"] == "failed" and check["message"] not in value["errors"]:
            value["errors"].append(check["message"])
    if not value["errors"]:
        expected = browser_names | set(scenario_names)
        if not expected.issubset(names):
            raise ValueError("Container omitted required runtime evidence")
    return value


def run_validation(
    artifact,
    actions,
    cancel,
    *,
    image="game-forge-validator:local",
    timeout=90,
    qa_scenarios=None,
    spec=None,
    manifest=None,
):
    check_cancel(cancel)
    manifest = manifest or artifact_manifest({}, artifact, spec or {})
    if manifest["html_sha256"] != hashlib.sha256(artifact.encode()).hexdigest():
        return failed("Input artifact changed before isolated validation", manifest)
    try:
        scenarios = validate_scenarios(qa_scenarios) if qa_scenarios else []
        if not isinstance(actions, list) or len(actions) > 12:
            raise ValueError("At most twelve legacy smoke actions are permitted")
        normalized_actions = [
            json.loads(action) if isinstance(action, str) else action for action in actions
        ]
        if (
            any(not isinstance(action, dict) for action in normalized_actions)
            or len(canonical_json(normalized_actions).encode()) > 16000
        ):
            raise ValueError("Invalid smoke actions")
    except (TypeError, ValueError, RecursionError) as exc:
        return failed("Invalid isolated validation request: " + str(exc), manifest)
    docker = shutil.which("docker")
    if not docker:
        return skipped(
            "Docker unavailable; browser/runtime checks were not run", manifest, scenarios
        )
    try:
        inspected = subprocess.run(
            [docker, "image", "inspect", image], capture_output=True, timeout=10
        )
        if inspected.returncode:
            return skipped(
                "Validator image unavailable; build it explicitly before requesting runtime checks",
                manifest,
                scenarios,
            )
    except (OSError, subprocess.TimeoutExpired):
        return skipped("Docker daemon unavailable; runtime checks skipped", manifest, scenarios)
    check_cancel(cancel)
    container = "forge-validator-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="forge-validator-") as directory:
        base = Path(directory)
        base.chmod(0o755)
        request = {
            "schema_version": 2,
            "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
            "artifact": manifest,
            "spec": spec or {},
            "smoke_actions": normalized_actions,
            "qa_scenarios": scenarios,
        }
        request_bytes = canonical_json(request).encode("utf-8")
        request_sha256 = hashlib.sha256(request_bytes).hexdigest()
        (base / "game.html").write_text(artifact, encoding="utf-8")
        (base / "request.json").write_bytes(request_bytes)
        for path in base.iterdir():
            path.chmod(0o644)
        args = [
            docker,
            "run",
            "--rm",
            "--pull=never",
            "--name",
            container,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--cpus",
            "1",
            "--memory",
            "768m",
            "--memory-swap",
            "768m",
            "--pids-limit",
            "128",
            "--user",
            "10001:10001",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=192m",
            "--shm-size",
            "128m",
            "--mount",
            f"type=bind,src={directory},dst=/input,readonly",
            image,
        ]
        # Output is spooled outside the immutable input mount, never unbounded in memory.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            proc = subprocess.Popen(args, stdout=stdout, stderr=stderr)
            start = time.monotonic()
            try:
                while True:
                    check_cancel(cancel)
                    if stdout.tell() > 1_000_000 or stderr.tell() > 256_000:
                        return failed("Runtime container exceeded its output limit", manifest)
                    if time.monotonic() - start > timeout:
                        return failed("Isolated browser exceeded wall timeout", manifest)
                    if proc.poll() is not None:
                        break
                    cancel.wait(0.05)
                if proc.returncode:
                    return failed("Runtime container failed", manifest)
                stdout.seek(0)
                try:
                    return checked_report(
                        json.loads(stdout.read(1_000_001)),
                        expected_manifest=manifest,
                        expected_request_sha256=request_sha256,
                        scenario_ids=[s["id"] for s in scenarios],
                        expected_scenarios=scenarios,
                        expected_runtime_contract_version=RUNTIME_CONTRACT_VERSION,
                        expected_presentation_mode=(spec or {}).get("presentation_mode", "canvas"),
                    )
                except (ValueError, TypeError, RecursionError):
                    return failed("Invalid, stale or incomplete runtime report", manifest)
            finally:
                if proc.poll() is None:
                    proc.kill()
                # Client exit does not prove container termination. Always clean by unique name.
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    subprocess.run(
                        [docker, "rm", "--force", container],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=3)
