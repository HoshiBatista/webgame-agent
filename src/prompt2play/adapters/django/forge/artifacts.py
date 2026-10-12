"""Byte identity for saved game evidence; does not execute or trust game code.

Kept dependency-free for the coordinator image. Its canonicalization is checked
against validator.evidence in the cross-component regression suite.
"""

import copy
import hashlib
import json


def artifact_manifest(files, html, spec):
    if (
        not isinstance(files, dict)
        or not isinstance(html, str)
        or not isinstance(spec, dict)
        or any(
            not isinstance(name, str) or not isinstance(source, str)
            for name, source in files.items()
        )
    ):
        raise ValueError("Для манифеста нужны строки исходников, HTML и объект спецификации.")
    encoded = html.encode("utf-8")
    canonical = json.dumps(
        spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return {
        "html_sha256": hashlib.sha256(encoded).hexdigest(),
        "html_bytes": len(encoded),
        "files_sha256": {
            name: hashlib.sha256(source.encode("utf-8")).hexdigest()
            for name, source in sorted(files.items())
        },
        "spec_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def require_report_binding(files, html, spec, report):
    if not isinstance(report, dict) or report.get("schema_version") != 2:
        raise ValueError(
            "Новая версия требует отчёт schema_version=2. Обновите исполнителя Game Forge."
        )
    manifest = artifact_manifest(files, html, spec)
    if report.get("artifact") != manifest:
        raise ValueError(
            "HTML, исходники или спецификация отличаются от проверенных байтов. Повторите проверку сборки."
        )
    for check in report.get("checks", []):
        if check.get("artifact_sha256") != manifest["html_sha256"]:
            raise ValueError("Результат проверки относится к другой сборке HTML.")
    if spec.get("mechanics_required") and report.get("status") == "passed":
        from prompt2play.contracts.mechanics import validate_mechanics

        cases = validate_mechanics(
            spec.get("mechanics_acceptance"), spec.get("mechanics_required_actions", [])
        )
        expected = {case["id"]: case["actions"] for case in cases}
        for width in (1280, 390):
            checks = [c for c in report.get("checks", []) if c.get("name") == f"mechanics:{width}"]
            if len(checks) != 1 or checks[0].get("status") != "passed":
                raise ValueError("Missing required basic mechanics evidence")
            evidence = checks[0].get("evidence", {})
            observed = evidence.get("cases", [])
            if (
                evidence.get("actual_input") is not True
                or len(observed) != len(expected)
                or {c.get("id"): c.get("actions") for c in observed} != expected
                or any(
                    c.get("passed") is not True or c.get("visible_changed") is not True
                    for c in observed
                )
            ):
                raise ValueError("Incomplete basic mechanics coverage")
    review = report.get("review")
    if review is not None and review.get("artifact_sha256") != manifest["html_sha256"]:
        raise ValueError("Ревью модели относится к другой сборке HTML.")
    generation = spec.get("generation", {})
    if (
        review is not None
        and isinstance(generation, dict)
        and generation.get("contract_sha256")
        and review.get("contract_sha256") != generation["contract_sha256"]
    ):
        raise ValueError("Ревью использует другую версию контракта генерации.")
    return manifest


def report_for_read(report):
    """Historic rows remain immutable; the API annotates their missing evidence."""
    value = copy.deepcopy(report) if isinstance(report, dict) else {}
    if value.get("schema_version") != 2:
        value["status"] = "failed" if value.get("status") == "failed" else "partial"
        value.setdefault("checks", [])
        value.setdefault("errors", [])
        warnings = value.setdefault("warnings", [])
        message = "Историческая версия: отчёт не привязан к хешам HTML, исходников и спецификации."
        if message not in warnings:
            warnings.append(message)
        value["binding_status"] = "legacy"
    return value
