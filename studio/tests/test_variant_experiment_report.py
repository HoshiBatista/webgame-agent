import json
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from generation.prompts import build_messages
from generation.providers.fake import generate as fixture_generate
from studio.models import Publication, VariantAnalyticsExperiment, VariantBatch
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


def test_empty_and_partial_choices_are_separate_from_comparable_choices(workspace):
    assert report()["first_choices"]["hinted_choice_share"] is None
    for fields in ({}, {"hint_variant_index": 1}, {"hint_variant_index": 1, "first_choice_index": 2},
                   {"hint_variant_index": 2, "first_choice_index": 2, "ready_at_first_choice": 1}):
        VariantAnalyticsExperiment.objects.create(batch=VariantBatch.objects.create(chat=workspace), **fields)
    assert report()["first_choices"] == {
        "opted_in": 4, "without_hint": 1, "assigned_without_choice": 1,
        "choices_without_ready_snapshot": 1, "early_choices": 1,
        "comparable_choices": 0, "hinted_choices": 0, "hinted_choice_share": None,
    }


def test_opt_in_from_public_signals_to_planner_choice_and_public_report(client, workspace, publication):
    play(publication, [30_000] * 4 + [3_000] * 4)
    rate(publication, [4, 5, 5])
    batch = create_batch(client, workspace, prompt="Сделай космический шутер", analytics_experiment=True)
    experiment = VariantAnalyticsExperiment.objects.get(batch_id=batch["id"])
    assert experiment.hint["source_publication_id"] == str(publication.pk)
    assert experiment.hint_variant_index in range(1, 5)

    with (patch("generation.service.generate", side_effect=fixture_generate),
          patch("validation.service.validate", return_value=PASS)):
        for variant in batch["variants"]:
            process_run(variant["run_id"])
    for run in workspace.runs.order_by("variant_index"):
        calls = list(run.invocations.order_by("attempt").values_list("request", flat=True))
        assert [req["operation"] for req in calls] == ["plan", "create"]
        system, user = build_messages(calls[0])
        context = json.loads(user["content"])
        suggestion = context["design"].get("optional_analytics_hint")
        if run.variant_index == experiment.hint_variant_index:
            assert suggestion["suggestion"] == experiment.hint["text"]
            assert str(publication.pk) not in user["content"]
            assert publication.title not in user["content"]
            assert "origin=design" in suggestion["guidance"]
            ordinary_system, _ = build_messages({**calls[0], "design": {}})
            assert ordinary_system == system
        else:
            assert suggestion is None
        assert context["game_request"] == "Сделай космический шутер"
        assert "optional_analytics_hint" not in build_messages(calls[1])[1]["content"]

    [finished] = detail(client, workspace)["variant_batches"]
    hinted = finished["variants"][experiment.hint_variant_index - 1]["revision"]
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
    assert sample["published_variants"]["hinted"] == {
        "publications": 1, "sessions": 2, "sessions_30s": 1, "share_30s": 0.5, "ratings": 2, "mean_rating": 4.0,
    }
    other = next(v for v in finished["variants"] if v["index"] != experiment.hint_variant_index)
    assert client.patch(f"/api/publications/{published.pk}/", {"revision_id": other["revision"]["id"]},
                        content_type="application/json").status_code == 200
    updated = report()["published_variants"]
    assert updated["hinted"]["publications"] == 0
    assert updated["other_three"] == {
        "publications": 1, "sessions": 0, "sessions_30s": 0, "share_30s": None, "ratings": 0, "mean_rating": None,
    }
