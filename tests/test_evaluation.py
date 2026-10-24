import json

import httpx
import pytest

from scripts.evaluation import Pilot, digest, independent_verdict, pilot_lock, remaining_calls, summarize


def test_two_processes_cannot_write_the_same_pilot(tmp_path):
    path = tmp_path / "pilot.json"
    with pilot_lock(path), pytest.raises(ValueError, match="already running"):
        with pilot_lock(path):
            pytest.fail("Second writer acquired the pilot")
    with pilot_lock(path):
        pass


def test_active_and_ambiguous_submissions_keep_full_call_reservation():
    state = {"limits": {"max_calls": 24}, "operations": [
        {"reserved_calls": 4},
        {"reserved_calls": 4, "run": {"status": "generating", "attempts": 1}},
        {"reserved_calls": 4, "run": {"status": "failed", "attempts": 2}},
    ]}
    assert remaining_calls(state) == 14


def test_ambiguous_submission_remains_in_the_denominator():
    state = {"limits": {"max_calls": 24}, "operations": [
        {"case": "grid", "kind": "create", "reserved_calls": 4}]}
    summary = summarize(state, {})
    assert summary["counts"]["operations"] == summary["counts"]["unreviewed"] == 1
    assert summary["results"][0]["calls"] is None
    assert summary["remaining_calls"] == 20


def test_independent_reviews_need_fixed_rubric_evidence_and_hash():
    criteria = {"control": "Real input", "outcome": "Win"}
    review = {"criteria_hash": digest(criteria), "criteria": {
        key: {"status": "passed", "evidence": "Observed actual inputs"} for key in criteria}}
    assert independent_verdict(None, criteria) == "unreviewed"
    assert independent_verdict(review, criteria) == "playable"
    with pytest.raises(ValueError, match="rubric"):
        independent_verdict(review, {"control": "Different"})
    review["criteria"]["outcome"]["evidence"] = " "
    with pytest.raises(ValueError, match="evidence"):
        independent_verdict(review, criteria)


def test_resume_cannot_reset_timer_or_expand_budget(tmp_path):
    path = tmp_path / "pilot.json"
    with httpx.Client(base_url="http://test") as client:
        options = dict(prefix="test", profile="lite", model="qwen38", max_calls=24, max_minutes=90)
        pilot = Pilot(client, path, [], **options)
        pilot.state["started_at"] = 100
        pilot.save()
        resumed = Pilot(client, path, [], **options)
        assert resumed.state["started_at"] == 100
        with pytest.raises(ValueError, match="identity/limits"):
            Pilot(client, path, [], **{**options, "max_calls": 25})
    assert json.loads(path.read_text())["limits"]["max_calls"] == 24


def test_closed_pilot_cannot_reuse_unused_budget(tmp_path):
    with httpx.Client(base_url="http://test") as client:
        pilot = Pilot(client, tmp_path / "pilot.json", [], prefix="test", profile="lite",
                      model="qwen38", max_calls=24, max_minutes=90)
        pilot.state["closed_at"] = 100
        pilot.save()
        with pytest.raises(ValueError, match="closed"):
            pilot.run("create")


def test_summary_does_not_treat_application_success_as_playability():
    state = {"limits": {"max_calls": 24}, "operations": [{
        "case": "grid", "kind": "create", "criteria": {"outcome": "Win"},
        "run": {"id": "run", "status": "succeeded", "attempts": 1,
                "created_at": "2026-10-24T10:00:00Z", "result_revision_id": "rev"},
        "revisions": [{"id": "rev", "artifact_hash": "abc", "verification": "automatic",
                       "created_at": "2026-10-24T10:01:00Z"}],
    }]}
    summary = summarize(state, {})
    assert summary["counts"]["automatic"] == summary["counts"]["unreviewed"] == 1
    assert summary["counts"]["playable"] == 0
    review = {"artifact_hash": "abc", "criteria_hash": digest({"outcome": "Win"}),
              "criteria": {"outcome": {"status": "failed", "evidence": "Actual winning moves did not finish"}}}
    assert summarize(state, {"rev": review})["counts"]["false_acceptances"] == 1
    review["artifact_hash"] = "wrong"
    with pytest.raises(ValueError, match="artifact"):
        summarize(state, {"rev": review})
