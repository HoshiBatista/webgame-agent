from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from generation.artifacts import sha256
from generation.errors import ContractError
from generation.providers.fake import fixture_response
from generation.schema import response_schema, validate_checks
from validation.checks import check_issue, comparable, parse_number, review_checks
from validation.contracts import browser_watchdog_seconds
from validation.service import validate


@pytest.mark.parametrize("text,number", [("0", 0), (" 1.25 ", 1.25), ("-3e2", -300)])
def test_strict_numeric_dom_observation(text, number):
    assert parse_number(text) == number


@pytest.mark.parametrize("text", ["", " ", "Счёт: 1", "1px", "1,5", "NaN", "Infinity", "1e999", None, True])
def test_numeric_dom_never_guesses_or_accepts_nonfinite_numbers(text):
    with pytest.raises(ValueError):
        parse_number(text)


@pytest.mark.parametrize("actual,expected", [(None, "anything"), ([], None), (True, 1), ("1", 1)])
def test_mismatched_types_cannot_pass_a_trivial_not_eq(actual, expected):
    assert not comparable(actual, expected)


def test_application_review_repairs_only_representation_without_weakening_the_suite():
    checks = fixture_response()["checks"]
    checks[1]["observation"] = {"source": "text", "selector": "#hits"}
    checks[1]["expect"] = {"operator": "increased", "value": None}
    original = deepcopy(checks)
    effective, changes = review_checks(checks)
    assert checks == original
    assert changes[0]["code"] == "explicit_numeric_observation"
    assert effective[1]["observation"]["source"] == "text_number"
    for old, new in zip(checks, effective):
        assert {k: v for k, v in old.items() if k != "observation"} == {
            k: v for k, v in new.items() if k != "observation"
        }
    assert review_checks(effective) == (effective, [])


def test_current_check_language_is_shared_by_codex_and_api_and_rejects_retired_contracts():
    response = fixture_response()
    response["checks"][1]["observation"]["source"] = "text_number"
    response["checks"][1]["observation"].pop("path")
    response["checks"][1]["observation"]["selector"] = "#hits"
    response["checks"][1]["steps"].extend([{"action": "checkpoint"}, {"action": "wait_for", "ms": 500}])
    assert Draft202012Validator(response_schema({})).is_valid(response)
    for version in (2, 3):
        with pytest.raises(ContractError):
            response_schema({"generation_contract": {"pipeline_version": version}})


def test_checkpoint_cannot_count_only_setup_as_control_and_waits_stay_bounded():
    check = fixture_response()["checks"][1]
    check["expect"] = {"operator": "increased", "value": None}
    check["steps"].append({"action": "checkpoint"})
    assert "настоящий" in check_issue(check)
    check["steps"].extend([deepcopy(check["steps"][0]), {"action": "wait_for", "ms": 1000}])
    assert check_issue(check) is None
    assert browser_watchdog_seconds([check]) >= 6
    check["steps"].append({"action": "wait", "ms": 10000})
    with pytest.raises(ValueError):
        browser_watchdog_seconds([check])
    with pytest.raises(ContractError, match="10 секунд"):
        validate_checks([check], require_complete=False)


def game(broken=False, crash=False):
    effect = "" if broken else "setTimeout(()=>{s.count++;score.textContent=String(s.count);draw()},120);"
    return '''<!doctype html><style>body{margin:0}canvas{width:280px;height:180px}</style>
    <button id="start">Начать</button><canvas width="280" height="180"></canvas><p id="score">0</p>
    <script>window.s={count:0,active:false};const c=document.querySelector('canvas'),ctx=c.getContext('2d');
    function draw(){ctx.fillStyle='#ddd';ctx.fillRect(0,0,280,180);ctx.fillStyle='#25a';ctx.fillRect(0,20,50,50)}
    start.onclick=()=>{s.active=true;s.count=10;score.textContent='10';''' + (
        "throw new Error('real game failure');" if crash else ""
    ) + '''};c.onclick=()=>{if(s.active){''' + effect + '''}};draw();</script>'''


def game_checks():
    start = {"action": "click", "selector": "#start", "x": None, "y": None}
    click = {"action": "tap", "selector": "canvas", "x": 40, "y": 40}
    wait = {"action": "wait_for", "ms": 500}
    return [
        {"id": "start", "category": "start", "requirement": "Старт начинает партию",
         "viewport": "mobile", "steps": [start], "observation": {"source": "text", "selector": "#score"},
         "expect": {"operator": "eq", "value": "10"}},
        {"id": "control", "category": "control", "requirement": "Нажатие увеличивает счёт",
         "viewport": "mobile", "steps": [start, {"action": "checkpoint"}, click, wait],
         "observation": {"source": "text_number", "selector": "#score"},
         "expect": {"operator": "increased", "value": None}},
        {"id": "outcome", "category": "outcome", "requirement": "Два нажатия достигают цели",
         "viewport": "desktop", "steps": [start, click, click, wait],
         "observation": {"source": "state", "path": "s.count"}, "expect": {"operator": "eq", "value": 12}},
    ]


@pytest.mark.browser
def test_numeric_dom_setup_checkpoint_and_async_effect_pass_in_isolated_browser():
    html, checks = game(), game_checks()
    result = validate(html, checks, artifact_hash=sha256(html))
    assert result["status"] == "passed", result
    assert result["facts"][1]["before"] == 10 and result["facts"][1]["after"] == 11
    assert all(result["gates"].values())


@pytest.mark.browser
def test_broken_control_cannot_pass_using_only_the_startup_change():
    html = game(broken=True)
    result = validate(html, game_checks(), artifact_hash=sha256(html))
    assert result["status"] == "failed", result
    fact = result["facts"][1]
    assert fact["before"] == fact["after"] == 10 and fact["status"] == "failed"


@pytest.mark.browser
@pytest.mark.parametrize("crash", [False, True])
def test_bad_selector_is_distinct_from_a_runtime_failure_and_never_skips_gates(crash):
    html, checks = game(crash=crash), game_checks()
    checks[1]["observation"]["selector"] = "#wrong-selector"
    result = validate(html, checks, artifact_hash=sha256(html))
    codes = {f["code"] for f in result["findings"]}
    assert "invalid_check" in codes, result
    assert result["gates"]["surface"] is True
    assert result["gates"]["runtime"] is (not crash)
    assert result["status"] == ("failed" if crash else "unverified"), result


@pytest.mark.browser
def test_numeric_label_is_a_check_problem_and_does_not_become_a_gameplay_failure():
    html, checks = game(), game_checks()
    checks[1]["observation"]["selector"] = "#start"
    result = validate(html, checks, artifact_hash=sha256(html))
    assert result["status"] == "unverified", result
    assert result["facts"][1]["status"] == "unverified"
    assert {f["code"] for f in result["findings"]} == {"invalid_check"}
    assert all(result["gates"].values())
