"""Map observed export coordinates through the exact packager, never guess source."""

import re
from copy import deepcopy
from typing import Any

from validation.syntax import Scripts

from .artifacts import bundle, sha256
from .errors import ContractError

VERSION = 1


def _offset(text, line, column, *, utf16=True):
    if type(line) is not int or type(column) is not int or min(line, column) < 1:
        return None
    rows = text.split("\n")
    if line > len(rows):
        return None
    row, target = rows[line - 1], column - 1
    if utf16:
        used = 0
        for index, char in enumerate(row):
            if used == target:
                target = index
                break
            used += len(char.encode("utf-16-le")) // 2
        else:
            if used != target:
                return None
            target = len(row)
    if target > len(row):
        return None
    return sum(len(row) + 1 for row in rows[:line - 1]) + target


def _original_offset(record, offset):
    shift = 0
    for match in re.finditer(r"</script", record["original"], re.I):
        inserted = match.start() + 1 + shift
        if offset == inserted:
            return None
        if inserted < offset:
            shift += 1
    return offset - shift


def _location(location, files, html, scripts, records):
    index = location.get("script_index")
    if type(index) is int and 1 <= index <= len(scripts) and "script_column" in location:
        record = records[index - 1]
        point = _offset(record["generated"], location.get("script_line"), location["script_column"])
    else:
        absolute = _offset(html, location.get("line"), location.get("column"))
        if absolute is None:
            return None
        record, point = None, None
        for script, candidate in zip(scripts, records):
            start = _offset(html, script["line"], script["column"] + 1, utf16=False)
            if start is not None and start <= absolute <= start + len(candidate["generated"]):
                record, point = candidate, absolute - start
                break
    if record is None or point is None:
        return None
    original = _original_offset(record, point)
    if original is None:
        return None
    path = record["path"]
    source = files[path]
    point = record["source_start"] + original
    if not 0 <= point <= len(source):
        return None
    prefix = source[:point]
    line = prefix.count("\n") + 1
    column = len(prefix.rsplit("\n", 1)[-1].encode("utf-16-le")) // 2 + 1
    rows = source.split("\n")
    return {
        "location": "source", "file": path, "path": path, "line": line, "column": column,
        "column_unit": "utf16", "file_hash": sha256(source),
        "source_excerpt": "\n".join(f"{n + 1}: {rows[n]}" for n in range(max(0, line - 2), min(len(rows), line + 1)))[:1000],
        "bundled_location": {key: location[key] for key in
                             ("file", "line", "column", "script_index", "script_line", "script_column")
                             if key in location},
    }


def locate_findings(findings, *, files, html):
    """Failure to prove the exact mapping preserves the original export location."""
    result = deepcopy(findings)
    if not result:
        return result
    # CDP/browser normalization of these separators is not represented by this
    # packager map. Keep export facts rather than assign a plausible source line.
    if re.search(r"\r(?!\n)|[\u2028\u2029]", html):
        return result
    records: list[dict[str, Any]] = []
    try:
        if bundle(files, script_map=records) != html:
            return result
    except (ContractError, KeyError, TypeError):
        return result
    parser = Scripts()
    parser.feed(html)
    parser.close()
    scripts = parser.scripts
    if len(scripts) != len(records) or any(
        script["content"] != record["generated"] for script, record in zip(scripts, records)
    ):
        return result
    for finding in result:
        if finding.get("location") == "source":
            continue
        if finding.get("code") == "javascript_syntax":
            mapped = _location(finding, files, html, scripts, records)
            if mapped:
                finding.update(mapped)
        elif finding.get("code") == "runtime_or_network":
            mapped = [_location(item, files, html, scripts, records) for item in finding.get("locations", [])]
            proven = [item for item in mapped if item]
            if proven:
                finding.update(proven[0])
                finding["locations"] = proven
    return result
