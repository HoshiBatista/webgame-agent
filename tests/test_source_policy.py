from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any, cast

import pytest

from prompt2play.contracts.source_policy import source_findings
from prompt2play.generation.runtime import assemble_runtime
from prompt2play.generation.workspace import GenerationControl, quick_check
from prompt2play.legacy.validator.checks import assemble, static_validate
from prompt2play.paths import LEGACY_ROOT, RESOURCE_ROOT
from prompt2play.validation.runner import IsolatedValidator


@pytest.mark.parametrize(
    "source",
    [
        "const api = {importSave(text) { return ctx.storage.import(text); }, exportSave() { return ctx.storage.export({phase:'ready'}); }};",
        "const names = {import: 'save', export: 'save'}; ctx.storage?.import(text);",
        "const methods = {import(text) {return text}, export() {return 'ok'}};",
        "// import forbidden from 'somewhere'; export default X;\n/* import('x') */ const text = 'export default';",
        "const pattern = /import\\(export\\)/; const msg = `A saved game ${ctx.storage.import(text).phase}`;",
        "const importSaved = x => x; const exportSaved = x => x; importSaved(exportSaved({}));",
    ],
)
def test_safe_storage_and_literal_text(source: str) -> None:
    assert not source_findings(source, runtime_managed=True)


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("import {X} from 'x';", "es_module_import"),
        ("import/* comment */('x')", "dynamic_import"),
        ("function f(){import('x')\n{let y=1}}", "dynamic_import"),
        ("function f(){import(url)\n{let y=1}}", "dynamic_import"),
        ("const text = `value ${import('x')}`", "dynamic_import"),
        ("export const X=1;", "es_module_export"),
        ("export {x};", "es_module_export"),
        ("import.meta.url", "es_module_import"),
        ("fetch /* comment */ ('x')", "external_execution"),
        ("new Function('return 1')", "dynamic_function"),
        ("document.write('<div/>')", "document_write"),
        ("navigator.sendBeacon('x','x')", "external_execution"),
        ("const t=`value ${`nested ${eval('1')}`}`", "external_execution"),
        ("requestAnimationFrame(()=>{})", "unmanaged_timer"),
        ("window.__GAME_TEST__.snapshot()", "runtime_access"),
        ("document.querySelector('#p2p-start')", "runtime_access"),
    ],
)
def test_actual_forbidden_constructs(source: str, code: str) -> None:
    assert code in {item.code for item in source_findings(source, runtime_managed=True)}


def test_findings_do_not_echo_source() -> None:
    source = "const secret = 'private-sensitive-string';\nfetch(secret);"
    findings = source_findings(source)
    assert [(item.code, item.offset) for item in findings] == [("external_execution", 43)]
    assert findings[0].message == "Forbidden external_execution at source line 2"
    assert "private" not in repr(findings)


def test_legacy_accepts_unmanaged_clock_and_bridge_but_native_rejects_them() -> None:
    source = "window.__GAME_TEST__ = {}; requestAnimationFrame(()=>{});"
    assert not source_findings(source)
    assert {f.code for f in source_findings(source, runtime_managed=True)} == {
        "runtime_access",
        "unmanaged_timer",
    }


def test_css_comments_and_offline_declarations() -> None:
    assert not source_findings(
        "/* @import 'https://example.invalid' */ .board{display:grid}", javascript=False
    )
    assert source_findings("@import 'local.css';", javascript=False)[0].code == "external_style"
    assert (
        source_findings(".x{background:url('https://example.invalid/a')}", javascript=False)[0].code
        == "external_style"
    )


def test_policy_findings_are_bounded() -> None:
    assert len(source_findings("fetch('x');" * 2000)) == 32


def test_reviewed_storage_source_passes_both_quick_and_native_static_policy() -> None:
    fixture = RESOURCE_ROOT / "runtime" / "examples" / "dom"
    files = {"game.js": (fixture / "game.js").read_text()}
    spec = json.loads((fixture / "spec.json").read_text())
    assert quick_check(files, GenerationControl.bounded()) == []
    report = IsolatedValidator._static(
        files, assemble_runtime(files, spec), spec, threading.Event()
    )
    assert not report["errors"]
    imported = {"game.js": files["game.js"] + "\nimport('local.js');"}
    blocked = IsolatedValidator._static(
        imported, assemble_runtime(imported, spec), spec, threading.Event()
    )
    assert any(
        check["name"] == "offline:game.js" and check["status"] == "failed"
        for check in blocked["checks"]
    )


def test_legacy_policy_accepts_storage_member_and_rejects_dynamic_import() -> None:
    fixture = LEGACY_ROOT / "reference" / "corpus" / "lamps"
    files = {
        name: (fixture / name).read_text()
        for name in ("engine.js", "renderer.js", "audio.js", "ui.js")
    }
    spec = json.loads((fixture / "spec.json").read_text())
    files["engine.js"] += (
        "\nfunction memberImportRegression(ctx,text){return ctx.storage.import(text);}"
    )
    assembler = cast(Callable[[dict[str, str], str], str], assemble)
    validate = cast(Callable[..., dict[str, Any]], static_validate)
    report = validate(files, assembler(files, spec["title"]), threading.Event(), spec=spec)
    assert all(
        check["status"] == "passed"
        for check in report["checks"]
        if check["name"].startswith("offline:")
    )
    files["engine.js"] += "\nimport('local.js');"
    report = validate(files, assembler(files, spec["title"]), threading.Event(), spec=spec)
    assert any(
        check["name"] == "offline:engine.js" and check["status"] == "failed"
        for check in report["checks"]
    )
