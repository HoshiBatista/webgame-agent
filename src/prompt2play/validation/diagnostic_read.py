"""Bounded, read-only views of already authenticated browser evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any


def compact(value: Any, budget: int = 3000) -> Any:
    """A preview, never a replacement for the original JSON available by pointer."""
    if len(json.dumps(value, ensure_ascii=False)) <= budget:
        return value
    if budget < 80:
        return "<omitted from preview>"
    if isinstance(value, dict) and value:
        keys = list(value)[:20]
        return {k: compact(value[k], max(40, budget // len(keys) - len(k))) for k in keys}
    if isinstance(value, list) and value:
        return [compact(v, max(40, budget // min(8, len(value)))) for v in value[:8]]
    return str(value)[:budget] + "…"


def diagnostic_query(path: str, content: str) -> dict[str, Any]:
    query = json.loads(content) if content else {}
    if not isinstance(query, dict) or set(query) - {"diagnostic_key", "pointer", "offset", "limit"}:
        raise ValueError("Diagnostic content accepts only diagnostic_key, pointer, offset, limit")
    if len(path) > 200:
        raise ValueError("Diagnostic path is too long")
    if "diagnostic_key" in query and (
        not isinstance(query["diagnostic_key"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", query["diagnostic_key"])
    ):
        raise ValueError("Invalid diagnostic key")
    pointer = query.get("pointer", "")
    if not isinstance(pointer, str) or len(pointer) > 2000:
        raise ValueError("Invalid diagnostic pointer")
    for key, default, low, high in (("offset", 0, 0, 64_000_000), ("limit", 12000, 1, 16000)):
        value = query.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Invalid diagnostic {key}")
    return {"path": path, **query}


def select(value: Any, pointer: str) -> Any:
    if pointer and not pointer.startswith("/"):
        raise ValueError("pointer must be an RFC 6901 JSON Pointer")
    for part in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", part):
            raise ValueError("Invalid JSON Pointer escape")
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            if int(key) >= len(value):
                raise ValueError("JSON Pointer is not present")
            value = value[int(key)]
        else:
            raise ValueError("JSON Pointer is not present")
    return value


def read_evidence(
    report: dict[str, Any],
    read: Callable[[str], bytes],
    *,
    path: str = "",
    pointer: str = "",
    offset: int = 0,
    limit: int = 12000,
) -> dict[str, Any]:
    """The caller supplies only the current job's immutable diagnostic manifest."""
    entries = {item["path"]: item for item in report.get("evidence_files", [])}
    if not path:
        failures = []
        for name, entry in entries.items():
            match = re.fullmatch(r"inputs-(1280|390)(?:-[a-f0-9]{32})?\.json", name)
            if not match:
                continue
            data = json.loads(read(entry["object_key"]))
            failed_ids = {
                case["id"]
                for check in report.get("checks", [])
                if check["name"] == "mechanics:" + match[1]
                for case in check.get("evidence", {}).get("cases", [])
                if not case.get("passed")
            }
            failed_ids.update(
                check["evidence"]["case_id"]
                for check in report.get("checks", [])
                if check["name"].startswith("mechanic_case:" + match[1] + ":")
                and check.get("status") != "passed"
                and check.get("evidence", {}).get("case_id")
            )
            if any(
                check["name"] in ("input:" + match[1], "runtime_harness:" + match[1])
                and check.get("status") == "failed"
                for check in report.get("checks", [])
            ):
                failed_ids.add("")
            records = data.get("records", [])
            groups: dict[str, list[dict[str, Any]]] = {}
            for index, record in enumerate(records):
                case_id = record.get("case_id", "")
                if (
                    record.get("error")
                    or record.get("status") == "running"
                    or case_id in failed_ids
                ):
                    groups.setdefault(case_id, []).append(
                        {"pointer": f"/records/{index}", **record}
                    )
            for case_id, items in list(groups.items())[:4]:
                failures.append(
                    {
                        "path": name,
                        "case_id": case_id,
                        "preview_only": True,
                        "recent_steps": [compact(item, 1800) for item in items[-3:]],
                    }
                )
        return {
            "artifact": report.get("artifact"),
            "status": report.get("status"),
            "incomplete": report.get("incomplete", False),
            "files": [
                {k: entry[k] for k in ("path", "bytes", "sha256")}
                | {"readable": entry["path"].endswith((".json", ".txt", ".log"))}
                for entry in entries.values()
            ],
            "failure_previews": failures,
            "note": "Read exact JSON by path and pointer. Previews may omit data. Historical reports may lack input snapshots. Evidence describes the recorded artifact, not later edits. Binary screenshots/trace archives are listed but this operation reads text only.",
        }
    if path not in entries or not path.endswith((".json", ".txt", ".log")):
        raise ValueError("Choose a readable path from this diagnostic's inventory")
    entry = entries[path]
    raw = read(entry["object_key"]).decode("utf-8")
    value = select(json.loads(raw), pointer) if path.endswith(".json") else raw
    if pointer and not path.endswith(".json"):
        raise ValueError("JSON Pointer requires a JSON evidence file")
    content = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if offset > len(content):
        raise ValueError("offset exceeds selected content length")
    end = min(len(content), offset + limit)
    return {
        "path": path,
        "sha256": entry["sha256"],
        "pointer": pointer,
        "offset": offset,
        "total_chars": len(content),
        "next_offset": end if end < len(content) else None,
        "content": content[offset:end],
    }
