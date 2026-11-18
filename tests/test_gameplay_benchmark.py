import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from scripts.gameplay_benchmark import (
    DEFAULT_SUITE,
    compare,
    invocation_metrics,
    load_cases,
    run_case,
    summarize,
)


def test_counts_only_sent_operations_and_preserves_all_financial_receipts():
    sent = datetime(2026, 11, 19, tzinfo=UTC)
    metrics = invocation_metrics([
        ("edit", None, "failed", Decimal("0.00"), Decimal("6.28")),
        ("create", None, "reserved", None, Decimal("6.28")),
        ("repair", None, "succeeded", Decimal("0.25"), Decimal("6.28")),
        ("repair", None, "unknown", None, Decimal("6.28")),
        ("check_repair", sent, "succeeded", Decimal("0.07"), Decimal("6.28")),
        ("edit", sent, "succeeded", None, Decimal("6.28")),
    ])
    assert metrics == {
        "model_operations": {"edit": 1, "check_repair": 1}, "repair_calls": 1, "edit_calls": 1,
        "known_cost_usd": "0.32", "unknown_calls": 1, "unknown_reserved_usd": "6.28",
        "other_calls_without_cost": 1,
    }


def test_bundle_mismatch_or_absence_never_reaches_the_browser(tmp_path, monkeypatch):
    case = load_cases(DEFAULT_SUITE)[0]
    monkeypatch.setattr("validation.service.validate", lambda *a, **k: pytest.fail("unbound game executed"))
    missing = run_case(case, tmp_path)
    assert missing["status"] == "missing_artifact"
    path = tmp_path / (case["run_id"] + ".json")
    path.write_text("{")
    assert run_case(case, tmp_path)["status"] == "invalid_pack"
    path.write_text(json.dumps({"run_id": case["run_id"], "profile": "other", "html": "other"}))
    assert run_case(case, tmp_path)["status"] == "artifact_mismatch"


def test_replay_uses_operator_checks_and_counts_uncertain_games(tmp_path, monkeypatch):
    case = load_cases(DEFAULT_SUITE)[0]
    html = "inert export"
    case["artifact_hash"] = hashlib.sha256(html.encode()).hexdigest()
    metrics = {"repair_calls": 1, "edit_calls": 2, "known_cost_usd": "0.246810", "unknown_calls": 1,
               "unknown_reserved_usd": "6.28", "other_calls_without_cost": 0, "generation_seconds": 100}
    pack = {"html": html, "revision_id": "saved", "run_id": case["run_id"], "profile": case["profile"],
            "metrics": metrics}
    path = tmp_path / (case["run_id"] + ".json")
    path.write_text(json.dumps(pack))

    def validate(source, checks, *, artifact_hash, operator_criteria, test_profile):
        assert source == html and artifact_hash == case["artifact_hash"]
        assert [c.id for c in operator_criteria] == [c["id"] for c in checks]
        assert test_profile["seed"] == case["seed"]
        return {"status": "passed", "elapsed_seconds": 3, "environment": "browser 1",
                "facts": [{"status": "passed"} for _ in checks], "findings": []}

    monkeypatch.setattr("validation.service.validate", validate)
    good = run_case(case, tmp_path)
    assert good["checks_passed"] == 12 and good["generation"] == metrics
    wrong = run_case({**case, "artifact_hash": "1"*64}, tmp_path)
    assert wrong["status"] == "artifact_mismatch"
    path.write_text(json.dumps({**pack, "revision_id": None, "html": None}))
    no_game = run_case({**case, "checks": [], "artifact_hash": None}, tmp_path)
    totals = summarize([good, wrong, no_game])
    assert totals["scheduled"] == 3 and totals["passed"] == 1
    assert totals["statuses"] == {"passed": 1, "no_revision": 1, "artifact_mismatch": 1}
    assert totals["measured_games"] == 2 and totals["known_cost_usd"] == "0.493620"
    assert totals["unknown_reserved_usd"] == "12.56"


def test_profile_comparison_pairs_only_shared_families(tmp_path):
    rows = [run_case(c, tmp_path) for c in load_cases(DEFAULT_SUITE)]
    report = {"cases": rows}
    comparison = compare(report, report, "lite", "pro")
    assert comparison["only_before"] == ["snake"] and comparison["only_after"] == []
    [pair] = comparison["pairs"]
    assert pair["group"] == "sokoban" and not pair["same_checks"] and not pair["same_artifact"]
    assert not pair["same_environment"]
    with pytest.raises(ValueError, match="Ambiguous"):
        compare({"cases": rows + rows}, report, "lite", "pro")
