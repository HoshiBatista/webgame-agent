import json
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import connections, transaction

from generation.prompts import build_messages
from generation.providers.fake import generate as fixture_generate
from studio.management.commands.variant_experiment_report import public_outcomes
from studio.models import Publication, VariantAnalyticsExperiment, VariantAnalyticsHint, VariantBatch
from studio.tasks import process_run
from studio.tests.test_analytics_hints import play, rate
from studio.tests.test_analytics_hints import publication as publication
from studio.tests.test_pro_variants import create_batch, detail, post, select
from studio.tests.test_pro_variants import workspace as workspace
from studio.tests.test_staged_generation import PASS

pytestmark = pytest.mark.django_db(transaction=True)


def report():
    output = StringIO()
    call_command("variant_experiment_report", stdout=output)
    return json.loads(output.getvalue())


def trial(chat, slots, chosen=None, ready=None, *, version=2):
    fields = {}
    if version == 1 and slots:
        [(index, key)] = slots.items()
        fields = {"hint_variant_index": index, "hint": {"hint_key": key}}
    experiment = VariantAnalyticsExperiment.objects.create(
        batch=VariantBatch.objects.create(chat=chat), protocol_version=version, first_choice_index=chosen,
        ready_at_first_choice=ready, **fields
    )
    if version == 2:
        VariantAnalyticsHint.objects.bulk_create([
            VariantAnalyticsHint(experiment=experiment, variant_index=index, hint={"hint_key": key})
            for index, key in slots.items()
        ])
    return experiment


def test_report_weights_baselines_by_comparable_choices_and_counts_distinct_mechanics(workspace):
    empty = report()["first_choices"]
    assert empty["hinted_choice_share"] is None and empty["random_choice_share"] is None
    trial(workspace, {}, chosen=3, ready=4)
    trial(workspace, {1: "waves"}, chosen=1, ready=4, version=1)
    trial(workspace, {3: "waves"})  # New protocol with a single available mechanic.
    trial(workspace, {1: "waves", 3: "route"}, chosen=3, ready=4)
    hands = {1: "waves", 2: "route", 4: "coins"}
    trial(workspace, hands, chosen=3, ready=4)
    trial(workspace, hands, chosen=4, ready=4)
    trial(workspace, hands, chosen=1, ready=2)
    trial(workspace, hands, chosen=1)

    result = report()
    assert result["first_choices"] == {
        "opted_in": 8, "without_hint": 1, "assigned_without_choice": 1, "choices_without_ready_snapshot": 1,
        "early_choices": 1, "comparable_choices": 4, "hinted_choices": 3, "hinted_choice_share": 0.75,
        "random_choice_share": 9 / 16,
    }
    cohorts = {(row["protocol_version"], row["hint_count"]): row for row in result["cohorts"]}
    assert {key: row["random_choice_share"] for key, row in cohorts.items()} == {
        (1, 1): 0.25, (2, 0): 0, (2, 1): 0.25, (2, 2): 0.5, (2, 3): 0.75,
    }
    assert cohorts[2, 0]["all_four_choices"] == 1 and cohorts[2, 0]["hinted_choices"] == 0
    assert cohorts[2, 1]["hinted_choice_share"] is None
    assert cohorts[2, 3]["all_four_choices"] == 2 and cohorts[2, 3]["hinted_choice_share"] == 0.5
    outcomes = result["mechanics"]
    assert (outcomes["waves"]["assigned"], outcomes["waves"]["comparable_exposures"], outcomes["waves"]["first_choices"]) == (7, 4, 1)
    assert (outcomes["route"]["comparable_exposures"], outcomes["route"]["first_choices"]) == (3, 1)
    assert outcomes["coins"]["choice_share"] == 0.5 and outcomes["coins"]["random_choice_share"] == 0.25


def test_publication_of_legacy_hint_written_without_an_assignment_counts_in_its_mechanic(publication):
    run = publication.revision.run
    legacy = trial(run.chat, {2: "enemy_waves"}, chosen=2, ready=4, version=1)
    run.variant_batch = legacy.batch
    run.variant_index = 2
    run.save(update_fields=["variant_batch", "variant_index"])
    play(publication, [30_000])
    rate(publication, [4])
    assert not legacy.assignments.exists()
    with transaction.atomic():
        assert Publication.objects.filter(pk=publication.pk).exists()
        data = report()
    expected = {"publications": 1, "sessions": 1, "sessions_30s": 1, "share_30s": 1.0, "ratings": 1, "mean_rating": 4.0}
    assert data["published_variants"]["hinted"] == expected
    assert data["mechanics"]["enemy_waves"]["published"] == expected


