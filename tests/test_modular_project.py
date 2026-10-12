"""Source envelopes and opt-in isolated compilation; generated JS never runs on host."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from prompt2play.generation.project import bundle_project, compiler_identity, project_sources
from prompt2play.generation.runtime import assemble_runtime, capture_runtime_identity
from prompt2play.paths import RESOURCE_ROOT
from prompt2play.validation import IsolatedValidator


@pytest.mark.parametrize(
    "name,source",
    [
        ("../escape.js", "export const x=1"),
        ("package.json", "{}"),
        ("esbuild.config.js", "throw 1"),
        ("x.svg", "<svg><script>bad()</script></svg>"),
        ("x.js", "fetch('https://example.org')"),
        ("x.js", "import('./module.js')"),
        ("x.json", '{"a":NaN}'),
        ("x.png", "invalid"),
    ],
)
def test_modular_source_rejects_escape_configuration_active_svg_network_and_bad_data(
    name: str, source: str
) -> None:
    with pytest.raises(ValueError):
        project_sources({"game.js": "export function createGame(ctx) {}", name: source})


@pytest.mark.skipif(
    os.environ.get("P2P_RUN_ISOLATED_BROWSER") != "1",
    reason="Explicit Docker compiler and isolated browser required",
)
def test_multimodule_game_and_embedded_assets_compile_deterministically_and_pass_browser(
    tmp_path: Path,
) -> None:
    root = RESOURCE_ROOT / "runtime/examples/dom"
    files = {
        "game.js": "import {makeGame} from './rules.js'; import emblem from './art/emblem.svg'; import palette from './content.json'; export function createGame(ctx){return makeGame(ctx);}",
        "rules.js": (root / "game.js")
        .read_text()
        .replace("function createGame(ctx)", "export function makeGame(ctx)"),
        "content.json": '{"tone":"warm"}',
        "art/emblem.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="gold"/></svg>',
        "style.css": "button {border-radius: 8px; background-image:url(./art/emblem.svg)}",
    }
    identity = compiler_identity()
    compiled = bundle_project(files, identity)
    assert (
        compiled == bundle_project(files, identity)
        and "data:image/svg+xml" in compiled["style.css"]
    )
    spec: dict[str, Any] = json.loads((root / "spec.json").read_text())
    spec.update(
        format="runtime-modules-v2",
        packager=identity,
        runtime=capture_runtime_identity(),
        input_acceptance=json.loads((root / "acceptance.json").read_text()),
    )
    html = assemble_runtime(files, spec)
    report = IsolatedValidator(
        os.environ.get("P2P_VALIDATOR_IMAGE", "prompt2play-validator:adaptive")
    ).validate(files, html, spec, threading.Event(), tmp_path)
    assert report["status"] == "passed", report
    for imported in ("../validator/package.json", "esbuild", "https://example.org/a.js"):
        with pytest.raises(ValueError):
            bundle_project(
                {
                    **files,
                    "game.js": "import x from "
                    + json.dumps(imported)
                    + "; export function createGame(ctx){return x(ctx)}",
                },
                identity,
            )
