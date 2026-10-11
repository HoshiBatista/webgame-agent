"""Select short lessons by mechanics/findings, with auditable source provenance."""

from __future__ import annotations

import json
from typing import Any

from prompt2play.paths import RESOURCE_ROOT

KNOWLEDGE_VERSION = "knowledge-v1"


def select_lessons(
    spec: dict[str, Any], findings: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads(
        (RESOURCE_ROOT / "knowledge" / "lessons.json").read_text(encoding="utf-8")
    )
    text = " ".join(
        str(spec.get(key, "")) for key in ("genre", "rules", "actions", "invariants")
    ).lower()
    capabilities = set(spec.get("capabilities", []))
    codes = {str(finding.get("code", "")) for finding in findings or []}
    return [
        entry
        for entry in entries
        if any(term.lower() in text for term in entry["mechanic_terms"])
        or capabilities.intersection(entry["capabilities"])
        or codes.intersection(entry["finding_codes"])
    ]
