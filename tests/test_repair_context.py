import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from generation.prompts import build_messages, repair_evidence
from generation.schema import CONTRACT_VERSION
from studio.tasks import request_for as build_request


def request_for(run, base, findings):
    run.invocations = Mock()
    run.invocations.order_by.return_value.first.return_value = SimpleNamespace(
        request={"generation_contract": {"pipeline_version": CONTRACT_VERSION}}
    )
    run.max_repair_attempts = 1
    run.completion_policy = 2
    run.pipeline_version = CONTRACT_VERSION
    run.generation_profile = "full"
    run.source_format = "string"
    run.game_request = run.prompt
    run.generation_strategy = "lite"
    run.planning_required = False
    from generation.requirements import policy_snapshot

    run.game_plan = {}
    run.policy_snapshot = policy_snapshot()
    run.preferences_snapshot = []
    run.helper_catalog = {}
    run.visual_state = {}
    run.requirement_manifest = {}
    run.source_revision_id = run.base_revision_id
    run.candidate_revision_id = None
    if base is not None:
        base.accepted = True
        base.artifact_hash = "candidate-hash"
        base.compact_manifest = {}
        base.checks = __import__(
            "generation.providers.fake", fromlist=["fixture_response"]
        ).fixture_response()["checks"]
    # This unit fixture has no persisted receipts; database-backed fragment
    # recovery is exercised by studio/tests/test_edit_recovery.py.
    with patch("studio.patch_repair.pending_permission", return_value=None):
        return build_request(run, base, findings)


@pytest.mark.parametrize("operation", ["create", "edit", "repair"])
def test_recorded_prompt_hash_matches_the_instructions_actually_sent_for_each_operation(operation):
    base = None if operation == "create" else SimpleNamespace(id="revision", files={}, design={}, checks=[])
    run = SimpleNamespace(
        base_revision_id="revision" if operation == "edit" else None,
        prompt="Сделай законченную игру",
        audience="everyone",
        chat=SimpleNamespace(owner=object()),
        provider="fake",
        model="fixture",
    )
    # A pre-candidate contract failure must retain create/edit, not become repair.
    findings = [{"code": "invalid_schema"}] if base is None else []
    request = request_for(run, base, findings)
    prompt = build_messages(request)[0]["content"]
    assert request["operation"] == operation
    assert (
        request["generation_contract"]["system_prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    )
    assert {
        "create": "CURRENT STEP: CREATE",
        "edit": "CURRENT STEP: APPLY",
        "repair": "CURRENT STEP: REPAIR",
    }[operation] in prompt


def browser_report():
    return {
        "status": "failed",
        "facts": [
            {
                "id": "move",
                "category": "control",
                "requirement": "Робот движется после касания",
                "status": "failed",
                "viewport": "mobile",
                "actions": [{"action": "tap_fraction", "selector": "#right", "x": 0.5, "y": 0.5}],
                "before": 10,
                "after": 10,
                "expected": {"operator": "increased"},
                "detail": "Позиция не изменилась",
                "screenshot_base64": "PRIVATE_SCREENSHOT_NOT_FOR_PROMPT",
            }
        ],
        "findings": [{"code": "effect_mismatch", "check_id": "move"}],
        "screenshot_base64": "PRIVATE_SCREENSHOT_NOT_FOR_PROMPT",
    }


def test_repair_request_carries_actual_browser_context_for_the_exact_candidate():
    report = browser_report()
    reports = Mock()
    reports.order_by.return_value.first.return_value = SimpleNamespace(**report)
    base = SimpleNamespace(
        id="candidate", files={"game.js": "const x=10;"}, design={}, checks=[], reports=reports
    )
    run = SimpleNamespace(
        base_revision_id=None,
        prompt="Двигай робота",
        audience="everyone",
        chat=SimpleNamespace(owner=object()),
        provider="fake",
        model="fixture",
    )
    request = request_for(run, base, report["findings"])
    assert request["operation"] == "repair"
    assert request["base_revision"] == "candidate"
    context = json.loads(build_messages(request)[1]["content"])
    fact = context["validation_evidence"]["facts"][0]
    assert fact["before"] == fact["after"] == 10
    assert fact["expected"] == {"operator": "increased"}
    assert fact["actions"] == report["facts"][0]["actions"]
    assert fact["viewport"] == "mobile"
    assert "PRIVATE_SCREENSHOT_NOT_FOR_PROMPT" not in json.dumps(context)


@pytest.mark.parametrize("reason", ["packaging", "infrastructure", "passed", "missing_report"])
def test_unrelated_or_infrastructure_report_is_not_sent_as_repair_evidence(reason):
    report = browser_report()
    findings = report["findings"]
    if reason == "packaging":
        findings = [{"code": "ambiguous_patch"}]
    elif reason != "missing_report":
        report["status"] = "infrastructure_error" if reason == "infrastructure" else "passed"
    reports = Mock()
    reports.order_by.return_value.first.return_value = (
        None if reason == "missing_report" else SimpleNamespace(**report)
    )
    base = SimpleNamespace(id="candidate", files={}, design={}, checks=[], reports=reports)
    run = SimpleNamespace(
        base_revision_id=None,
        prompt="Исправь",
        audience="everyone",
        chat=SimpleNamespace(owner=object()),
        provider="fake",
        model="fixture",
    )
    request = request_for(run, base, findings)
    assert "validation_evidence" not in request


def test_large_evidence_is_bounded_marked_and_does_not_mutate_the_stored_facts():
    report = browser_report()
    report["facts"][0]["before"] = "я" * 10000
    report["facts"] = [
        dict(deepcopy(report["facts"][0]), id=f"case-{i}", detail="я" * 1700) for i in range(12)
    ]
    original = deepcopy(report)
    evidence = repair_evidence(report)
    assert len(json.dumps(evidence, ensure_ascii=False).encode()) <= 24000
    assert evidence["facts"][0]["before"]["omitted"] is True
    assert evidence["facts"][0]["before"]["utf8_bytes"] > 10000
    assert evidence["omitted_fact_ids"]
    assert evidence["omitted_fact_count"] == len(evidence["omitted_fact_ids"])
    assert report == original


def test_failed_facts_take_priority_over_successful_facts_in_repair_context():
    report = browser_report()
    failed = deepcopy(report["facts"][0])
    report["facts"].insert(0, {**failed, "id": "start", "status": "passed"})
    evidence = repair_evidence(report)
    assert [fact["status"] for fact in evidence["facts"]] == ["failed", "passed"]
