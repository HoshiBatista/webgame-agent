"""Pure atomic patches and deterministic, offline single-HTML packaging."""

import base64
import difflib
import hashlib
import html as html_module
import json
import posixpath
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from .errors import ContractError
from .schema import validate_checks, validate_response

MAX_TOTAL_BYTES = 1500000
ALLOWED_SUFFIXES = {".html", ".css", ".js", ".json", ".svg"}


def sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_path(path):
    if (
        not isinstance(path, str)
        or not path
        or "\\" in path
        or "\x00" in path
        or any(ord(c) < 32 for c in path)
    ):
        raise ContractError("unsafe_path", "Недопустимый путь игрового файла.")
    parsed = PurePosixPath(path)
    if (
        path.startswith("/")
        or any(p in {".", ".."} for p in path.split("/"))
        or ":" in path
        or parsed.suffix.lower() not in ALLOWED_SUFFIXES
    ):
        raise ContractError("unsafe_path", f"Файл вне допустимого игрового набора: {path[:120]}")
    return path


def normalize_files(files):
    if isinstance(files, list):
        result = {}
        for entry in files:
            path = safe_path(entry["path"])
            if path in result:
                raise ContractError("duplicate_file", "Повторяющийся путь в ответе модели.")
            result[path] = entry["content"]
    elif isinstance(files, dict):
        result = {safe_path(path): content for path, content in files.items()}
    else:
        raise ContractError("invalid_files", "Ожидался набор исходников игры.")
    if not all(isinstance(content, str) for content in result.values()):
        raise ContractError("invalid_content", "Игровые исходники должны быть текстовыми.")
    if len(result) > 20 or sum(len(c.encode()) for c in result.values()) > MAX_TOTAL_BYTES:
        raise ContractError("artifact_too_large", "Размер превышает формат небольшой автономной игры.")
    return result


def apply_patches(files, patches):
    original = normalize_files(files)
    result = dict(original)
    by_path: dict[str, list[dict[str, Any]]] = {}
    for patch_number, patch in enumerate(patches, 1):
        path = safe_path(patch["path"])
        by_path.setdefault(path, []).append(patch)
        if path not in original:
            if patch["file_hash"] is not None or patch["old_text"] or len(by_path[path]) != 1:
                raise ContractError(
                    "new_file_conflict", f"Новый файл {path} требует null hash и пустой old_text."
                )
            continue
        if patch["file_hash"] != sha256(original[path]):
            raise ContractError("stale_file", f"Hash исходного файла {path} не совпал; патч не применён.")
        old = patch["old_text"]
        if not old or original[path].count(old) != 1:
            count = original[path].count(old) if old else 0
            raise ContractError(
                "ambiguous_patch",
                f"Патч №{patch_number} в {path}: old_text должен совпадать ровно один раз; "
                f"найдено совпадений: {count}. Скопируйте уникальный фрагмент из переданного исходного файла точно, "
                "включая пробелы и переносы строк. Ни один патч из ответа не применён.",
            )
        if PurePosixPath(path).suffix in {".html", ".js"} and old.strip() == original[path].strip():
            raise ContractError(
                "whole_file_patch", f"Нужна локальная правка {path}, а не замена всего кода игры."
            )
    for path, group in by_path.items():
        if path not in original:
            result[path] = group[0]["new_text"]
            continue
        edits = [(original[path].index(p["old_text"]), len(p["old_text"]), p["new_text"]) for p in group]
        edits.sort(key=lambda e: e[0])
        for left, right in zip(edits, edits[1:]):
            if left[0] + left[1] > right[0]:
                raise ContractError("overlapping_patch", f"Патчи в {path} пересекаются.")
        content = original[path]
        for start, length, replacement in reversed(edits):
            content = content[:start] + replacement + content[start + length :]
        result[path] = content
    return normalize_files(result)


def _resource_path(value, containing):
    value = html_module.unescape(value)
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        raise ContractError("external_resource", f"Нужен локальный ресурс: {value[:120]}")
    path = posixpath.normpath(posixpath.join(posixpath.dirname(containing), unquote(parts.path)))
    return safe_path(path)


def _get(files, path):
    if path not in files:
        raise ContractError("missing_resource", f"Локальный файл {path} не найден.")
    return files[path]


def _attr(tag, name):
    found = re.search(r"\b" + name + r"\s*=\s*(?:([\"'])(.*?)\1|([^\s>]+))", tag, re.I | re.S)
    return (found.group(2) if found.group(1) else found.group(3)) if found else None


