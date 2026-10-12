"""Deterministic, integrity-bound standalone packaging. Never evaluates sources."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Any

from prompt2play.contracts.models import stable
from prompt2play.paths import RESOURCE_ROOT

RUNTIME_VERSION = "runtime-v1.0.7"
PACKAGER_VERSION = "runtime-packager-v1"
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"


def trusted_runtime(expected_digest: str | None = None) -> dict[str, str]:
    root = RESOURCE_ROOT / "runtime"
    names = ("runtime-v1.js", "runtime-v1.css")
    current = {name: (root / name).read_text(encoding="utf-8") for name in names}
    current_digest = hashlib.sha256(stable(current).encode()).hexdigest()
    if expected_digest is None or expected_digest == current_digest:
        return current
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise ValueError("Runtime digest changed or is invalid; create a new child revision")
    archive = root / "versions" / expected_digest
    try:
        frozen = {name: (archive / name).read_text(encoding="utf-8") for name in names}
    except OSError as exc:
        raise ValueError("Runtime digest changed and its frozen version is unavailable") from exc
    if hashlib.sha256(stable(frozen).encode()).hexdigest() != expected_digest:
        raise ValueError("Frozen trusted runtime digest was tampered")
    return frozen


def runtime_digest() -> str:
    return hashlib.sha256(stable(trusted_runtime()).encode()).hexdigest()


def capture_runtime_identity() -> dict[str, str]:
    """Version and digest come from the same source snapshot, never module state."""
    return _source_identity(trusted_runtime())


def _source_identity(sources: dict[str, str]) -> dict[str, str]:
    version = re.search(
        r'const VERSION = "(runtime-v[0-9]+\.[0-9]+\.[0-9]+)";', sources["runtime-v1.js"]
    )
    if version is None:
        raise ValueError("Trusted runtime has no supported version identity")
    return {
        "version": version.group(1),
        "sha256": hashlib.sha256(stable(sources).encode()).hexdigest(),
    }


def assemble_runtime(
    files: dict[str, str], spec: dict[str, Any], *, expected_runtime_digest: str | None = None
) -> str:
    """Trusted coordinator can reproduce these bytes from a bounded submission."""
    runtime_reference = spec.get("runtime") or {}
    if not isinstance(runtime_reference, dict):
        raise ValueError("Runtime reference must be an object")
    requested_digest = expected_runtime_digest or runtime_reference.get("sha256")
    runtime = trusted_runtime(requested_digest)
    identity = _source_identity(runtime)
    if runtime_reference and runtime_reference.get("version") != identity["version"]:
        raise ValueError("Declared runtime version does not match its exact trusted sources")
    if runtime_reference and runtime_reference.get("sha256") != identity["sha256"]:
        raise ValueError("Declared runtime digest does not match its exact trusted sources")
    if not files.get("game.js", "").strip():
        raise ValueError("runtime-v1 requires game.js")
    if spec.get("format") == "runtime-modules-v2":
        from .project import bundle_project

        files = bundle_project(files, spec.get("packager", {}))
    if set(files) - {"game.js", "style.css"}:
        raise ValueError("runtime-v1 allows only game.js and optional style.css")
    script = runtime["runtime-v1.js"] + "\n" + files["game.js"]
    script += "\nwindow.Prompt2PlayRuntime.install(createGame, " + stable(spec) + ");"
    script = re.sub(r"</script", r"<\\/script", script, flags=re.I)
    style = runtime["runtime-v1.css"] + "\n" + files.get("style.css", "")
    style = re.sub(r"</style", r"<\\/style", style, flags=re.I)
    title = html.escape(str(spec["title"])[:160])
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{html.escape(CSP, quote=True)}"><title>{title}</title><style>{style}</style></head><body><main id="game-root"></main><script>{script}</script></body></html>'
