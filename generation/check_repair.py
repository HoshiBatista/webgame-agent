"""An application-issued permission to revise scenarios, never game source or requirements."""

import hashlib
import json
from copy import deepcopy

from .errors import ContractError
from .schema import validate_checks

IDENTITY = ("id", "category", "requirement", "viewport")
CHECK_FINDINGS = {
    "invalid_check",
    "check_unverified",
    "check_timeout",
    "incomplete_checks",
    "effect_mismatch",
    "surface_not_observed",
    "input_obstructed",
    "effect_not_causal",
}


def checks_hash(checks):
    return hashlib.sha256(json.dumps(checks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def needs_check_repair(checks, findings):
    codes = {item.get("code") for item in findings}
    # Infrastructure and proven game faults retain their own paths. A mismatch alone
    # cannot tell a bad move sequence from a broken game; source must stay unchanged.
    if codes and not codes.issubset(CHECK_FINDINGS):
        return False
    try:
        validate_checks(checks)
    except ContractError:
        return True
    return bool(codes)


def permission(artifact_hash, checks, design):
    requirements = [{key: check[key] for key in IDENTITY} for check in checks]
    ids = {r["id"] for r in requirements}
    if len(ids) != len(requirements):
        raise ContractError(
            "check_review_required", "Повторяющиеся ID проверок требуют ручного разбора; исходники сохранены."
        )
    categories = {r["category"] for r in requirements}
    missing = {
        "start": "Понятное начало игры согласно исходному запросу.",
        "control": "Реальный ввод управляет игрой: "
        + ("; ".join(design.get("controls", [])) or "механика из исходного запроса."),
        "outcome": "Достигается игровой исход: " + (design.get("outcome") or "условие из исходного запроса."),
    }
    for category, requirement in missing.items():
        if category in categories:
            continue
        ident = "required_" + category
        while ident in ids:
            ident += "_"
        ids.add(ident)
        requirements.append(
            {
                "id": ident,
                "category": category,
                "requirement": requirement[:500],
                "viewport": "mobile",
            }
        )
    if len(requirements) > 12:
        raise ContractError(
            "check_review_required", "Для обязательных условий недостаточно места в наборе проверок."
        )
    return {"artifact_hash": artifact_hash, "checks_hash": checks_hash(checks), "requirements": requirements}


def repaired_checks(response, *, base_revision, artifact_hash, previous_checks, policy):
    if not policy or response["base_revision"] != str(base_revision):
        raise ContractError("stale_revision", "Исправление проверок относится к другой версии игры.")
    if (
        response["artifact_hash"] != artifact_hash
        or policy["artifact_hash"] != artifact_hash
        or response["checks_hash"] != checks_hash(previous_checks)
        or policy["checks_hash"] != checks_hash(previous_checks)
    ):
        raise ContractError("stale_checks", "Изменились исходники или исходный набор проверок.")
    if response["status"] == "unchanged":
        return None
    checks = response["checks"]
    validate_checks(checks)
    expected = {r["id"]: r for r in policy["requirements"]}
    actual = {check["id"]: {key: check[key] for key in IDENTITY} for check in checks}
    if expected != actual:
        raise ContractError(
            "changed_requirement", "Нельзя удалять или менять ID, условия, категории и viewport проверок."
        )
    if checks == previous_checks:
        raise ContractError("no_changes", "Сценарии не изменились; исходники сохранены.")
    return deepcopy(checks)
