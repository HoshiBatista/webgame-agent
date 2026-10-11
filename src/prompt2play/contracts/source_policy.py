"""Lexical offline checks; execution isolation remains the security boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceViolation:
    code: str
    offset: int
    message: str


@dataclass(frozen=True)
class _Token:
    text: str
    offset: int
    literal: bool = False
    member_context: bool = False


_IDENTIFIER = re.compile(r"(?:[^\W\d]|[$_])(?:\w|[$])*", re.UNICODE)
_EXTERNAL = frozenset(
    {
        "fetch",
        "eval",
        "WebSocket",
        "XMLHttpRequest",
        "EventSource",
        "Worker",
        "SharedWorker",
        "importScripts",
        "sendBeacon",
    }
)
_TIMERS = frozenset({"requestAnimationFrame", "setTimeout", "setInterval"})
_REGEXP_PREFIX = frozenset(
    {"(", "[", "{", "=", ":", ";", ",", "!", "?", "&", "|", "return", "throw", "case", "=>"}
)
_PROTECTED = re.compile(r"__GAME_TEST__|Prompt2PlayRuntime|p2p-(?:status|start|restart)")


def _tokens(source: str) -> list[_Token]:
    """Skip comments/literal text while retaining executable template interpolations."""
    result: list[_Token] = []
    length = len(source)

    def quoted(index: int, quote: str) -> int:
        start = index
        index += 1
        while index < length:
            if source[index] == "\\":
                index += 2
            elif source[index] == quote:
                index += 1
                break
            else:
                index += 1
        result.append(_Token(source[start:index], start, True))
        return index

    def template(index: int, depth: int) -> int:
        start = segment = index
        index += 1
        while index < length:
            if source[index] == "\\":
                index += 2
            elif source[index] == "`":
                result.append(_Token(source[segment : index + 1], segment, True))
                return index + 1
            elif source.startswith("${", index):
                result.append(_Token(source[segment:index], segment, True))
                result.append(_Token("{", index + 1))
                index = code(index + 2, stop=True, depth=depth + 1)
                segment = index
            else:
                index += 1
        result.append(_Token(source[segment:index], start, True))
        return index

    def regexp(index: int) -> int:
        start = index
        index += 1
        bracket = False
        while index < length and source[index] not in "\r\n":
            char = source[index]
            if char == "\\":
                index += 2
                continue
            if char == "[":
                bracket = True
            elif char == "]":
                bracket = False
            elif char == "/" and not bracket:
                index += 1
                while index < length and source[index].isalpha():
                    index += 1
                result.append(_Token(source[start:index], start, True))
                return index
            index += 1
        result.append(_Token("/", start))
        return start + 1

    def code(index: int, *, stop: bool = False, depth: int = 0) -> int:
        if depth > 64:
            raise ValueError("Template nesting exceeds the source-policy bound")
        braces = 0
        brace_kinds: list[str] = []
        while index < length:
            char = source[index]
            if char.isspace():
                index += 1
                continue
            if source.startswith("//", index):
                end = source.find("\n", index + 2)
                index = length if end < 0 else end + 1
                continue
            if source.startswith("/*", index):
                end = source.find("*/", index + 2)
                index = length if end < 0 else end + 2
                continue
            if char in "\"'":
                index = quoted(index, char)
                continue
            if char == "`":
                index = template(index, depth)
                continue
            if char == "/" and (not result or result[-1].text in _REGEXP_PREFIX):
                index = regexp(index)
                continue
            match = _IDENTIFIER.match(source, index)
            if match:
                result.append(
                    _Token(
                        match.group(),
                        index,
                        member_context=bool(brace_kinds and brace_kinds[-1] in {"object", "class"}),
                    )
                )
                index = match.end()
                continue
            if char == "}" and stop and braces == 0:
                result.append(_Token("}", index))
                return index + 1
            if char == "{":
                braces += 1
                previous = result[-1].text if result else ""
                recent = [token.text for token in result[-8:]]
                brace_kinds.append(
                    "object"
                    if previous in {"=", "(", "[", ":", "return", ","}
                    else "class"
                    if "class" in recent and previous != "=>"
                    else "block"
                )
            elif char == "}":
                braces -= 1
                if brace_kinds:
                    brace_kinds.pop()
            if source.startswith("=>", index):
                result.append(_Token("=>", index))
                index += 2
            else:
                result.append(_Token(char, index))
                index += 1
        return index

    code(0)
    return result


def source_findings(
    source: str, *, javascript: bool = True, runtime_managed: bool = False
) -> list[SourceViolation]:
    """Return bounded construct labels/offsets, never payload excerpts or secrets."""
    findings: list[SourceViolation] = []

    def finding(code: str, offset: int) -> None:
        if len(findings) < 32:
            line = source.count("\n", 0, offset) + 1
            findings.append(
                SourceViolation(code, offset, f"Forbidden {code} at source line {line}")
            )

    if not javascript:
        visible = re.sub(r"/\*[\s\S]*?\*/", lambda m: " " * len(m.group()), source)
        for match in re.finditer(r"@import\b|https?://|<script\b", visible):
            finding("external_style", match.start())
        if runtime_managed:
            for match in _PROTECTED.finditer(visible):
                finding("runtime_access", match.start())
        return findings
    try:
        tokens = _tokens(source)
    except ValueError:
        finding("source_complexity", 0)
        return findings

    def method(index: int) -> bool:
        if (
            index == 0
            or not tokens[index].member_context
            or tokens[index - 1].text not in {"{", ",", "async", "get", "set", "static"}
            or index + 2 >= len(tokens)
            or tokens[index + 1].text != "("
            or tokens[index + 2].literal
        ):
            return False
        nesting = 0
        for end in range(index + 1, min(index + 257, len(tokens))):
            nesting += tokens[end].text == "("
            nesting -= tokens[end].text == ")"
            if nesting == 0:
                return end + 1 < len(tokens) and tokens[end + 1].text == "{"
        return False

    for index, token in enumerate(tokens):
        previous = tokens[index - 1].text if index else ""
        following = tokens[index + 1].text if index + 1 < len(tokens) else ""
        if token.literal:
            if re.search(r"https?://|<script\b", token.text):
                finding("external_literal", token.offset)
            if runtime_managed and _PROTECTED.search(token.text):
                finding("runtime_access", token.offset)
            continue
        if (
            token.text in {"import", "export"}
            and previous != "."
            and following != ":"
            and not method(index)
        ):
            finding(
                "dynamic_import"
                if token.text == "import" and following == "("
                else "es_module_" + token.text,
                token.offset,
            )
        if token.text in _EXTERNAL and following == "(":
            finding("external_execution", token.offset)
        if token.text == "Function" and previous == "new" and following == "(":
            finding("dynamic_function", token.offset)
        if (
            token.text == "write"
            and previous == "."
            and index >= 2
            and tokens[index - 2].text == "document"
            and following == "("
        ):
            finding("document_write", token.offset)
        if runtime_managed and (
            _PROTECTED.search(token.text) or (token.text in _TIMERS and following == "(")
        ):
            finding(
                "runtime_access" if _PROTECTED.search(token.text) else "unmanaged_timer",
                token.offset,
            )
    return findings
