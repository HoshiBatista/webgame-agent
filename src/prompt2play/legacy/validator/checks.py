from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from prompt2play.contracts.source_policy import source_findings
from prompt2play.legacy.worker.core import (
    FILES,
    ProviderError,
    check_cancel,
    validate_semantic_contract,
)
from .evidence import artifact_manifest, check_record
from .scenarios import validate_scenarios

CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"


def validate_files(files):
    if not isinstance(files, dict) or set(files) != set(FILES):
        raise ValueError("Exactly engine.js, renderer.js, audio.js and ui.js are required")
    for name, source in files.items():
        if not isinstance(source, str) or not source.strip() or len(source.encode()) > 180_000:
            raise ValueError(f"Invalid or oversized module: {name}")
    if sum(len(s.encode()) for s in files.values()) > 600_000:
        raise ValueError("Combined source exceeds 600 KB")


def assembled_script(files):
    script = '"use strict";\n(() => {\n' + "\n".join(files[n] for n in FILES)
    script += '\nconst __mounted = mountGame(document.getElementById("game-root"));\n})();'
    # HTML parsing happens before JavaScript parsing, including inside strings.
    return re.sub(r"</script", r"<\\/script", script, flags=re.I)


def assemble(files, title):
    validate_files(files)
    script = assembled_script(files)
    name = html.escape(str(title)[:160], quote=True)
    return f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{html.escape(CSP, quote=True)}"><title>{name}</title><style>html,body{{margin:0;min-height:100%;background:#101318;color:#eee}}#game-root{{min-height:100dvh}}</style></head><body><main id="game-root"></main><script>{script}</script></body></html>'


def static_validate(files, artifact, cancel, *, spec=None):
    checks, errors, warnings = [], [], []
    manifest = artifact_manifest(files, artifact, spec or {})

    def result(name, ok, message, *, kind="static", affected=None, command=None, evidence=None):
        checks.append(
            check_record(
                name,
                "passed" if ok else "failed",
                message,
                manifest,
                check_kind=kind,
                affected_files=affected,
                command=command,
                evidence=evidence,
                limitations=["Source and syntax checks do not execute the game or prove behavior"]
                if kind in {"static", "syntax"}
                else [],
            )
        )
        if not ok:
            errors.append(message)

    def report():
        return dict(
            schema_version=2,
            artifact=manifest,
            status="failed" if errors else "partial",
            checks=checks,
            errors=errors,
            warnings=warnings,
        )

    try:
        validate_files(files)
        result("module_paths", True, "Four whitelisted, bounded source modules")
    except ValueError as exc:
        result("module_paths", False, str(exc))
        return report()
    inline = re.fullmatch(r"[\s\S]*?<script>([\s\S]*)</script>[\s\S]*", artifact)
    result(
        "single_script",
        len(re.findall(r"<script\b", artifact, re.I)) == 1
        and len(re.findall(r"</script\s*>", artifact, re.I)) == 1,
        "HTML must contain exactly one inline script",
    )
    result(
        "artifact_sources",
        bool(inline) and inline.group(1) == assembled_script(files),
        "The script extracted from the delivered HTML must exactly match the assembled source modules",
        kind="provenance",
        affected=list(FILES),
    )
    if spec is not None and "title" in spec:
        result(
            "artifact_assembly",
            artifact == assemble(files, spec["title"]),
            "The exact delivered HTML must match the standard assembler and frozen specification",
            kind="provenance",
            affected=list(FILES),
        )
    for name, source in files.items():
        bad = source_findings(source)
        result(
            "offline:" + name,
            not bad,
            name
            + (
                ": external/dynamic execution construct detected"
                if bad
                else ": no prohibited external-code constructs found"
            ),
            affected=[name],
        )
    expected = {
        "engine.js": r"\bclass\s+GameEngine\b",
        "renderer.js": r"\bclass\s+GameRenderer\b",
        "audio.js": r"\bclass\s+GameAudio\b",
        "ui.js": r"\b(?:function\s+mountGame|(?:const|let)\s+mountGame\s*=)",
    }
    for name, pattern in expected.items():
        result(
            "interface:" + name,
            bool(re.search(pattern, files[name])),
            name + ": required interface declaration",
            affected=[name],
        )
    result(
        "test_bridge",
        "__GAME_TEST__" in files["ui.js"] and "data-testid" in files["ui.js"],
        "UI must expose the test bridge and start selector",
        affected=["ui.js"],
    )
    node = shutil.which("node")
    if node:
        with tempfile.TemporaryDirectory(prefix="forge-syntax-") as directory:
            individual_failed = False
            sources = dict(files)
            if inline:
                sources["assembled.js"] = inline.group(1)
            for name, source in sources.items():
                if name == "assembled.js" and individual_failed:
                    continue
                path = Path(directory) / name
                path.write_text(source, encoding="utf-8")
                check_cancel(cancel)
                try:
                    # --check parses; it never evaluates ANY generated statement.
                    run = subprocess.run(
                        [node, "--check", str(path)], capture_output=True, text=True, timeout=15
                    )
                    detail = run.stderr.replace(directory, "<syntax>")[-1800:]
                    result(
                        "javascript_syntax:" + name,
                        run.returncode == 0,
                        name + ": parses successfully" if not run.returncode else detail,
                        kind="syntax",
                        affected=[name] if name in FILES else list(FILES),
                        command="node --check " + name,
                    )
                    if run.returncode:
                        individual_failed = True
                except subprocess.TimeoutExpired:
                    result(
                        "javascript_syntax:" + name,
                        False,
                        name + ": syntax parser exceeded 15 second limit",
                        kind="syntax",
                        affected=[name] if name in FILES else list(FILES),
                        command="node --check " + name,
                    )
                    individual_failed = True
    else:
        checks.append(
            check_record(
                "javascript_syntax",
                "skipped",
                "Node unavailable; no syntax parser was run",
                manifest,
                check_kind="syntax",
            )
        )
        warnings.append("JavaScript syntax was not checked")
    warnings.append(
        "Static scanning is not a sandbox or proof of behavior; generated JavaScript was not executed on the host"
    )
    return report()


