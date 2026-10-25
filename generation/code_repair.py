"""Frozen application permission to repair code while inheriting incomplete checks."""

from jsonschema import Draft202012Validator

from .check_repair import checks_hash
from .errors import ContractError
from .schema import CHECK_SCHEMA

DEFECTS = {"javascript_syntax", "runtime_or_network", "mobile_overflow"}


def inherit_checks(basis, *, base_revision, artifact_hash, checks):
    if not isinstance(basis, dict) or (
        basis.get("base_revision") != str(base_revision) or basis.get("artifact_hash") != artifact_hash
        or basis.get("checks_hash") != checks_hash(checks)
        or type(basis.get("report_id")) is not int or basis["report_id"] <= 0
        or not isinstance(basis.get("report_identity"), str) or not basis["report_identity"]
        or not basis.get("defects") or not set(basis["defects"]).issubset(DEFECTS)
    ):
        raise ContractError("invalid_code_repair_basis", "Нет разрешения исправлять эту базу кода.")
    validator = Draft202012Validator(CHECK_SCHEMA)
    if not isinstance(checks, list) or len(checks) > 12 or any(not validator.is_valid(c) for c in checks):
        raise ContractError("invalid_baseline_checks", "Повреждена структура исходных проверок.")
    # Identity duplicates and missing semantic categories remain visible to review.
    return True