def _css(content, containing, files):
    if re.search(r"@import\b", content, re.I):
        raise ContractError("css_import", "Используйте локальный CSS без @import.")

    def replace(match):
        value = match.group(1).strip().strip("\"'")
        if value.startswith(("data:image/", "#")):
            return match.group(0)
        path = _resource_path(value, containing)
        if not path.endswith(".svg"):
            raise ContractError("unsupported_asset", "Текстовые локальные изображения должны быть SVG.")
        encoded = base64.b64encode(_get(files, path).encode()).decode()
        return f'url("data:image/svg+xml;base64,{encoded}")'

    return re.sub(r"url\((.*?)\)", replace, content, flags=re.I | re.S)


def bundle(files, *, script_map=None):
    files = normalize_files(files)
    document = _get(files, "index.html")
    if re.search(r"<(?:iframe|object|embed|base)\b", document, re.I):
        raise ContractError("embedded_document", "Игра должна быть автономной, без вложенных документов.")
    deferred = []
    immediate_maps, deferred_maps = [], []

    def script(match):
        tag, content = match.group(1), match.group(2)
        src = _attr(tag, "src")
        script_type = _attr(tag, "type")
        if script_type and script_type.lower() not in {"text/javascript", "application/javascript", "module"}:
            if src:
                path = _resource_path(src, "index.html")
                if script_type.lower() != "application/json" or not path.endswith(".json"):
                    raise ContractError(
                        "invalid_script", "Данные script src должны быть локальным application/json."
                    )
                content = _get(files, path)
                try:
                    json.loads(content)
                except ValueError as exc:
                    raise ContractError("invalid_data", f"Некорректные JSON-данные в {path}.") from exc
                tag = re.sub(
                    r"\s+src\s*=\s*(?:[\"](?:[^\"]*)[\"]|['](?:[^']*)[']|[^\s>]+)", "", tag, flags=re.I
                )
                return tag + content.replace("<", "\\u003c") + "</script>"
            return match.group(0)
        if script_type == "module":
            raise ContractError("module_import", "Используйте обычные script без модульной сборки.")
        if src:
            path = _resource_path(src, "index.html")
            if not path.endswith(".js"):
                raise ContractError("invalid_script", "Script src должен ссылаться на локальный JS.")
            content = _get(files, path)
        if re.search(
            r"\bimport\s*(?:\(|[\"'{*])|\bexport\s+(?:default|const|function|class|let|\{)", content
        ):
            raise ContractError(
                "module_import", "Автономная игра использует обычные script без модульных импортов."
            )
        original_content = content
        source_start = 0 if src else match.start(2)
        # A JS string containing an HTML closing tag must not terminate its container.
        content = re.sub(r"</script", r"<\/script", content, flags=re.I)
        bundled = "<script>" + content + "</script>"
        record = {"path": path if src else "index.html", "source_start": source_start,
                  "original": original_content, "generated": content}
        if src and re.search(r"\sdefer(?:\s|=|>)", tag, re.I):
            deferred.append(bundled)
            deferred_maps.append(record)
            return ""
        immediate_maps.append(record)
        return bundled

    document = re.sub(r"(<script\b[^>]*>)(.*?)</script\s*>", script, document, flags=re.I | re.S)
    if deferred:
        if re.search(r"</body\s*>", document, re.I):
            document = re.sub(
                r"</body\s*>", lambda _: "".join(deferred) + "</body>", document, count=1, flags=re.I
            )
        else:
            document += "".join(deferred)

    def link(match):
        tag = match.group(0)
        if (_attr(tag, "rel") or "").lower() != "stylesheet":
            raise ContractError("unsupported_link", "Удалите внешние и служебные link из автономной игры.")
        href = _attr(tag, "href")
        if not href:
            raise ContractError("missing_stylesheet", "Не задан путь CSS.")
        path = _resource_path(href, "index.html")
        content = _css(_get(files, path), path, files)
        return "<style>" + re.sub(r"</style", r"<\/style", content, flags=re.I) + "</style>"

    document = re.sub(r"<link\b[^>]*>", link, document, flags=re.I)
    document = re.sub(
        r"(<style\b[^>]*>)(.*?)</style\s*>",
        lambda m: m[1] + _css(m[2], "index.html", files) + "</style>",
        document,
        flags=re.I | re.S,
    )

    def image(match):
        tag = match.group(0)
        src = _attr(tag, "src")
        if not src:
            return tag
        if src.startswith("data:image/"):
            return tag
        path = _resource_path(src, "index.html")
        if not path.endswith(".svg"):
            raise ContractError("unsupported_asset", "Локальная графика: SVG, Canvas или data:image.")
        uri = "data:image/svg+xml;base64," + base64.b64encode(_get(files, path).encode()).decode()
        return tag.replace(src, uri)

    document = re.sub(r"<img\b[^>]*>", image, document, flags=re.I)
    # Reject external declarations; sandbox/CSP enforces dynamic network restrictions too.
    if re.search(r"(?:src|href|poster)\s*=\s*['\"]\s*(?:https?:|//|file:)", document, re.I):
        raise ContractError("external_resource", "Экспорт не должен зависеть от внешних ресурсов.")
    if script_map is not None:
        script_map.extend(immediate_maps + deferred_maps)
    return document


