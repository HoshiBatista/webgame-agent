from copy import deepcopy

import pytest

from generation.artifacts import bundle, sha256
from generation.source_map import locate_findings
from validation.syntax import Scripts


def coordinates(text, offset):
    prefix = text[:offset]
    return prefix.count("\n") + 1, len(prefix.rsplit("\n", 1)[-1].encode("utf-16-le")) // 2 + 1


def syntax_location(html, token, *, eof=False):
    parser = Scripts()
    parser.feed(html)
    for index, script in enumerate(parser.scripts, 1):
        if token in script["content"]:
            offset = len(script["content"]) if eof else script["content"].index(token)
            line, column = coordinates(script["content"], offset)
            return {"code": "javascript_syntax", "file": "index.html", "location": "bundled_html",
                    "script_index": index, "script_line": line, "script_column": column,
                    "line": script["line"] + line - 1, "column": column, "message": "Unexpected token"}
    raise AssertionError("Token not found")


@pytest.mark.parametrize("deferred", [False, True])
def test_multiple_external_and_inline_scripts_keep_exact_file_and_source_hash(deferred):
    files = {"index.html": '<body>\n<script src="a.js"' + (' defer' if deferred else '') +
             '></script>\n<script>const inline = 1;</script>\n<script src="b.js"></script></body>',
             "a.js": "const first=1;\nconst broken = ;\n", "b.js": "const second=2;"}
    html = bundle(files)
    finding = syntax_location(html, "broken")
    before = deepcopy(finding)
    mapped = locate_findings([finding], files=files, html=html)[0]
    assert mapped["path"] == "a.js" and mapped["line"] == 2 and mapped["column"] == 7
    assert mapped["file_hash"] == sha256(files["a.js"])
    assert mapped["bundled_location"]["script_index"] == (3 if deferred else 1)
    assert "2: const broken = ;" in mapped["source_excerpt"]
    assert finding == before


def test_inline_coordinates_include_unicode_prefix_in_the_original_html():
    files = {"index.html": '<body>😀\n😀<script>const value="😀";const broken = ;</script></body>'}
    html = bundle(files)
    original = files["index.html"]
    line, column = coordinates(original, original.index("broken"))
    mapped = locate_findings([syntax_location(html, "broken")], files=files, html=html)[0]
    assert (mapped["path"], mapped["line"], mapped["column"]) == ("index.html", line, column)


def test_external_escape_and_utf16_columns_map_back_without_altering_source_bytes():
    files = {"index.html": '<script src="game.js"></script>',
             "game.js": 'const label="😀</script>";const broken = ;'}
    original = deepcopy(files)
    html = bundle(files)
    assert "<\\/script>" in html
    expected = coordinates(files["game.js"], files["game.js"].index("broken"))
    mapped = locate_findings([syntax_location(html, "broken")], files=files, html=html)[0]
    assert (mapped["line"], mapped["column"]) == expected
    assert files == original


def test_syntax_eof_after_trailing_newline_maps_to_source_eof():
    files = {"index.html": '<script src="game.js"></script>', "game.js": "function broken() {\n"}
    html = bundle(files)
    mapped = locate_findings([syntax_location(html, "broken", eof=True)], files=files, html=html)[0]
    assert (mapped["path"], mapped["line"], mapped["column"]) == ("game.js", 2, 1)


def test_crlf_source_lines_are_preserved_and_nonstandard_line_normalization_is_not_guessed():
    files = {"index.html": '<script src="game.js"></script>', "game.js": "const x=1;\r\nconst broken = ;"}
    html = bundle(files)
    finding = syntax_location(html, "broken")
    mapped = locate_findings([finding], files=files, html=html)[0]
    assert (mapped["path"], mapped["line"], mapped["column"]) == ("game.js", 2, 7)
    files["game.js"] = files["game.js"].replace("\r\n", "\u2028")
    html = bundle(files)
    finding = syntax_location(html, "broken")
    assert locate_findings([finding], files=files, html=html) == [finding]


