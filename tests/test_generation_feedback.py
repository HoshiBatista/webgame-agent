import json
from copy import deepcopy

from generation.feedback import MAX_FINDINGS, MAX_MESSAGE_CHARS, focus_findings


def test_syntax_precedes_runtime_and_gameplay_without_modifying_reports():
    findings = [
        {"code": "effect_mismatch", "check_id": "start", "before": 0, "after": 0},
        {"code": "runtime_or_network", "errors": ["game is undefined"], "requests": []},
        {"code": "javascript_syntax", "path": "game.js", "line": 12, "message": "Unexpected end of input"},
    ]
    original = deepcopy(findings)
    assert focus_findings(findings) == [findings[-1]]
    assert findings == original
    result = focus_findings(findings)
    result[0]["message"] = "changed"
    assert findings == original


def test_syntax_preserves_bundled_html_and_script_locations():
    finding = {"code": "javascript_syntax", "message": "Unexpected end of input", "file": "index.html",
               "line": 42, "column": 17, "script_index": 2, "script_line": 8}
    assert focus_findings([finding]) == [finding]


def test_many_scenario_cascades_become_one_root_error_with_check_ids():
    findings = []
    for index in range(9):
        findings.extend([
            {"code": "check_unverified", "check_id": f"check-{index}", "message": "Timeout waiting for button"},
            {"code": "runtime_or_network", "check_id": f"check-{index}",
             "message": "Ошибки JavaScript или попытки внешних запросов.",
             "errors": [f"TypeError: Cannot set property state which has only a getter\n at play:{index}"],
             "requests": []},
        ])
    result = focus_findings(findings)
    assert len(result) == 1
    assert result[0]["errors"] == [findings[1]["errors"][0]]
    assert result[0]["check_id"] == "check-0"
    assert result[0]["check_ids"] == [f"check-{index}" for index in range(9)]
    assert len(findings) == 18


def test_unique_runtime_errors_and_blocked_urls_precede_scenario_failures():
    findings = [
        {"code": "effect_mismatch", "message": "No score change"},
        {"code": "runtime_or_network", "check_id": "touch", "errors": ["ReferenceError: x is not defined"],
         "requests": ["https://example.test/assets.png?token=secret"]},
        {"code": "runtime_or_network", "check_id": "keyboard",
         "errors": ["ReferenceError: x is not defined", "TypeError: Invalid coordinate"],
         "requests": ["https://example.test/assets.png?token=other"]},
    ]
    result = focus_findings(findings)
    assert len(result) == 3
    assert [item.get("errors") for item in result[:2]] == [
        ["ReferenceError: x is not defined"], ["TypeError: Invalid coordinate"],
    ]
    assert result[2]["requests"] == ["https://example.test/assets.png"]


def test_gameplay_observations_and_expectations_are_preserved_and_copied():
    finding = {"code": "effect_mismatch", "check_id": "blocked-move", "message": "Forbidden move must preserve state",
               "before": {"x": 1, "y": 2}, "after": {"x": 2, "y": 2},
               "expected": {"operator": "equals", "value": {"x": 1, "y": 2}}}
    result = focus_findings([finding])
    assert result == [finding]
    result[0]["expected"]["value"]["x"] = 99
    assert finding["expected"]["value"]["x"] == 1


def test_empty_or_unknown_runtime_details_keep_actionable_message():
    findings = [{"code": "runtime_or_network", "message": "Unknown runtime failure", "errors": []}]
    assert focus_findings(findings) == [{"code": "runtime_or_network", "message": "Unknown runtime failure"}]
    assert focus_findings([]) == []


def test_only_three_distinct_findings_are_selected_with_stable_tie_order():
    findings = [{"code": "effect_mismatch", "check_id": f"check-{index}", "message": f"Effect {index} failed"}
                for index in range(8)]
    assert focus_findings(findings) == findings[:3]
    assert len(findings) == 8


def test_patch_and_schema_errors_retain_code_and_message_but_not_raw_payloads():
    findings = [
        {"code": "ambiguous_patch", "message": "Фрагмент в game.js должен совпадать ровно один раз.",
         "raw_response": {"private": "raw payload"}},
        {"code": "invalid_schema", "message": "checks.0.title is not allowed", "response": "raw payload"},
    ]
    assert focus_findings(findings) == [
        {"code": "ambiguous_patch", "message": findings[0]["message"]},
        {"code": "invalid_schema", "message": findings[1]["message"]},
    ]


def test_feedback_is_bounded_deterministic_and_redacts_recognizable_credentials():
    findings = [{"code": "effect_mismatch", "check_id": f"check-{index}",
                 "message": "Authorization: Bearer never-expose-this https://user:pass@example.test/a?q=secret#token "
                 + "details " * 1000,
                 "before": {"password": "not-this-either", "raw_response": "private", "items": ["x" * 2000] * 30},
                 "expected": {"operator": "equals", "value": "secret=also-private"}}
                for index in range(20)]
    result = focus_findings(findings)
    encoded = json.dumps(result)
    assert len(result) <= MAX_FINDINGS
    assert len(result[0]["message"]) <= MAX_MESSAGE_CHARS
    assert len(encoded) < 8000
    for secret in ("never-expose-this", "user:pass", "q=secret", "#token", "not-this-either", "also-private", "raw_response"):
        assert secret not in encoded
    assert result == focus_findings(findings)