def materialize(response, *, operation, base_revision=None, files=None, previous_checks=None):
    validate_response(response, operation=operation)
    if response["status"] == "scope_refusal":
        raise ContractError("scope_refusal", response["message"])
    original = normalize_files(files) if files is not None else {}
    if response["status"] == "unchanged":
        if not original:
            raise ContractError("invalid_unchanged", "Нельзя сохранить игру без изменений до её создания.")
        if response["base_revision"] != str(base_revision):
            raise ContractError("stale_revision", "Ответ «без изменений» относится к другой версии игры.")
        return {"status": "unchanged", "message": response["message"]}
    if original:
        if operation == "repair":
            try:
                validate_checks(previous_checks or [])
            except ContractError as exc:
                raise ContractError(
                    "invalid_baseline_checks",
                    "Сохранённые проверки требуют отдельной проверки приложения; код игры не переписываем.",
                ) from exc
            previous = {check["id"]: check for check in previous_checks or []}
            if any(previous.get(check["id"]) != check for check in response["checks"]):
                raise ContractError(
                    "repair_checks_locked",
                    "Автоматическое исправление не может менять обязательные проверки. Верните checks=[].",
                )
        if response["operation"] not in {"edit", "repair"} or response["files"]:
            raise ContractError(
                "rewrite_disallowed", "Изменение существующей игры должно содержать только точные патчи."
            )
        if response["base_revision"] != str(base_revision):
            raise ContractError("stale_revision", "Патч относится к другой версии игры.")
        result = apply_patches(original, response["patches"])
    else:
        if response["operation"] != "create" or response["patches"] or response["base_revision"] is not None:
            raise ContractError(
                "invalid_create", "Новая игра должна содержать исходники без патчей к чужой версии."
            )
        result = normalize_files(response["files"])
    check_map = {c["id"]: c for c in response["checks"]}
    for old in previous_checks or []:
        if old["id"] in check_map:
            new = check_map[old["id"]]
            if operation != "edit" and (
                new["requirement"] != old["requirement"] or new["category"] != old["category"]
            ):
                raise ContractError(
                    "changed_requirement",
                    f"Нельзя незаметно удалить эффект {old['id']} при коррекции проверки.",
                )
        else:
            check_map[old["id"]] = old
    checks = list(check_map.values())
    validate_checks(checks)
    if original and result == original and check_map != {c["id"]: c for c in previous_checks or []}:
        raise ContractError(
            "test_only_change",
            "Изменены только проверки. Нужна отдельная проверка приложения; игра не объявляется исправленной.",
        )
    if original and result == original:
        raise ContractError(
            "no_changes",
            "Ответ заявляет об изменении, но исходники и проверки остались прежними. Верните нужный точный патч; если запрос уже реализован, используйте status=unchanged и объясните почему.",
        )
    document = bundle(result)
    changes: list[str] = []
    for path in sorted(set(result) | set(original)):
        if result.get(path) != original.get(path):
            changes.extend(
                difflib.unified_diff(
                    original.get(path, "").splitlines(True),
                    result.get(path, "").splitlines(True),
                    fromfile=path,
                    tofile=path,
                )
            )
    return {
        "files": result,
        "html": document,
        "artifact_hash": sha256(document),
        "file_hashes": {p: sha256(c) for p, c in result.items()},
        "design": response["design"],
        "checks": checks,
        "title": response["title"],
        "diff": "".join(changes),
    }
