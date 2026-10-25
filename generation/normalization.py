"""Narrow, audited compatibility for complete JSON; never repairs game logic."""

from copy import deepcopy

VERSION = 1


def normalize_response(response):
    """Return a copy and changed paths. The strict contract must still validate it."""
    result = deepcopy(response)
    changed: list[str] = []
    if not isinstance(result, dict):
        return result, changed
    # A known status alias is unambiguous only when canonical status is absent.
    if "status" not in result and result.get("type") in ("ok", "scope_refusal", "unchanged"):
        result["status"] = result.pop("type")
        changed.append("type->status")
    if result.get("status") in ("ok", "unchanged") and "scope_refusal" in result and result["scope_refusal"] is None:
        del result["scope_refusal"]
        changed.append("scope_refusal(null)")
    if result.get("operation") == "create" and isinstance(result.get("files"), list):
        for i, item in enumerate(result["files"]):
            if isinstance(item, dict) and "file_hash" in item and item["file_hash"] is None:
                del item["file_hash"]
                changed.append(f"files.{i}.file_hash(null)")
    if isinstance(result.get("checks"), list):
        for i, item in enumerate(result["checks"]):
            if isinstance(item, dict) and item.get("title") == "":
                del item["title"]
                changed.append(f"checks.{i}.title(empty)")
    # No blanket deletion of unknown fields, filling missing requirements,
    # coercing types, truncating code, altering patches or weakening checks.
    return result, changed
