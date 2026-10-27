from unittest.mock import patch

import pytest

from generation.artifacts import sha256
from studio.tasks import process_run
from studio.tests import test_visual_workflow as workflow
from studio.tests.test_visual_workflow import browser, response_for, start
from tests.test_compact_generation import compact_response

maker = workflow.maker


@pytest.mark.django_db
@pytest.mark.parametrize("use_browser", [False, pytest.param(True, marks=pytest.mark.browser)])
def test_compact_visual_patch_keeps_runtime_rules_and_frozen_criteria(maker, use_browser):
    run = start(maker, generation_profile="compact")

    def model(request, **kwargs):
        if request["operation"] == "create":
            return {"response": compact_response(), "usage": {"input_tokens": 10, "output_tokens": 20}}
        result = (
            response_for(request, **kwargs)
            if request["operation"] == "visual_review"
            else {
                "response": {
                    "operation": "visual_patch",
                    "status": "ok",
                    "message": "Уточнён контраст",
                    **{
                        k: request["visual_patch"][k]
                        for k in (
                            "base_revision",
                            "artifact_hash",
                            "report_id",
                            "report_identity",
                            "packet_hash",
                        )
                    },
                    "patches": [
                        {
                            "path": "game.js",
                            "file_hash": sha256(request["files"]["game.js"]),
                            "old_text": "'#ffd84d'",
                            "new_text": "'#ffe28a'",
                        }
                    ],
                },
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
        )
        if request["operation"] == "visual_review":
            result["response"]["issues"][0].update(path="game.js", defect="unreadable_text")
        return result

    from contextlib import nullcontext

    with (
        patch("generation.providers.fake.generate", side_effect=model) as provider,
        nullcontext() if use_browser else patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert provider.call_count == 3, run.visual_state
    original, improved = run.revisions.order_by("number")
    assert improved.accepted and improved.compact_manifest == original.compact_manifest
    assert (
        improved.checks == original.checks and improved.requirement_manifest == original.requirement_manifest
    )
    assert improved.helper_manifest == original.helper_manifest and improved.helper_manifest
    assert all(improved.files[p] == original.files[p] for p in original.files if p != "game.js")
    assert improved.files["game.js"].replace("'#ffe28a'", "'#ffd84d'") == original.files["game.js"]
    assert run.visual_state["phase"] == "done"
    if use_browser:
        assert original.reports.get().visual_evidence["status"] == "captured"
        assert improved.reports.get().visual_evidence["status"] == "captured"
