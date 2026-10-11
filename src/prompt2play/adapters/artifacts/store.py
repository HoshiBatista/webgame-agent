"""Hash-addressed, atomic storage with recoverable prepared commits.

Only coordinator-owned paths are used; game filenames are data inside a bundle.
The database stores intent ids and hashes, never generated source bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import TypeAlias, cast

JSON: TypeAlias = str | int | float | bool | list["JSON"] | dict[str, "JSON"] | None
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_INTENT = re.compile(r"[a-f0-9]{32}\Z")


def canonical(value: JSON) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ArtifactCorruptError(ValueError):
    """Content has changed or a store path is unsafe."""


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects = self.root / "objects"
        self.pending = self.root / "pending"
        for directory in (self.objects, self.pending):
            if directory.is_symlink():
                raise ArtifactCorruptError("Artifact directory cannot be a symlink.")
            directory.mkdir(exist_ok=True)

    def _object(self, key: str) -> Path:
        if not _DIGEST.fullmatch(key):
            raise ValueError("Invalid content digest.")
        return self.objects / key

    def _intent(self, intent: str) -> Path:
        if not _INTENT.fullmatch(intent):
            raise ValueError("Invalid commit intent.")
        return self.pending / intent

    @staticmethod
    def _read(path: Path) -> bytes:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            return stream.read()

    @staticmethod
    def _sync(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _create(cls, path: Path, data: bytes) -> None:
        temporary = path.parent / f".{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Publish only complete bytes, without overwriting an existing object.
            os.link(temporary, path, follow_symlinks=False)
            cls._sync(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def prepare(self, value: JSON) -> tuple[str, str]:
        data = canonical(value)
        intent = uuid.uuid4().hex
        self._create(self._intent(intent), data)
        return intent, digest(data)

    def commit(self, intent: str, key: str) -> str:
        target = self._object(key)
        draft = self._intent(intent)
        if target.exists() or target.is_symlink():
            self.read(key)
        else:
            data = self._read(draft)
            if digest(data) != key:
                raise ArtifactCorruptError("Prepared artifact differs from its commit intent.")
            try:
                self._create(target, data)
            except FileExistsError:
                self.read(key)
        draft.unlink(missing_ok=True)
        self._sync(self.pending)
        return key

    def put_bytes(self, data: bytes) -> str:
        key = digest(data)
        target = self._object(key)
        try:
            self._create(target, data)
        except FileExistsError:
            self.read(key)
        return key

    def read(self, key: str) -> bytes:
        data = self._read(self._object(key))
        if digest(data) != key:
            raise ArtifactCorruptError("Stored artifact digest does not match its bytes.")
        return data

    def read_json(self, key: str) -> dict[str, JSON]:
        value = json.loads(self.read(key))
        if not isinstance(value, dict):
            raise ArtifactCorruptError("Artifact bundle must be an object.")
        return cast(dict[str, JSON], value)
