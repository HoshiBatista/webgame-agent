"""Conservative source admission and bounded, application-owned repair permissions."""

import hashlib
import re

from bs4 import BeautifulSoup

from .errors import ContractError

MAX_MODULE_BYTES = 12 * 1024
MODULE_POLICY_VERSION = 1
JAVASCRIPT_TYPES = {"", "text/javascript", "application/javascript"}


def source_diagnostics(files):
    """A suspicious comment tail is a warning, never a guessed source rewrite."""
    result = []
    for path, source in files.items():
        if not path.endswith('.js'):
            continue
        quote, escaped = None, False
        index = 0
        while index < len(source) - 1:
            char = source[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in {'"', "'", '`'}:
                quote = char
            elif source[index:index+2] == '/*':
                end = source.find('*/', index+2)
                index = len(source) if end < 0 else end+1
            elif source[index:index+2] == '//':
                end = re.search(r'[\r\n\u2028\u2029]', source[index:])
                if end:
                    index += end.start()
                else:
                    tail = source[index:]
                    if len(tail) >= 200 and len(tail) > len(source) / 2 and re.search(
                        r'\bfunction\b|=>|\baddEventListener\b|\brequestAnimationFrame\b', tail
                    ):
                        result.append({'path': path, 'file_hash': hashlib.sha256(source.encode()).hexdigest(),
                                       'code': 'commented_implementation_suspected',
                                       'comment_offset': index, 'comment_characters': len(tail),
                                       'source_characters': len(source),
                                       'message': 'Большой хвост похожего на код текста находится внутри // без переноса. Не восстанавливайте границы по догадке.'})
                    break
            index += 1
    return result[:3]


def has_code(source):
    """Recognize only an empty/comment-only payload, without parsing or executing JS."""
    remaining = source.lstrip("\ufeff \t\r\n")
    while remaining:
        if remaining.startswith(("//", "<!--", "-->")):
            parts = re.split(r"[\r\n\u2028\u2029]", remaining, maxsplit=1)
            remaining = parts[1].lstrip() if len(parts) == 2 else ""
        elif remaining.startswith("/*"):
            _, closing, remaining = remaining.partition("*/")
            if not closing:
                # An unterminated comment is a syntax error, not a missing implementation.
                return True
            remaining = remaining.lstrip()
        else:
            return True
    return False


def require_implementation(document):
    """A script may create Canvas dynamically; completeness is not gameplay approval."""
    soup = BeautifulSoup(document, "html.parser")
    if any(has_code(script.get_text()) for script in soup.find_all("script")
           if str(script.get("type", "")).lower() in JAVASCRIPT_TYPES):
        return
    if any(has_code(value) for tag in soup.find_all(True) for name, value in tag.attrs.items()
           if name.lower().startswith("on") and isinstance(value, str)):
        return
    raise ContractError(
        "incomplete_sources",
        "В исходниках нет исполняемой реализации игры: только разметка, данные или комментарии. "
        "Верните полный index.html и весь связанный код в files, а не патч к заглушке.",
    )


def module_policy(files, findings, *, allowed_paths=None):
    """Select a small file named by actual findings, or the only JS gameplay module."""
    eligible = {p: hashlib.sha256(content.encode()).hexdigest() for p, content in files.items()
                if (allowed_paths is None or p in allowed_paths)
                and p != "gf-motion-v1.js" and p.endswith((".js", ".css", ".json")) and len(content.encode()) <= MAX_MODULE_BYTES}
    defects = [f for f in findings if f.get("code") in {"javascript_syntax", "runtime_or_network",
               "effect_mismatch", "canvas_missing", "mobile_overflow", "module_not_registered", "control_obstructed"}]
    located = [f for f in defects if f.get("path") or f.get("file")]
    selected = next((p for f in located if (p := f.get("path") or f.get("file")) in eligible
                     and f.get("file_hash", eligible[p]) == eligible[p]), None)
    if not located and any(f.get("code") in {"effect_mismatch", "canvas_missing", "runtime_or_network"}
                           for f in findings):
        scripts = [p for p in files if p.endswith(".js") and p != "gf-motion-v1.js"
                   and (allowed_paths is None or p in allowed_paths)]
        if len(scripts) == 1 and scripts[0] in eligible:
            selected = scripts[0]
    return {"version": MODULE_POLICY_VERSION, "max_bytes": MAX_MODULE_BYTES,
            "files": {selected: eligible[selected]} if selected else {},
            "scope": "single_module" if selected else "patch"}
