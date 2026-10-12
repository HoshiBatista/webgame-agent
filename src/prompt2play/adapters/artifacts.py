"""Content-addressed immutable game artifact storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from prompt2play.contracts import GameSpec

MAX_HTML_BYTES = 512_000


@dataclass(frozen=True)
class StoredArtifact:
    """Opaque digest and size returned after an atomic commit."""

    digest: str
    size_bytes: int


class ArtifactStore:
    """Persist immutable single-file games below a configured root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.objects = self.root / "objects" / "sha256"
        self.staging = self.root / "staging"
        self.private = self.root / "private"
        for directory in (self.objects, self.staging, self.private):
            directory.mkdir(parents=True, exist_ok=True)

    def _object_dir(self, digest: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Invalid artifact digest")
        return self.objects / digest[:2] / digest[2:4] / digest

    def commit(self, html: str, spec: GameSpec, run_id: UUID) -> StoredArtifact:
        """Write, hash and atomically publish a complete artifact directory."""

        html_bytes = html.encode("utf-8")
        if len(html_bytes) > MAX_HTML_BYTES:
            raise ValueError(f"Game exceeds the {MAX_HTML_BYTES}-byte artifact limit")
        digest = hashlib.sha256(html_bytes).hexdigest()
        target = self._object_dir(digest)
        if target.is_dir():
            return StoredArtifact(digest=digest, size_bytes=len(html_bytes))

        work = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=self.staging))
        try:
            index_path = work / "index.html"
            index_path.write_bytes(html_bytes)
            manifest = {
                "schema_version": "1",
                "entry_point": "index.html",
                "template_profile": "canvas2d-single-html-v1",
                "game": {
                    "title": spec.title,
                    "genre": spec.genre,
                    "audience": spec.audience,
                    "controls": spec.controls,
                },
                "bridge_version": "1",
                "files": [{"path": "index.html", "sha256": digest, "bytes": len(html_bytes)}],
            }
            (work / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(work, target)
            except FileExistsError:
                shutil.rmtree(work, ignore_errors=True)
            return StoredArtifact(digest=digest, size_bytes=len(html_bytes))
        finally:
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)

    def read_html(self, digest: str) -> str:
        """Read a previously committed entry point without accepting paths."""

        path = self._object_dir(digest) / "index.html"
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("Artifact entry point does not exist")
        return path.read_text(encoding="utf-8")

    def entrypoint_path(self, digest: str) -> Path:
        """Resolve a verified immutable entry point for the isolated runner."""

        path = self._object_dir(digest) / "index.html"
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("Artifact entry point does not exist")
        return path

    def write_validation(self, revision_id: UUID, report: dict[str, object]) -> None:
        """Persist private validation evidence outside the immutable bundle."""

        directory = self.private / str(revision_id) / "validation"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "report.json.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(directory / "report.json")
