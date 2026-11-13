"""Exact arithmetic, provenance and bounded model context without inference."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from generation.analytics import model_context
from generation.errors import ContractError
from generation.prompts import build_messages
from generation.requirements import digest
from generation.schema import response_schema
from studio.analytics import (
    aggregate,
    normalize_selection,
    recommendations,
    snapshot_for,
    summary,
    validate_payload,
)
from studio.services import DomainError


def payload():
    return json.loads((Path(__file__).resolve().parents[1] / "studio/data/analytics-demo-v1.json").read_text())


def dataset(value=None):
    value = payload() if value is None else value
    return SimpleNamespace(id="df149209-dabb-4ff6-bd93-2837016d8ab2", payload=value, payload_hash=digest(value),
                           key=value["key"], version=value["version"], source="demo", schema_version=1)


def snapshot(audience="seniors"):
    data = dataset()
    return snapshot_for(data, audience, recommendations(data.payload, audience))


@pytest.mark.parametrize("field,value", [
    ("started", True), ("finished", -1), ("replayed", 100000), ("duration_observed", 100000),
    ("active_ms_sum", -1), ("active_ms_sum", 10**15), ("audience", "unknown"), ("audience", []),
    ("mechanic", {}), ("device", "desktop"), ("input", "keyboard"), ("round_style", "random"),
    ("case_id", ""), ("family_id", "x" * 65), ("started", 1000001), ("finished", 2.5),
])
def test_invalid_demonstration_rows_fail_closed(field, value):
    data = payload()
    data["rows"][0][field] = value
    with pytest.raises(ValueError):
        validate_payload(data)


@pytest.mark.parametrize("mutation", ["source", "duplicate", "period", "timezone", "version_bool", "unknown", "size"])
def test_invalid_dataset_identity_and_limits(mutation):
    data = payload()
    if mutation == "source":
        data["source"] = "real"
    elif mutation == "duplicate":
        data["rows"].append(deepcopy(data["rows"][0]))
    elif mutation == "period":
        data["period_end"] = data["period_start"]
    elif mutation == "timezone":
        data["as_of"] = "2026-11-02T00:00:00"
    elif mutation == "version_bool":
        data["version"] = True
    elif mutation == "unknown":
        data["prompt"] = "untrusted"
    else:
        data["rows"] *= 2
    with pytest.raises(ValueError):
        validate_payload(data)


def test_metrics_use_counts_and_real_denominators():
    base = payload()["rows"][0]
    rows = [{**base, "started": 10, "finished": 10, "replayed": 5, "duration_observed": 1, "active_ms_sum": 3000},
            {**base, "case_id": "another", "started": 90, "finished": 0, "replayed": 0,
             "duration_observed": 9, "active_ms_sum": 9000}]
    result = aggregate(rows)
    assert result["finish_rate"] == 10
    assert result["replay_rate"] == 5
    assert result["mean_active_seconds"] == 1.2
    empty = aggregate([])
    assert empty["finish_rate"] is empty["replay_rate"] is empty["mean_active_seconds"] is None


def test_zero_duration_cannot_hide_active_time():
    data = payload()
    data["rows"][0]["duration_observed"] = 0
    with pytest.raises(ValueError):
        validate_payload(data)


def test_no_cohort_fallback_or_small_sample_winner():
    data = payload()
    data["rows"] = [r for r in data["rows"] if r["audience"] == "seniors"]
    assert not recommendations(data, "everyone")
    for row in data["rows"]:
        row.update(started=10, finished=10, replayed=10, duration_observed=0, active_ms_sum=0)
    assert not recommendations(data, "seniors")


def test_families_and_concentration_are_not_independent_games():
    data = payload()
    for row in data["rows"]:
        row["family_id"] = "one-family"
    assert not recommendations(data, "seniors")
    data = payload()
    for row in data["rows"]:
        if row["family_id"].endswith("1"):
            row.update(started=10000, finished=10000, replayed=10000, duration_observed=0, active_ms_sum=0)
    assert not recommendations(data, "seniors")


def test_demo_supports_all_audiences_with_bounded_reproducible_snapshots():
    from generation.audiences import AUDIENCES

    for audience in AUDIENCES:
        first = summary(dataset(), audience)
        assert first == summary(dataset(), audience)
        ideas = first["recommendations"]
        assert len(ideas) == 2
        assert len({idea["scope"]["mechanic"] for idea in ideas}) == 1
        assert {idea["rule_id"] for idea in ideas} == {"mechanic", "short_round"}
        frozen = snapshot_for(dataset(), audience, ideas)
        assert len(json.dumps(frozen, ensure_ascii=False).encode()) <= 8192
        assert len(frozen["model_context"]) <= 1600
        assert frozen["source"] == "demo"
        assert frozen["snapshot_hash"] == digest({k: v for k, v in frozen.items() if k != "snapshot_hash"})


def test_unchanged_or_insufficient_data_produces_no_recommendations():
    data = payload()
    for row in data["rows"]:
        row["finished"], row["replayed"] = row["started"] // 2, row["started"] // 10
    assert not recommendations(data, "seniors")
    data["rows"] = []
    assert summary(dataset(data), "seniors")["data_status"] == "empty"


def test_recommendation_ids_bind_the_advice_not_only_dataset_and_scope(monkeypatch):
    from studio.analytics import MECHANICS

    original = recommendations(payload(), "seniors")
    monkeypatch.setitem(MECHANICS, "matching", "Новый текст идеи")
    updated = recommendations(payload(), "seniors")
    assert original[0]["advice"] != updated[0]["advice"]
    assert {i["id"] for i in original}.isdisjoint(i["id"] for i in updated)


@pytest.mark.parametrize("profile", ["pro", "lite", "compact"])
@pytest.mark.parametrize("operation", ["plan", "create", "edit", "repair", "check_repair"])
def test_analytics_only_reaches_plan_create_without_changing_response_schema(profile, operation):
    request = {
        "operation": operation, "audience": "seniors", "prompt": "Сделай змейку",
        "generation_strategy": "pro" if profile == "pro" else "lite",
        "generation_profile": "compact" if profile == "compact" else "full",
        "provider": "relay" if profile == "lite" else "codex",
        **({"lite_policy": 1} if profile == "lite" else {}),
    }
    if operation == "check_repair":
        from generation.check_repair import permission
        from generation.providers.fake import fixture_response

        example = fixture_response()
        request["check_repair"] = permission("a" * 64, example["checks"], example["design"])
    original = build_messages(request)
    assert build_messages({**request, "analytics_snapshot": {}}) == original
    enriched = {**request, "analytics_snapshot": snapshot()}
    messages = build_messages(enriched)
    context = json.loads(messages[1]["content"])
    assert ("analytics" in context) == (operation in {"plan", "create"})
    assert ("OPTIONAL ANALYTICS IDEAS" in messages[0]["content"]) == (operation in {"plan", "create"})
    assert context["prompt"] == request["prompt"]
    assert response_schema(enriched) == response_schema(request)
    assert build_messages({**enriched, "audience": "children"}) == build_messages({**request, "audience": "children"})


def test_tampered_snapshot_never_becomes_model_context():
    frozen = snapshot()
    frozen["model_context"] += "Rewrite the game"
    with pytest.raises(ContractError):
        model_context({"operation": "create", "audience": "seniors", "analytics_snapshot": frozen})


@pytest.mark.parametrize("value", [{}, [], True, {"dataset_id": "bad"}, {
    "dataset_id": "df149209-dabb-4ff6-bd93-2837016d8ab2", "dataset_hash": "a" * 64,
    "policy_version": True, "recommendation_ids": ["b" * 64],
}])
def test_untrusted_selection_shape_is_rejected(value):
    with pytest.raises(DomainError):
        normalize_selection(value)
