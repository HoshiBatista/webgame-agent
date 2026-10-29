"""An application-issued permission to revise scenarios, never game source or requirements."""

import hashlib
import json
from copy import deepcopy

from .errors import ContractError
from .schema import validate_checks

IDENTITY = ("id", "category", "requirement", "viewport")
CHECK_FINDINGS = {
    "requirement_manifest_mismatch",
    "invalid_check",
    "check_unverified",
    "check_timeout",
    "incomplete_checks",
    "missing_effects",
    "missing_mobile_start",
    "missing_mobile_control",
    "missing_keyboard_control",
    "effect_mismatch",
    "surface_not_observed",
    "input_obstructed",
    "effect_not_causal",
}


def checks_hash(checks):
    return hashlib.sha256(json.dumps(checks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def merge_checks(previous, incoming):
    """An explicit edit replaces an ID, but never silently deduplicates a suite."""
    changed = {check["id"] for check in incoming}
    return deepcopy(incoming + [check for check in previous if check["id"] not in changed])


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


def permission(artifact_hash, checks, design, manifest=None, *, protected_ids=()):
    requirements: list[dict[str, str]] = []
    identities: dict[tuple, str] = {}
    repairs = []
    frozen = (manifest or {}).get("requirements", [])
    ids = {check["id"] for check in checks} | {r["id"] for r in frozen}
    for index, check in enumerate(checks):
        identity = tuple(check[key] for key in IDENTITY)
        if identity in identities:
            # Multiple scenarios for the exact same promise are supplied in full
            # as context, but request one replacement scenario for that promise.
            ident = identities[identity]
        else:
            ident = check["id"]
            if any(r["id"] == ident for r in requirements):
                suffix = 2
                while f"{ident[:30]}_check{suffix}" in ids:
                    suffix += 1
                ident = f"{ident[:30]}_check{suffix}"
                ids.add(ident)
            identities[identity] = ident
            requirements.append({**{key: check[key] for key in IDENTITY}, "id": ident})
        repairs.append({"source_index": index, "source_id": check["id"], "requirement_id": ident})
    if frozen:
        # The pre-code promises take precedence over a model's altered check identity.
        required = {r["id"]: {key: r[key] for key in IDENTITY} for r in frozen}
        requirements = list(required.values()) + [r for r in requirements if r["id"] not in required]
        ids = {r["id"] for r in requirements}
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
    # New mobile coverage must not rewrite an inherited desktop assertion.
    for category in ("start", "control"):
        if any(r["category"] == category and r["viewport"] == "mobile" for r in requirements):
            continue
        original = next(r for r in requirements if r["category"] == category)
        ident = "required_mobile_" + category
        while ident in ids:
            ident += "_"
        ids.add(ident)
        requirements.append({**original, "id": ident, "viewport": "mobile"})
    require_keyboard = bool(design.get('assets'))
    if require_keyboard and not any(r['category'] == 'control' and r['viewport'] == 'desktop' for r in requirements):
        ident = 'required_keyboard_control'
        while ident in ids:
            ident += '_'
        requirements.append({'id': ident, 'category': 'control', 'viewport': 'desktop',
                             'requirement': 'Реальное управление с клавиатуры вызывает игровой эффект без мыши.'})
    if len(requirements) > 12:
        raise ContractError(
            "check_review_required", "Для обязательных условий недостаточно места в наборе проверок."
        )
    policy = {"artifact_hash": artifact_hash, "checks_hash": checks_hash(checks), "requirements": requirements,
              "identity_repairs": repairs, "require_keyboard": require_keyboard}
    if protected_ids:
        validate_checks(checks)
        expected = {r['id']: r for r in requirements}
        protected = [c for c in checks if c['id'] in protected_ids]
        if len(protected) != len(set(protected_ids)) or any(
            {key: c[key] for key in IDENTITY} != expected.get(c['id']) for c in protected
        ):
            raise ContractError('stale_checks', 'Нельзя закрепить сценарий с изменившимся условием.')
        policy['protected_checks'] = deepcopy(protected)
    return policy


def scoped_response(response, *, previous_checks, policy):
    """Retain already verified scenarios; never repair their meaning from model text.

    Call after wire-schema validation. The raw reply remains immutable, and the
    caller records every retained original in the response audit metadata.
    """
    protected = policy.get('protected_checks', []) if policy else []
    if not protected or response['status'] == 'unchanged':
        return response, []
    if response['checks_hash'] != checks_hash(previous_checks) or policy['checks_hash'] != checks_hash(previous_checks):
        raise ContractError('stale_checks', 'Изменился исходный набор проверок.')
    original = {c['id']: c for c in previous_checks}
    if len(original) != len(previous_checks) or any(original.get(c['id']) != c for c in protected):
        raise ContractError('stale_checks', 'Закреплённые сценарии не совпадают с исходными.')
    expected = {r['id']: r for r in policy['requirements']}
    incoming = {c['id']: c for c in response['checks']}
    if len(incoming) != len(response['checks']) or expected != {
        ident: {key: c[key] for key in IDENTITY} for ident, c in incoming.items()
    }:
        raise ContractError('changed_requirement', 'Нельзя удалять или менять условия проверок.')
    locked = {c['id']: c for c in protected}
    retained = [c['id'] for c in response['checks'] if c['id'] in locked and c != locked[c['id']]]
    result = deepcopy(response)
    result['checks'] = [deepcopy(locked.get(c['id'], c)) for c in response['checks']]
    return result, retained


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
    if policy.get('require_keyboard'):
        from validation.contracts import suite_findings

        missing = suite_findings(checks, require_keyboard=True)
        if missing:
            raise ContractError(missing[0]['code'], missing[0]['message'])
    expected = {r["id"]: r for r in policy["requirements"]}
    actual = {check["id"]: {key: check[key] for key in IDENTITY} for check in checks}
    if expected != actual:
        raise ContractError(
            "changed_requirement", "Нельзя удалять или менять ID, условия, категории и viewport проверок."
        )
    if checks == previous_checks:
        raise ContractError("no_changes", "Сценарии не изменились; исходники сохранены.")
    return deepcopy(checks)
