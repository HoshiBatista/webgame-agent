"""Container-only execution of untrusted games; host work is parsing and hashing."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from prompt2play.contracts.source_policy import source_findings
from prompt2play.legacy.validator.checks import static_validate as legacy_static_validate
from prompt2play.legacy.validator.evidence import artifact_manifest as legacy_artifact_manifest
from prompt2play.legacy.validator.evidence import canonical_json as legacy_canonical_json
from prompt2play.legacy.validator.evidence import check_record as legacy_check_record
from prompt2play.legacy.worker.core import check_cancel as legacy_check_cancel
from prompt2play.validation.progress import ProgressWatchdog

canonical_json = cast(Callable[[Any], str], legacy_canonical_json)
artifact_manifest = cast(
    Callable[[dict[str, str], str, dict[str, Any]], dict[str, Any]], legacy_artifact_manifest
)
check_record = cast(Callable[..., dict[str, Any]], legacy_check_record)
check_cancel = cast(Callable[[threading.Event], None], legacy_check_cancel)
static_validate = cast(Callable[..., dict[str, Any]], legacy_static_validate)

BROWSER_CONTRACT_VERSION = 3
REQUIRED_CHECKS = frozenset(
    f"{name}:{width}"
    for name in (
        "startup",
        "surface",
        "input",
        "completion",
        "restart",
        "javascript_errors",
        "external_requests",
        "evidence",
        "independent_acceptance",
    )
    for width in (1280, 390)
) | {"mobile_layout:390"}
MAX_EVIDENCE_BYTES = 32_000_000
HASH = re.compile(r"[0-9a-f]{64}")


@lru_cache(maxsize=16)
def _preflight_image(docker: str, image: str, expected: str) -> None:
    # Only trusted container inventory is inspected; no generated game is mounted.
    script = (
        "const fs=require('fs'),crypto=require('crypto');let result={};"
        "for(const name of fs.readdirSync('/validator').filter(p=>p.endsWith('.mjs')).sort())"
        "result[name]=crypto.createHash('sha256').update(fs.readFileSync('/validator/'+name))"
        ".digest('hex');process.stdout.write(JSON.stringify(result));"
    )
    try:
        value = subprocess.run(
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
                image,
                "node",
                "-e",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if value.returncode or json.loads(value.stdout) != json.loads(expected):
            raise ValueError(
                "Validator image does not match trusted checking code; rebuild before generation"
            )
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise ValueError(
            "Validator environment is unavailable before generation; no model call made"
        ) from exc


def _selector(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("A bounded, nonempty selector is required")
    return value


def _point(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise ValueError("Pointer coordinates require x and y")
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1280
        for v in value.values()
    ):
        raise ValueError("Pointer coordinates are outside the viewport bounds")
    return {"x": value["x"], "y": value["y"]}


def validate_acceptance(value: Any, *, allow_passive: bool = False) -> dict[str, Any]:
    """Only declarative real input is permitted; there is no executable test source."""
    if not isinstance(value, dict) or set(value) != {
        "start_selector",
        "restart_selector",
        "desktop",
        "touch",
    }:
        raise ValueError(
            "Independent acceptance requires start, restart, desktop and touch scenarios"
        )
    result: dict[str, Any] = {
        "start_selector": _selector(value["start_selector"]),
        "restart_selector": _selector(value["restart_selector"]),
    }
    for device in ("desktop", "touch"):
        scenario = value[device]
        if not isinstance(scenario, dict) or set(scenario) != {"steps", "completion"}:
            raise ValueError("Each acceptance scenario requires steps and completion")
        steps = scenario["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
            raise ValueError("Acceptance requires one to sixty-four steps")
        normalized = []
        actual_inputs = 0
        for step_index, step in enumerate(steps, 1):
            if not isinstance(step, dict) or step.get("kind") not in {
                "key",
                "key_down",
                "key_up",
                "blur",
                "focus",
                "click",
                "tap",
                "drag",
                "wait",
            }:
                raise ValueError("Unsupported real input operation")
            kind = step["kind"]
            repeat = step.get("repeat", 1)
            if type(repeat) is not int or not 1 <= repeat <= 30:
                raise ValueError("Input repeat must be between one and thirty")
            item: dict[str, Any] = {"kind": kind, "repeat": repeat}
            allowed = {"kind", "repeat"}
            if kind in {"key", "key_down", "key_up"}:
                if device == "touch":
                    raise ValueError("Touch acceptance cannot substitute keyboard input")
                key = step.get("key")
                if not isinstance(key, str) or not key.strip() or len(key) > 40:
                    raise ValueError("A bounded keyboard key is required")
                item["key"] = key
                allowed.add("key")
            elif kind in {"blur", "focus"}:
                pass
            elif kind in {"click", "tap"}:
                if step.get("selector"):
                    item["selector"] = _selector(step["selector"])
                    allowed.add("selector")
                elif kind == "tap":
                    item.update(_point({"x": step.get("x"), "y": step.get("y")}))
                    allowed.update({"x", "y"})
                else:
                    raise ValueError("Click requires a selector")
            elif kind == "drag":
                ms = step.get("ms", 0)
                if type(ms) is not int or not 0 <= ms <= 600000:
                    raise ValueError("Drag duration must be zero to ten simulated minutes")
                if ms:
                    item["ms"] = ms
                allowed.add("ms")
                if step.get("from_selector") or step.get("to_selector"):
                    item["from_selector"] = _selector(step.get("from_selector"))
                    item["to_selector"] = _selector(step.get("to_selector"))
                    allowed.update({"from_selector", "to_selector"})
                else:
                    item["from"] = _point(step.get("from"))
                    item["to"] = _point(step.get("to"))
                    allowed.update({"from", "to"})
            else:
                ms = step.get("ms")
                if type(ms) is not int or not 0 <= ms <= 600000 or repeat != 1:
                    raise ValueError("Wait must be at most ten simulated minutes")
                item["ms"] = ms
                allowed.add("ms")
            defaults = {
                "from_selector": "",
                "to_selector": "",
                "key": "",
                "selector": "",
                "x": 0,
                "y": 0,
                "ms": 0,
                "from": {"x": 0, "y": 0},
                "to": {"x": 0, "y": 0},
            }
            extra = set(step) - allowed
            invalid = sorted(
                name for name in extra if name not in defaults or step[name] != defaults[name]
            )
            if invalid:
                rules = "; ".join(
                    f"{name} must be {defaults[name]!r}" if name in defaults else f"remove {name}"
                    for name in invalid
                )
                raise ValueError(
                    f"{device}.steps[{step_index - 1}] ({kind}): {rules}. Duration ms is supported only for wait and drag; use a separate wait for held keys."
                )
            actual_inputs += repeat if kind != "wait" else 0
            normalized.append(item)
        if not (0 if allow_passive else 1) <= actual_inputs <= 128:
            raise ValueError("Acceptance requires one to 128 actual input events")
        if sum(step.get("ms", 0) for step in normalized) > 1800000:
            raise ValueError("Scenario exceeds thirty simulated minutes")
        completion = scenario["completion"]
        if not isinstance(completion, dict) or set(completion) != {"path", "one_of"}:
            raise ValueError("Completion requires a JSON pointer and accepted outcome values")
        path, outcomes = completion["path"], completion["one_of"]
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or len(path) > 200
            or re.search(r"~(?![01])", path)
        ):
            raise ValueError("Completion path must be a bounded JSON pointer")
        if (
            not isinstance(outcomes, list)
            or not 1 <= len(outcomes) <= 8
            or any(type(v) not in (str, bool, int) for v in outcomes)
        ):
            raise ValueError("Completion outcomes must be bounded scalar values")
        if len(canonical_json(outcomes).encode()) > 1000:
            raise ValueError("Completion outcome values are oversized")
        result[device] = {"steps": normalized, "completion": completion}
    return result


def validate_native_acceptance(value: Any) -> dict[str, Any]:
    """Reject a smoke test as a playthrough; never silently replace its oracle."""
    result = validate_acceptance(value)
    if result["start_selector"] != "#p2p-start" or result["restart_selector"] != "#p2p-restart":
        raise ValueError("Native scenarios must use the platform start/restart controls")
    for device in ("desktop", "touch"):
        completion = result[device]["completion"]
        if completion["path"] != "/phase" or not set(completion["one_of"]) <= {"won", "lost"}:
            raise ValueError(
                f"{device}: this is a smoke test, not a complete playthrough. Use set_test_scenario "
                "with real gameplay actions and simulated waits reaching /phase won or lost. "
                "Do not change the game rules to finish after an intermediate action."
            )
    return result


def _failure(
    manifest: dict[str, Any], message: str, *, unavailable: bool = False
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "artifact": manifest,
        "status": "unverified" if unavailable else "failed",
        "incomplete": True,
        "browser_contract_version": BROWSER_CONTRACT_VERSION,
        "checks": [
            check_record(
                "isolated_browser_runtime",
                "skipped" if unavailable else "failed",
                message,
                manifest,
                check_kind="browser",
            )
        ],
        "errors": [] if unavailable else [message],
        "warnings": [message] if unavailable else [],
        "evidence_files": [],
        "scope": {"isolated": True, "real_input": False, "webview": False},
    }


def evidence_payload(directory: Path, report: dict[str, Any]) -> dict[str, str]:
    """Read only verified private evidence into the validator-role upload payload."""
    result = {}
    total = 0
    for item in report.get("evidence_files", []):
        name = item.get("path")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z0-9_-]+\.(?:png|json|zip|txt)", name)
            or name in result
        ):
            raise ValueError("Unsafe or repeated evidence upload path")
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise ValueError("Invalid evidence upload file")
        data = path.read_bytes()
        total += len(data)
        if total > MAX_EVIDENCE_BYTES:
            raise ValueError("Evidence upload byte budget exceeded")
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Evidence changed after validation")
        result[item["path"]] = base64.b64encode(data).decode("ascii")
    return result


class IsolatedValidator:
    """Resource-isolated execution with an idle watchdog, not a total time limit."""

    def __init__(self, image: str = "prompt2play-validator:local", timeout: float = 90) -> None:
        if not image or len(image) > 250 or timeout <= 0 or not math.isfinite(timeout):
            raise ValueError("Invalid validator configuration")
        self.image = image
        self.timeout = timeout

    def cache_identity(self) -> dict[str, Any]:
        """Bind draft reuse to the actual image and trusted suite, not a mutable tag."""
        image_id = "unavailable"
        docker = shutil.which("docker")
        if docker:
            try:
                value = subprocess.run(
                    [docker, "image", "inspect", "--format", "{{.Id}}", self.image],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if not value.returncode and re.fullmatch(
                    r"sha256:[0-9a-f]{64}", value.stdout.strip()
                ):
                    image_id = value.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
        return {
            "image": image_id,
            "image_tag": self.image,
            "timeout": self.timeout,
            "timeout_policy": "completed-progress-idle-v1",
            "browser_contract": BROWSER_CONTRACT_VERSION,
            "harness_files": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.runtime_path.parent.glob("*.mjs"))
            },
        }

    def preflight(self) -> dict[str, Any]:
        """Reject an unavailable/stale image before paying for planning or authoring."""
        identity = self.cache_identity()
        docker = shutil.which("docker")
        if not docker or identity["image"] == "unavailable":
            raise ValueError("Validator image is unavailable before generation; no model call made")
        _preflight_image(docker, identity["image"], canonical_json(identity["harness_files"]))
        return identity

    def validate(
        self,
        files: dict[str, str],
        html: str,
        spec: dict[str, Any],
        cancel: threading.Event,
        evidence_dir: Path,
        *,
        release_scenarios: dict[str, Any] | None = None,
        require_completion: bool = True,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        check_cancel(cancel)
        manifest: dict[str, Any] = artifact_manifest(files, html, spec)
        try:
            acceptance = (
                validate_native_acceptance
                if "game.js" in files and require_completion
                else validate_acceptance
            )(
                release_scenarios
                or spec.get("independent_acceptance")
                or spec.get("input_acceptance")
            )
        except (ValueError, TypeError) as exc:
            return _failure(
                manifest, "No valid real-input acceptance scenario: " + str(exc), unavailable=True
            )
        mechanics = []
        if spec.get("mechanics_required") or spec.get("mechanics_acceptance"):
            from prompt2play.contracts.mechanics import validate_mechanics

            try:
                mechanics = validate_mechanics(
                    spec.get("mechanics_acceptance"),
                    spec.get(
                        "mechanics_required_actions", [a["type"] for a in spec.get("actions", [])]
                    ),
                )
            except (ValueError, TypeError) as exc:
                return _failure(
                    manifest, "Invalid basic mechanics acceptance: " + str(exc), unavailable=True
                )
        acceptance_source = "release-config" if release_scenarios is not None else "candidate-plan"
        if release_scenarios is None and "game.js" in files:
            acceptance_source = "native-conformance"
        static = self._static(files, html, spec, cancel)
        if static["errors"]:
            return static
        docker = shutil.which("docker")
        if not docker:
            return _failure(
                manifest, "Docker unavailable; generated game was not executed", unavailable=True
            )
        try:
            inspection = subprocess.run(
                [docker, "image", "inspect", "--format", "{{.Id}}", self.image],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            image_id = inspection.stdout.strip()
            if inspection.returncode or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                return _failure(
                    manifest,
                    "Validator image unavailable; build the configured image",
                    unavailable=True,
                )
        except (OSError, subprocess.TimeoutExpired):
            return _failure(
                manifest,
                "Docker daemon unavailable; generated game was not executed",
                unavailable=True,
            )
        evidence_dir = evidence_dir.resolve()
        evidence_dir.mkdir(parents=True, exist_ok=True)
        if any(evidence_dir.iterdir()):
            raise ValueError("Evidence directory must be empty for each immutable attempt")
        # A dedicated evidence-only mount is writable by the container's unprivileged UID.
        evidence_dir.chmod(0o777)
        harness_files = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.runtime_path.parent.glob("*.mjs"))
        }
        suite = hashlib.sha256(
            canonical_json(
                {
                    "version": BROWSER_CONTRACT_VERSION,
                    "acceptance": acceptance,
                    "mechanics": mechanics,
                    "completion_required": require_completion,
                    "harness_files_sha256": harness_files,
                }
            ).encode()
        ).hexdigest()
        request = {
            "schema_version": 2,
            "browser_contract_version": BROWSER_CONTRACT_VERSION,
            "artifact": manifest,
            "spec": spec,
            "acceptance": acceptance,
            "mechanics": mechanics,
            "completion_required": require_completion,
            "acceptance_source": acceptance_source,
            "suite_sha256": suite,
            "validator_image_sha256": image_id,
            "harness_files_sha256": harness_files,
        }
        with tempfile.TemporaryDirectory(prefix="p2p-validation-input-") as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            (base / "game.html").write_text(html, encoding="utf-8")
            request_bytes = canonical_json(request).encode()
            (base / "request.json").write_bytes(request_bytes)
            for path in base.iterdir():
                path.chmod(0o644)
            container = "p2p-validator-" + uuid.uuid4().hex
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
                "256",
                "--user",
                "10001:10001",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=192m",
                "--shm-size",
                "128m",
                "--mount",
                f"type=bind,src={base},dst=/input,readonly",
                "--mount",
                f"type=bind,src={evidence_dir},dst=/evidence",
                image_id,
                "node",
                "/validator/release_runtime.mjs",
            ]
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                try:
                    process = subprocess.Popen(args, stdout=stdout, stderr=stderr)
                except OSError:
                    evidence_dir.chmod(0o700)
                    return _failure(
                        manifest, "Could not start isolated validator", unavailable=True
                    )
                watchdog = ProgressWatchdog(
                    hashlib.sha256(request_bytes).hexdigest(), time.monotonic()
                )
                last_notification = float("-inf")
                try:
                    while process.poll() is None:
                        check_cancel(cancel)
                        now = time.monotonic()
                        progressed = watchdog.observe(evidence_dir, now)
                        if stdout.tell() > 1_000_000 or stderr.tell() > 256_000:
                            stderr.seek(0)
                            return self._interrupted_report(
                                manifest,
                                watchdog,
                                evidence_dir,
                                request,
                                "Isolated validator exceeded its output bound",
                                diagnostic=stderr.read(256_000),
                            )
                        if progressed and on_progress and now - last_notification >= 10:
                            on_progress(
                                {"completed_operations": watchdog.completed, **watchdog.active}
                            )
                            last_notification = now
                        if watchdog.stalled(now, self.timeout):
                            stderr.seek(0)
                            return self._stalled_report(
                                manifest,
                                watchdog,
                                evidence_dir,
                                request,
                                diagnostic=stderr.read(256_000),
                            )
                        cancel.wait(0.05)
                    check_cancel(cancel)
                    watchdog.observe(evidence_dir, time.monotonic())
                    stderr.seek(0)
                    diagnostic = stderr.read(256_000)
                    if process.returncode:
                        return self._interrupted_report(
                            manifest,
                            watchdog,
                            evidence_dir,
                            request,
                            f"Isolated validator exited with code {process.returncode}; inspect attached diagnostic",
                            diagnostic=diagnostic,
                        )
                    stdout.seek(0)
                    try:
                        value = json.loads(stdout.read(1_000_001))
                        value = self.checked_report(
                            value,
                            manifest,
                            hashlib.sha256(request_bytes).hexdigest(),
                            suite,
                            image_id,
                            evidence_dir,
                            expected_harness=harness_files,
                            require_completion=require_completion,
                        )
                        if mechanics and value["status"] == "passed":
                            from prompt2play.adapters.django.forge.artifacts import (
                                require_report_binding,
                            )

                            cast(Callable[..., Any], require_report_binding)(
                                files, html, spec, value
                            )
                        if mechanics:
                            names = {c["name"] for c in value["checks"]}
                            value["incomplete"] = (
                                value.get("incomplete", False)
                                or not {"mechanics:1280", "mechanics:390"} <= names
                            )
                    except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
                        reason = str(exc)[:1000]
                        return self._interrupted_report(
                            manifest,
                            watchdog,
                            evidence_dir,
                            request,
                            "Invalid, stale, incomplete, or unbound isolated browser evidence: "
                            + reason,
                            diagnostic=diagnostic,
                        )
                    value["checks"] = static["checks"] + value["checks"]
                    value["warnings"] = static["warnings"] + value["warnings"]
                    if (
                        any(check["status"] == "skipped" for check in static["checks"])
                        and value["status"] == "passed"
                    ):
                        value["status"] = "unverified"
                    if acceptance_source == "candidate-plan" and value["status"] == "passed":
                        value["status"] = "unverified"
                        value["warnings"].append(
                            "Legacy candidate-authored conditions require a trusted release acceptance scenario"
                        )
                    return value
                finally:
                    if process.poll() is None:
                        process.kill()
                    try:
                        subprocess.run(
                            [docker, "rm", "--force", container],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=10,
                            check=False,
                        )
                        process.wait(timeout=3)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    evidence_dir.chmod(0o700)

    @property
    def runtime_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "legacy" / "validator" / "release_runtime.mjs"

    def _stalled_report(
        self,
        manifest: dict[str, Any],
        watchdog: ProgressWatchdog,
        directory: Path,
        request: dict[str, Any],
        *,
        diagnostic: bytes = b"",
    ) -> dict[str, Any]:
        game = watchdog.active["kind"] == "game"
        message = (
            "Browser game operation stopped making progress; inspect the recorded step and repair the game or scenario"
            if game
            else "Isolated browser infrastructure stopped making progress; saved draft can be retried"
        )
        return self._interrupted_report(
            manifest,
            watchdog,
            directory,
            request,
            message,
            check_name="browser_progress_stalled" if game else "isolated_browser_runtime",
            diagnostic=diagnostic,
        )

    def _interrupted_report(
        self,
        manifest: dict[str, Any],
        watchdog: ProgressWatchdog,
        directory: Path,
        request: dict[str, Any],
        message: str,
        *,
        check_name: str = "isolated_browser_runtime",
        diagnostic: bytes = b"",
    ) -> dict[str, Any]:
        """Preserve request-bound findings on every abnormal container exit."""
        evidence = {
            "idle_timeout_seconds": self.timeout,
            "completed_operations": watchdog.completed,
            "active": watchdog.active,
            "incomplete": True,
        }
        checks = watchdog.findings(directory, manifest["html_sha256"])
        checks.append(
            check_record(
                check_name,
                "failed",
                message,
                manifest,
                check_kind="browser",
                evidence=evidence,
            )
        )
        report = {
            **_failure(manifest, message),
            "checks": checks,
            "errors": [str(check.get("message", "Browser check failed")) for check in checks],
            "request_sha256": watchdog.request_hash,
            "completion_required": request.get("completion_required", True),
            **{
                key: request[key]
                for key in ("suite_sha256", "validator_image_sha256", "harness_files_sha256")
            },
            "warnings": ["Validation is incomplete. No unexecuted check is claimed as passed."],
        }
        # Exclusive, host-owned immutable snapshot. Mutable progress files are never uploaded.
        data = canonical_json(
            {
                "progress": evidence,
                "report": report,
                "container_stderr": diagnostic[:256_000].decode("utf-8", errors="replace"),
            }
        ).encode()
        name = f"interrupted-{uuid.uuid4().hex}.json"
        with (directory / name).open("xb") as output:
            output.write(data)
        report["evidence_files"] = [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        ]
        from .progress import read_object

        for width in (1280, 390):
            inputs = read_object(directory / f"inputs-{width}.json", 2_000_000)
            if inputs.get("request_sha256") != watchdog.request_hash:
                continue
            data = canonical_json(inputs).encode()
            name = f"inputs-{width}-{uuid.uuid4().hex}.json"
            with (directory / name).open("xb") as output:
                output.write(data)
            report["evidence_files"].append(
                {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            )
        return report

    @staticmethod
    def _static(
        files: dict[str, str], html: str, spec: dict[str, Any], cancel: threading.Event
    ) -> dict[str, Any]:
        if set(files) == {"engine.js", "renderer.js", "audio.js", "ui.js"}:
            return dict(static_validate(files, html, cancel, spec=spec))
        manifest = artifact_manifest(files, html, spec)
        checks, errors = [], []
        from prompt2play.generation.runtime import assemble_runtime

        try:
            runtime_identity = spec.get("runtime", {})
            exact_assembly = html == assemble_runtime(
                files, spec, expected_runtime_digest=runtime_identity.get("sha256")
            )
        except (ValueError, TypeError, KeyError):
            exact_assembly = False
        checks.append(
            check_record(
                "artifact_assembly",
                "passed" if exact_assembly else "failed",
                "Native delivery matches trusted runtime and source bytes",
                manifest,
                check_kind="provenance",
            )
        )
        if not exact_assembly:
            errors.append("Native delivered HTML differs from trusted assembly")
        modular = spec.get("format") == "runtime-modules-v2"
        valid = (
            bool(files)
            and len(html.encode()) <= 1_000_000
            and all(
                re.fullmatch(r"[a-zA-Z0-9_.-]+\.(?:js|css)", name)
                and isinstance(source, str)
                and len(source.encode()) <= 600_000
                for name, source in files.items()
            )
        )
        if modular:
            from prompt2play.generation.project import PROJECT_QUOTAS, project_sources

            try:
                project_sources(files)
                valid = len(html.encode()) <= PROJECT_QUOTAS["html_bytes"]
            except (ValueError, TypeError):
                valid = False
        checks.append(
            check_record(
                "module_paths",
                "passed" if valid else "failed",
                "Native source paths and byte limits",
                manifest,
            )
        )
        if not valid:
            errors.append("Invalid native source paths or byte limits")
        for name, source in files.items():
            if modular and not name.endswith((".js", ".css")):
                continue
            forbidden = source_findings(
                source, javascript=name.endswith(".js"), runtime_managed=True, modules=modular
            )
            checks.append(
                check_record(
                    "offline:" + name,
                    "failed" if forbidden else "passed",
                    name + ": local source policy",
                    manifest,
                )
            )
            if forbidden:
                errors.append(name + ": prohibited dynamic or external construct")
        node = shutil.which("node")
        if node and valid:
            with tempfile.TemporaryDirectory(prefix="p2p-static-parse-") as temporary:
                for name, source in files.items():
                    if not name.endswith(".js"):
                        continue
                    check_cancel(cancel)
                    path = Path(temporary) / (name + (".mjs" if modular else ""))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source, encoding="utf-8")
                    try:
                        parsed = subprocess.run(
                            [node, "--check", str(path)],
                            capture_output=True,
                            text=True,
                            timeout=15,
                            check=False,
                        )
                        parsed_ok = parsed.returncode == 0
                    except (OSError, subprocess.TimeoutExpired):
                        parsed_ok = False
                    message = name + ": syntax parses without executing generated code"
                    checks.append(
                        check_record(
                            "javascript_syntax:" + name,
                            "passed" if parsed_ok else "failed",
                            message,
                            manifest,
                            check_kind="syntax",
                        )
                    )
                    if not parsed_ok:
                        errors.append(
                            name + ": JavaScript syntax parser rejected source or timed out"
                        )
        return {
            "schema_version": 2,
            "artifact": manifest,
            "status": "failed" if errors else "unverified",
            "checks": checks,
            "errors": errors,
            "warnings": ["Static checks do not execute the game"],
        }

    @staticmethod
    def checked_report(
        value: Any,
        manifest: dict[str, Any],
        request_hash: str,
        suite: str,
        image_id: str,
        evidence_dir: Path,
        *,
        expected_harness: dict[str, str] | None = None,
        require_completion: bool = True,
    ) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 2
            or value.get("browser_contract_version") != BROWSER_CONTRACT_VERSION
            or value.get("artifact") != manifest
            or value.get("request_sha256") != request_hash
            or value.get("suite_sha256") != suite
            or value.get("validator_image_sha256") != image_id
            or value.get("completion_required", True) is not require_completion
        ):
            raise ValueError("Runtime identity mismatch")
        if expected_harness is not None and value.get("harness_files_sha256") != expected_harness:
            raise ValueError("Validator image contains outdated harness sources")
        checks = value.get("checks")
        if not isinstance(checks, list) or not 1 <= len(checks) <= 100:
            raise ValueError("Invalid bounded check list")
        names = set()
        for check in checks:
            if (
                not isinstance(check, dict)
                or check.get("status") not in {"passed", "failed", "skipped"}
                or check.get("artifact_sha256") != manifest["html_sha256"]
                or not isinstance(check.get("name"), str)
                or check["name"] in names
                or check.get("check_kind") not in {"browser", "scenario"}
            ):
                raise ValueError("Invalid browser observation")
            if len(canonical_json(check).encode()) > 16_000:
                raise ValueError("Oversized browser observation")
            names.add(check["name"])
            if check["name"].startswith("input:") and check["status"] == "passed":
                observed = check.get("evidence", {})
                if (
                    observed.get("actual_input") is not True
                    or observed.get("causal_control") is not True
                    or observed.get("state_changed") is not True
                    or observed.get("visible_changed") is not True
                    or type(observed.get("events")) is not int
                    or observed["events"] < 1
                ):
                    raise ValueError("Input lacked correlated real and visible observations")
        if not isinstance(value.get("errors"), list) or not isinstance(value.get("warnings"), list):
            raise ValueError("Invalid runtime diagnostics")
        evidence = value.get("evidence_files")
        if not isinstance(evidence, list) or not 6 <= len(evidence) <= 40:
            raise ValueError("Missing actual evidence files")
        total = 0
        evidence_names = set()
        for item in evidence:
            if (
                not isinstance(item, dict)
                or set(item) != {"path", "sha256", "bytes"}
                or not isinstance(item["path"], str)
                or not re.fullmatch(r"[a-z0-9_-]+\.(?:png|json|zip|txt)", item["path"])
                or item["path"] in evidence_names
            ):
                raise ValueError("Unsafe or repeated evidence file")
            path = evidence_dir / item["path"]
            if (
                path.is_symlink()
                or not path.is_file()
                or type(item["bytes"]) is not int
                or not 0 <= item["bytes"] <= MAX_EVIDENCE_BYTES
            ):
                raise ValueError("Invalid evidence file")
            total += item["bytes"]
            if total > MAX_EVIDENCE_BYTES:
                raise ValueError("Evidence byte budget exceeded")
            data = path.read_bytes()
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("Evidence file bytes do not match report")
            evidence_names.add(item["path"])
        expected_evidence = {
            f"{kind}-{width}.{extension}"
            for width in (1280, 390)
            for kind, extension in (
                ("start", "png"),
                ("final", "png"),
                ("restart", "png"),
                ("console", "json"),
                ("network", "json"),
                ("trace", "zip"),
            )
        }
        failed = any(check["status"] == "failed" for check in checks) or bool(value["errors"])
        skipped = any(
            check["status"] == "skipped"
            and not (
                not require_completion and check["name"] in {"completion:1280", "completion:390"}
            )
            for check in checks
        )
        if not failed and (
            not REQUIRED_CHECKS.issubset(names) or not expected_evidence.issubset(evidence_names)
        ):
            raise ValueError("Omitted mandatory browser checks or evidence")
        value["status"] = "failed" if failed else "unverified" if skipped else "passed"
        value["incomplete"] = (
            skipped
            or not REQUIRED_CHECKS.issubset(names)
            or not expected_evidence.issubset(evidence_names)
        )
        value["scope"] = {"isolated": True, "real_input": True, "webview": False}
        return value
