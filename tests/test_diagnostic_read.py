"""Read-only JSON selection tests; authored data is not browser evidence."""

import hashlib
import json
from typing import Any

import pytest

from prompt2play.validation.diagnostic_read import compact, diagnostic_query, read_evidence, select


def fixture() -> tuple[dict[str, Any], bytes]:
    raw = json.dumps(
        {
            "records": [
                {
                    "case_id": "trade",
                    "step": 2,
                    "snapshot": {"ui": {"selection": "ship", "message": "я" * 20000}},
                    "status": "failed",
                    "error": "covered",
                }
            ]
        }
    ).encode()
    return {
        "artifact": {"html_sha256": "a" * 64},
        "checks": [],
        "evidence_files": [
            {
                "path": "inputs-390.json",
                "object_key": "fixture",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        ],
    }, raw


def test_precise_json_pointer_and_paging_preserve_utf8_and_original_bytes() -> None:
    report, raw = fixture()

    def read(_: str) -> bytes:
        return raw

    index = read_evidence(report, read)
    assert index["failure_previews"][0]["recent_steps"][0]["error"] == "covered"
    assert "object_key" not in json.dumps(index)
    chunks, offset = [], 0
    while True:
        part = read_evidence(
            report,
            read,
            path="inputs-390.json",
            pointer="/records/0/snapshot/ui/message",
            offset=offset,
            limit=1000,
        )
        assert len(part["content"]) <= 1000
        chunks.append(part["content"])
        if part["next_offset"] is None:
            break
        offset = part["next_offset"]
    assert json.loads("".join(chunks)) == "я" * 20000
    assert select({"a/b": {"~": 42}}, "/a~1b/~0") == 42
    with pytest.raises(ValueError, match="inventory"):
        read_evidence(report, read, path="../../credentials.json")
    with pytest.raises(ValueError, match="offset"):
        read_evidence(report, read, path="inputs-390.json", offset=999999)


@pytest.mark.parametrize("pointer", ["records", "/records/999", "/records/-1", "/~3", "/missing"])
def test_invalid_pointer(pointer: str) -> None:
    with pytest.raises(ValueError):
        select({"records": [1]}, pointer)


@pytest.mark.parametrize(
    "query",
    [
        {"lease_token": "x"},
        {"limit": 16001},
        {"offset": -1},
        {"offset": True},
        {"pointer": 1},
        {"diagnostic_key": "arbitrary"},
        [],
    ],
)
def test_operation_query_rejects_fence_overrides_and_unbounded_reads(query: Any) -> None:
    with pytest.raises(ValueError):
        diagnostic_query("inputs-390.json", json.dumps(query))


def test_small_values_and_empty_or_text_evidence() -> None:
    assert compact({"x": 1}) == {"x": 1}
    assert (
        len(
            json.dumps(
                compact(
                    {str(i): {str(j): "x" * 1000 for j in range(100)} for i in range(100)}, 1000
                )
            )
        )
        < 5000
    )
    assert diagnostic_query("", "") == {"path": ""}
    report = {
        "evidence_files": [{"path": "stderr.txt", "object_key": "x", "sha256": "x", "bytes": 3}]
    }
    assert read_evidence(report, lambda _: b"abc", path="stderr.txt")["content"] == '"abc"'
    with pytest.raises(ValueError, match="requires"):
        read_evidence(report, lambda _: b"abc", path="stderr.txt", pointer="/a")
