"""Content-addressed immutable game artifact storage."""

from __future__ import annotations

import errno
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


class ArtifactIntegrityError(ValueError):
    """Stored bytes no longer match their immutable artifact identity."""


@dataclass(frozen=True)
class StoredArtifact:
    """Opaque digest and size returned after an atomic commit."""

    digest: str
    size_bytes: int


class ArtifactStore:
    """Persist immutable single-file games below a configured root."""

    def __init__(self, root: Path, validation_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.objects = self.root / "objects" / "sha256"
        self.staging = self.root / "staging"
        self.validation_root = (validation_root or self.root / "private").resolve()
        for directory in (self.objects, self.staging):
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
            self._verified_bytes(digest)
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
                "bridge_version": "2",
                "files": [{"path": "index.html", "sha256": digest, "bytes": len(html_bytes)}],
            }
            (work / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(work, target)
            except OSError as exc:
                if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                # Another writer won the race. Never accept a partial/corrupt winner.
                self._verified_bytes(digest)
                shutil.rmtree(work, ignore_errors=True)
            return StoredArtifact(digest=digest, size_bytes=len(html_bytes))
        finally:
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)

    def _verified_bytes(self, digest: str) -> tuple[Path, bytes]:
        """Check containment, size and identity before trusting a stored artifact."""
        path = self._object_dir(digest) / "index.html"
        if not path.resolve().is_relative_to(self.root) or any(
            item.is_symlink() for item in (path, *path.parents) if item.is_relative_to(self.root)
        ):
            raise ArtifactIntegrityError("Artifact path is not an immutable local object")
        if not path.is_file():
            raise FileNotFoundError("Artifact entry point does not exist")
        with path.open("rb") as stream:
            content = stream.read(MAX_HTML_BYTES + 1)
        if len(content) > MAX_HTML_BYTES or hashlib.sha256(content).hexdigest() != digest:
            raise ArtifactIntegrityError("Artifact content does not match its SHA-256 identity")
        return path, content

    def read_html(self, digest: str) -> str:
        """Return only bytes matching the requested validated artifact identity."""
        return self._verified_bytes(digest)[1].decode("utf-8")

    def entrypoint_path(self, digest: str) -> Path:
        """Resolve a verified immutable entry point for the isolated runner."""

        return self._verified_bytes(digest)[0]

    def write_validation(self, revision_id: UUID, report: dict[str, object]) -> None:
        """Persist private validation evidence outside the immutable bundle."""

        directory = self.validation_root / str(revision_id) / "validation"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "report.json.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(directory / "report.json")