def test_runtime_export_frame_maps_to_original_deferred_file():
    files = {"index.html": '<script src="game.js" defer></script><body>😀</body>',
             "game.js": 'const x="😀";\nthrow new Error("observed");'}
    html = bundle(files)
    line, column = coordinates(html, html.index("throw"))
    finding = {"code": "runtime_or_network", "errors": ["observed"], "locations": [
        {"file": "index.html", "line": line, "column": column}]}
    mapped = locate_findings([finding], files=files, html=html)[0]
    assert (mapped["path"], mapped["line"], mapped["column"]) == ("game.js", 2, 1)
    assert mapped["errors"] == ["observed"]


@pytest.mark.parametrize("reason", ["different_export", "invalid_line", "no_frame"])
def test_unproven_source_location_preserves_export_facts(reason):
    files = {"index.html": '<script src="game.js"></script>', "game.js": "const broken = ;"}
    html = bundle(files)
    finding = syntax_location(html, "broken")
    if reason == "different_export":
        html += " "
    elif reason == "invalid_line":
        finding["script_line"] = 1000
    else:
        finding = {"code": "runtime_or_network", "errors": ["Unknown"], "locations": []}
    assert locate_findings([finding], files=files, html=html) == [finding]


def test_long_utf16_line_keeps_actual_error_in_final_model_feedback():
    from generation.feedback import focus_findings
    from generation.prompts import build_messages

    source = 'const label="😀";' + 'const filler=1; ' * 400 + 'const offsets=[];offsets=[[1,2]];'
    files = {"index.html": '<script src="game.js"></script>', "game.js": source}
    html = bundle(files)
    location = syntax_location(html, 'offsets=[[1,2]]')
    mapped = locate_findings([location], files=files, html=html)[0]
    focused = focus_findings([mapped])[0]
    assert 'offsets=[[1,2]]' in focused['source_excerpt']
    assert focused['excerpt_start_column'] < focused['column'] <= focused['excerpt_end_column']
    assert focused['excerpt_truncated'] is True
    assert 'offsets=[[1,2]]' in build_messages({'operation': 'repair', 'findings': [focused]})[1]['content']


def test_moving_same_statement_retains_anchor_but_separate_identical_faults_do_not():
    def mapped(source, token='offsets=[[1,2]]', last=False):
        files = {'index.html': '<script src="game.js"></script>', 'game.js': source}
        html = bundle(files)
        line, column = coordinates(html, html.rindex(token) if last else html.index(token))
        finding = {'code': 'runtime_or_network', 'locations': [{'line': line, 'column': column}]}
        return locate_findings([finding], files=files, html=html)[0]

    first = mapped('const offsets=[]; offsets=[[1,2]];')
    shifted = mapped('let another=4; const offsets=[];   offsets=[[1,2]];')
    assert first['column'] != shifted['column'] and first['source_anchor'] == shifted['source_anchor']
    other = mapped('const offsets=[]; offsets=[[1,2]]; offsets=[[1,2]];', last=True)
    assert first['source_anchor'] != other['source_anchor']


@pytest.mark.browser
@pytest.mark.native_browser
@pytest.mark.parametrize("kind", ["syntax", "runtime"])
def test_real_isolated_chromium_locations_map_to_source_without_executing_on_host(kind, monkeypatch):
    from generation.providers.fake import fixture_response
    from validation.service import validate

    monkeypatch.setenv("VALIDATOR_BACKEND", "native")
    response = fixture_response()
    files = {entry["path"]: entry["content"] for entry in response["files"]}
    if kind == "syntax":
        files["game.js"] = "const initial=1;\nconst broken = ;\n"
    else:
        files["game.js"] += "\nthrow new Error('actual-runtime-probe');"
    html = bundle(files)
    report = validate(html, response["checks"], artifact_hash=sha256(html))
    assert report["status"] == "failed", report
    findings = locate_findings(report["findings"], files=files, html=html)
    target = next(item for item in findings if item["code"] ==
                  ("javascript_syntax" if kind == "syntax" else "runtime_or_network"))
    assert (target["path"], target["line"]) == ("game.js", 2), target
    assert target["file_hash"] == sha256(files["game.js"])
    assert target["bundled_location"]["file"] == "index.html"
