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
