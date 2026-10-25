"""Conservative source admission and bounded, application-owned repair permissions."""

import hashlib
import re

from bs4 import BeautifulSoup

from .errors import ContractError

MAX_MODULE_BYTES = 12 * 1024
MODULE_POLICY_VERSION = 1
JAVASCRIPT_TYPES = {"", "text/javascript", "application/javascript"}


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


def module_policy(files, findings):
    """Select a small file named by actual findings, or the only JS gameplay module."""
    eligible = {p: hashlib.sha256(content.encode()).hexdigest() for p, content in files.items()
                if p.endswith((".js", ".css", ".json")) and len(content.encode()) <= MAX_MODULE_BYTES}
    defects = [f for f in findings if f.get("code") in {"javascript_syntax", "runtime_or_network",
               "effect_mismatch", "canvas_missing", "mobile_overflow"}]
    located = [f for f in defects if f.get("path") or f.get("file")]
    selected = next((p for f in located if (p := f.get("path") or f.get("file")) in eligible
                     and f.get("file_hash", eligible[p]) == eligible[p]), None)
    if not located and any(f.get("code") in {"effect_mismatch", "canvas_missing", "runtime_or_network"}
                           for f in findings):
        scripts = [p for p in files if p.endswith(".js")]
        if len(scripts) == 1 and scripts[0] in eligible:
            selected = scripts[0]
    return {"version": MODULE_POLICY_VERSION, "max_bytes": MAX_MODULE_BYTES,
            "files": {selected: eligible[selected]} if selected else {}}
