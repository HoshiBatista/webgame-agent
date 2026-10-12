"""Offline modular compilation in a pinned, unprivileged, networkless container."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict, cast

from prompt2play.contracts.models import stable
from prompt2play.contracts.source_policy import source_findings

PROJECT_FORMAT = "runtime-modules-v2"


class ProjectQuotas(TypedDict):
    version: str
    files: int
    file_bytes: int
    total_bytes: int
    html_bytes: int


PROJECT_QUOTAS: ProjectQuotas = {
    "version": "project-quotas-v2",
    "files": 32,
    "file_bytes": 2_000_000,
    "total_bytes": 4_000_000,
    "html_bytes": 8_000_000,
}
COMPILER_VERSION = "esbuild-0.25.12"


def project_sources(files: dict[str, str]) -> dict[str, bytes]:
    from .workspace import normalized_path

    if not files.get("game.js", "").strip() or len(files) > PROJECT_QUOTAS["files"]:
        raise ValueError("A modular project needs game.js and at most 32 files")
    if sum(len(s.encode()) for s in files.values()) > PROJECT_QUOTAS["total_bytes"]:
        raise ValueError(
            "Project exceeds 4 MB; split or compress content without dropping requirements"
        )
    result = {}
    for name, source in files.items():
        normalized_path(name, allow_assets=True)
        if (
            Path(name).name in ("package.json", "tsconfig.json", "jsconfig.json")
            or ".config." in name
        ):
            raise ValueError("Generated compiler configuration and dependencies are forbidden")
        if not source.strip() or len(source.encode()) > PROJECT_QUOTAS["file_bytes"]:
            raise ValueError("Project file exceeds its 2 MB quota: " + name)
        if name.endswith(".png"):
            from .images import ImageInput

            data = base64.b64decode(source, validate=True)
            ImageInput(Path(name).name, data).metadata()
        else:
            data = source.encode()
            if name.endswith(".json"):
                stable(json.loads(source))
            elif name.endswith(".svg"):
                visible = re.sub(r'xmlns=["\']http://www.w3.org/2000/svg["\']', "", source)
                if re.search(
                    r"<script|foreignObject|\bon\w+\s*=|https?://|<!DOCTYPE|<!ENTITY", visible, re.I
                ):
                    raise ValueError("SVG contains active or external content: " + name)
            else:
                violations = source_findings(
                    source, javascript=name.endswith(".js"), runtime_managed=True, modules=True
                )
                if violations:
                    raise ValueError(name + ": " + violations[0].message)
        result[name] = data
    return result


def compiler_identity(image: str | None = None) -> dict[str, str]:
    docker = shutil.which("docker")
    if not docker:
        raise ValueError(
            "Isolated modular compiler is unavailable; build the configured packager image"
        )
    configured = image or os.environ.get(
        "PROMPT2PLAY_PACKAGER_IMAGE", "prompt2play-validator:adaptive"
    )
    try:
        result = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", configured],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Modular compiler environment is unavailable; preserve the draft") from exc
    image_id = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise ValueError("Configured modular compiler image is unavailable")
    _preflight_compiler(docker, image_id)
    return {
        "version": COMPILER_VERSION,
        "image": image_id,
        "quotas": str(PROJECT_QUOTAS["version"]),
    }


@lru_cache(maxsize=8)
def _preflight_compiler(docker: str, image_id: str) -> None:
    try:
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
                image_id,
                "node",
                "-e",
                "require('fs').accessSync('/validator/packager.mjs'); process.stdout.write(require('esbuild').version)",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Modular compiler preflight failed before generation") from exc
    if result.returncode or "esbuild-" + result.stdout.strip() != COMPILER_VERSION:
        raise ValueError("Pinned esbuild compiler is missing or incompatible")


def bundle_project(files: dict[str, str], identity: dict[str, Any]) -> dict[str, str]:
    project_sources(files)
    configured = compiler_identity()
    archived = os.environ.get("PROMPT2PLAY_PACKAGER_ARCHIVE_IMAGES", "").split(",")
    if any(value and not re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in archived):
        raise ValueError("Archived compiler identities must be immutable image digests")
    allowed = {configured["image"], *archived}
    if (
        identity.get("version") != COMPILER_VERSION
        or identity.get("quotas") != PROJECT_QUOTAS["version"]
        or identity.get("image") not in allowed
    ):
        raise ValueError(
            "Compiler identity is not operator-approved; preserve the old version or create a child revision"
        )
    return dict(_compile(stable(files), str(identity["image"])))


@lru_cache(maxsize=16)
def _compile(serialized: str, image: str) -> tuple[tuple[str, str], ...]:
    sources = project_sources(json.loads(serialized))
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Isolated modular compiler unavailable")
    with tempfile.TemporaryDirectory(prefix="p2p-project-") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        for name, data in sources.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o644)
        container = "p2p-pack-" + uuid.uuid4().hex
        command = [
            docker,
            "run",
            "--rm",
            "--name=" + container,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=10001:10001",
            "--memory=256m",
            "--cpus=1",
            "--pids-limit=64",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=32m",
            "-v",
            str(root) + ":/input:ro",
            image,
            "node",
            "/validator/packager.mjs",
        ]
        # Bound output on disk while the isolated compiler runs; never collect an
        # arbitrarily large stdout pipe in the API process.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if (
                        time.monotonic() - started > 20
                        or os.fstat(stdout.fileno()).st_size > PROJECT_QUOTAS["html_bytes"]
                        or os.fstat(stderr.fileno()).st_size > 100_000
                    ):
                        raise ValueError(
                            "Compiler resource quota exceeded; source remains available"
                        )
                    time.sleep(0.05)
                stdout.seek(0)
                stderr.seek(0)
                data = stdout.read(PROJECT_QUOTAS["html_bytes"] + 1)
                error = stderr.read(100_000).decode(errors="replace")
                if process.returncode or len(data) > PROJECT_QUOTAS["html_bytes"]:
                    raise ValueError("Modular compile rejected: " + error[-1500:])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                    subprocess.run(
                        [docker, "rm", "-f", container],
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
    value = json.loads(data)
    if set(value) != {"game.js", "style.css"} or any(
        not isinstance(s, str) for s in value.values()
    ):
        raise ValueError("Isolated compiler returned an invalid envelope")
    return tuple(sorted(cast(dict[str, str], value).items()))