def validate(
    files,
    artifact,
    cancel,
    runtime=False,
    image="game-forge-validator:local",
    smoke_actions=None,
    *,
    qa_scenarios=None,
    spec=None,
):
    report = static_validate(files, artifact, cancel, spec=spec)
    manifest = report["artifact"]
    scenarios = []
    if qa_scenarios is not None:
        try:
            scenarios = validate_scenarios(qa_scenarios)
            report["checks"].append(
                check_record(
                    "qa_declarations",
                    "passed",
                    f"{len(scenarios)} bounded declarative scenarios; no executable test source",
                    manifest,
                    check_kind="static",
                    limitations=[
                        "Valid declarations do not prove that scenarios passed or cover every rule"
                    ],
                    evidence={"scenario_ids": [scenario["id"] for scenario in scenarios]},
                )
            )
        except (ValueError, TypeError) as exc:
            message = "Invalid QA declaration: " + str(exc)
            report["errors"].append(message)
            report["checks"].append(
                check_record("qa_declarations", "failed", message, manifest, check_kind="static")
            )
            report["status"] = "failed"
    contract = (spec or {}).get("semantic_contract")
    if isinstance(contract, dict) and contract.get("version") == 3:
        from prompt2play.legacy.worker.semantics import validate_semantic_coverage

        try:
            validate_semantic_contract(contract)
            coverage = validate_semantic_coverage(contract, scenarios)
            report["checks"].append(
                check_record(
                    "semantic_coverage",
                    "passed",
                    "State, transaction and persistence obligations have bounded declared QA references",
                    manifest,
                    check_kind="static",
                    evidence=coverage,
                    limitations=[
                        "These are declaration bindings; runtime results and semantic correctness require separate evidence"
                    ],
                )
            )
        except (ProviderError, ValueError, TypeError, KeyError, RecursionError) as exc:
            message = "Invalid semantic QA coverage: " + str(exc)
            report["errors"].append(message)
            report["checks"].append(
                check_record(
                    "semantic_coverage",
                    "failed",
                    message,
                    manifest,
                    check_kind="static",
                    limitations=["No runtime coverage is implied by a contract validation failure"],
                )
            )
            report["status"] = "failed"
    if report["errors"]:
        return report
    if not runtime:
        report["checks"].append(
            check_record(
                "isolated_browser_runtime",
                "skipped",
                "Docker validation not enabled; no browser executed",
                manifest,
                check_kind="browser",
            )
        )
        for scenario in scenarios:
            report["checks"].append(
                check_record(
                    "scenario:" + scenario["id"],
                    "skipped",
                    "Declared scenario was not executed; isolated browser validation is disabled",
                    manifest,
                    check_kind="scenario",
                    scenario_id=scenario["id"],
                    affected_files=scenario["affected_files"],
                    limitations=scenario["limitations"],
                    evidence={"category": scenario["category"], "seed": scenario["seed"]},
                )
            )
        report["warnings"].append(
            "Gameplay, visual animation, audio and mobile behavior require isolated browser validation"
        )
        return report
    from .docker import run_validation

    extra = run_validation(
        artifact,
        smoke_actions or [],
        cancel,
        image=image,
        qa_scenarios=scenarios,
        spec=spec or {},
        manifest=manifest,
    )
    report["checks"].extend(extra["checks"])
    report["errors"].extend(extra["errors"])
    report["warnings"].extend(extra["warnings"])
    report["status"] = (
        "failed"
        if report["errors"]
        else "partial"
        if any(c["status"] == "skipped" for c in report["checks"])
        else "passed"
    )
    return report