def test_a_choice_during_the_report_appears_in_the_next_snapshot(workspace):
    experiment = trial(workspace, {2: "enemy_waves"})

    def click():
        try:
            VariantAnalyticsExperiment.objects.filter(pk=experiment.pk).update(first_choice_index=2, ready_at_first_choice=4)
        finally:
            connections.close_all()

    def click_after_publications_are_read():
        outcomes = public_outcomes()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(click).result(timeout=10)
        return outcomes

    with patch("studio.management.commands.variant_experiment_report.public_outcomes",
               side_effect=click_after_publications_are_read):
        assert report()["first_choices"]["assigned_without_choice"] == 1
    assert report()["first_choices"]["hinted_choices"] == 1


def test_three_public_signals_reach_separate_plans_and_only_one_control(client, workspace, publication):
    source_run = publication.revision.run
    source_run.game_plan.update(mechanics=["Контрольная точка", "Выбор маршрута"])
    source_run.save(update_fields=["game_plan"])
    play(publication, [30_000] * 4 + [3_000] * 4)
    rate(publication, [4, 5, 5])
    batch = create_batch(client, workspace, prompt="Сделай космический шутер", analytics_experiment=True)
    assert batch["analytics_experiment"] == {"status": "applied", "hint_count": 3}
    hints = dict(VariantAnalyticsHint.objects.filter(experiment_id=batch["id"]).values_list("variant_index", "hint"))
    assert {hint["hint_key"] for hint in hints.values()} == {"enemy_waves", "route_choice", "checkpoint"}
    assert all(hint["source_publication_id"] == str(publication.pk) for hint in hints.values())

    with (patch("generation.service.generate", side_effect=fixture_generate),
          patch("validation.service.validate", return_value=PASS)):
        for variant in batch["variants"]:
            process_run(variant["run_id"])
    for run in workspace.runs.order_by("variant_index"):
        calls = list(run.invocations.order_by("attempt").values_list("request", flat=True))
        assert [req["operation"] for req in calls] == ["plan", "create"]
        system, user = build_messages(calls[0])
        ordinary_system, _ = build_messages({**calls[0], "variant_index": None, "design": {}})
        assert ordinary_system == system
        context = json.loads(user["content"])
        suggestion = context["design"].get("optional_analytics_hint")
        if run.variant_index in hints:
            assert suggestion["suggestion"] == hints[run.variant_index]["text"]
            assert "origin=design" in suggestion["guidance"]
        else:
            assert suggestion is None
        assert str(publication.pk) not in user["content"]
        assert publication.title not in user["content"]
        assert context["game_request"] == "Сделай космический шутер"
        assert "optional_analytics_hint" not in build_messages(calls[1])[1]["content"]

    [finished] = detail(client, workspace)["variant_batches"]
    chosen_slot = next(iter(hints))
    hinted = finished["variants"][chosen_slot - 1]["revision"]
    displayed = [variant["revision"]["id"] for variant in finished["variants"]]
    assert select(client, workspace, finished, hinted, ready_revision_ids=displayed).status_code == 200
    response = post(client, "/api/publications/", chat_id=str(workspace.pk),
                    revision_id=hinted["id"], title="Аркада")
    assert response.status_code == 201
    published = Publication.objects.get(pk=response.json()["id"])
    play(published, [30_000, 300])
    play(published, [30_000], artifact_hash="0" * 64)
    rate(published, [5, 3])
    sample = report()
    assert sample["first_choices"]["comparable_choices"] == 1
    assert sample["first_choices"]["hinted_choice_share"] == 1
    assert sample["first_choices"]["random_choice_share"] == 0.75
    expected = {"publications": 1, "sessions": 2, "sessions_30s": 1, "share_30s": 0.5, "ratings": 2, "mean_rating": 4.0}
    assert sample["published_variants"]["hinted"] == expected
    for index, hint in hints.items():
        mechanic = sample["mechanics"][hint["hint_key"]]
        assert mechanic["first_choices"] == int(index == chosen_slot) and mechanic["comparable_exposures"] == 1
        assert mechanic["published"]["publications"] == int(index == chosen_slot)
    other = next(v for v in finished["variants"] if v["index"] not in hints)
    assert client.patch(f"/api/publications/{published.pk}/", {"revision_id": other["revision"]["id"]},
                        content_type="application/json").status_code == 200
    updated = report()["published_variants"]
    assert updated["hinted"]["publications"] == 0
    assert updated["ordinary"] == {
        "publications": 1, "sessions": 0, "sessions_30s": 0, "share_30s": None, "ratings": 0, "mean_rating": None,
    }
