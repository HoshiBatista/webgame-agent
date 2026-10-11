"""Filesystem integrity and crash recovery tests; no generated code executes."""

from pathlib import Path

import pytest

from prompt2play.adapters.artifacts.store import ArtifactCorruptError, ArtifactStore


def test_prepared_commit_is_recoverable_and_duplicate_safe(tmp_path: Path) -> None:
    first = ArtifactStore(tmp_path)
    intent, key = first.prepare({"html": "<p>fixture</p>", "files": {}})
    recovered = ArtifactStore(tmp_path)
    assert recovered.commit(intent, key) == key
    assert recovered.commit(intent, key) == key
    assert recovered.read_json(key)["html"] == "<p>fixture</p>"
    assert not (tmp_path / "pending" / intent).exists()


def test_tampered_object_and_pending_bytes_are_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    intent, key = store.prepare({"x": 1})
    (tmp_path / "pending" / intent).write_bytes(b"corrupt")
    with pytest.raises(ArtifactCorruptError):
        store.commit(intent, key)
    key = store.put_bytes(b"fixture")
    (tmp_path / "objects" / key).write_bytes(b"corrupt")
    with pytest.raises(ArtifactCorruptError):
        store.read(key)


def test_store_rejects_traversal_and_symlinks(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError):
        store.read("../outside")
    with pytest.raises(ValueError):
        store.commit("../outside", "a" * 64)
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    (tmp_path / "objects" / ("a" * 64)).symlink_to(outside)
    with pytest.raises(OSError):
        store.read("a" * 64)


def test_directory_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "objects").symlink_to(target)
    with pytest.raises(ArtifactCorruptError):
        ArtifactStore(tmp_path)


def test_interrupted_publication_never_leaves_partial_object(tmp_path: Path) -> None:
    from unittest.mock import patch

    store = ArtifactStore(tmp_path)
    intent, key = store.prepare({"html": "complete bytes"})
    with (
        patch("os.link", side_effect=InterruptedError("authored interruption")),
        pytest.raises(InterruptedError),
    ):
        store.commit(intent, key)
    assert not (tmp_path / "objects" / key).exists()
    assert (tmp_path / "pending" / intent).exists()
    assert store.commit(intent, key) == key
    assert store.read_json(key)["html"] == "complete bytes"
    assert not list((tmp_path / "objects").glob(".*.tmp"))


def test_simultaneous_identical_object_publication(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    store = ArtifactStore(tmp_path)

    def publish(_: int) -> str:
        return store.put_bytes(b"same complete authored bytes")

    with ThreadPoolExecutor(max_workers=4) as executor:
        keys = list(executor.map(publish, range(4)))
    assert len(set(keys)) == 1
    assert store.read(keys[0]) == b"same complete authored bytes"
