from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from generation.artifacts import sha256
from generation.errors import GenerationError
from generation.feedback_image import image_input
from generation.providers.fake import generate as fake_generate
from studio.models import Chat, Run, User
from studio.services import cancel_run, create_run
from studio.tasks import process_run
from tests.test_validation import fixture_report
from tests.test_visual_review import packet, review


@pytest.fixture
def maker(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    with (
        patch("studio.services.schedule"),
        patch("studio.tasks.dispatch_outbox"),
        patch("studio.tasks.dispatch_run"),
    ):
        yield Chat.objects.create(owner=User.objects.create_user(username="visual-maker"))


def start(chat, **kwargs):
    run = create_run(chat, {"prompt": "Три касания дают победу", "idempotency_key": "visual", **kwargs})
    run.generation_strategy = "pro"
    run.visual_review_enabled = True
    run.planning_required = False
    run.save(update_fields=["generation_strategy", "visual_review_enabled", "planning_required"])
    return run


def browser(html, checks, **kwargs):
    result = fixture_report(html, checks)
    if kwargs.get("capture_visual"):
        result["visual_evidence"] = packet(result["artifact_hash"], result["environment"])
    return result


def response_for(request, **kwargs):
    op = request["operation"]
    if op not in {"visual_review", "visual_patch"}:
        return fake_generate(request, **kwargs)
    assert image_input(request)
    if op == "visual_review":
        response = review(request[op])
    else:
        response = {
            **{
                k: request[op][k]
                for k in ("base_revision", "artifact_hash", "report_id", "report_identity", "packet_hash")
            },
            "operation": op,
            "status": "ok",
            "message": "Исправлено оформление",
            "patches": [
                {
                    "path": "styles.css",
                    "file_hash": sha256(request["files"]["styles.css"]),
                    "old_text": "#eff4ff",
                    "new_text": "#fff5e8",
                }
            ],
        }
    return {
        "response": response,
        "usage": {"input_tokens": 10, "output_tokens": 20, "cached_input_tokens": 0},
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "no_change",
        "taste",
        "suspected",
        "refusal",
        "malformed",
        "foreign_revision",
        "foreign_frame",
        "patch_refusal",
        "patch_invalid",
        "regression",
        "missing_recheck_frames",
        "known_failure",
    ],
)
def test_visual_cycle_is_bounded_and_keeps_verified_game(maker, fault):
    run = start(maker)

    def model(request, **kwargs):
        result = response_for(request, **kwargs)
        response = result["response"]
        if request["operation"] == "visual_review":
            if fault in {"no_change", "refusal"}:
                response.update(status="no_change" if fault == "no_change" else "scope_refusal", issues=[])
            if fault in {"taste", "suspected"}:
                response["issues"][0]["kind"] = "preference" if fault == "taste" else "suspected_defect"
            if fault == "malformed":
                response["files"] = []
            if fault == "foreign_revision":
                response["base_revision"] = "foreign"
            if fault == "foreign_frame":
                response["issues"][0]["frames"] = ["invented"]
            if fault == "known_failure":
                raise GenerationError("refused", "Отказ", outcome_unknown=False)
        if request["operation"] == "visual_patch":
            if fault == "patch_refusal":
                response.update(status="unchanged", patches=[])
            if fault == "patch_invalid":
                response["patches"][0]["old_text"] = "absent source"
        return result

    def validate(html, checks, **kwargs):
        result = browser(html, checks, **kwargs)
        if "#fff5e8" in html:
            if fault == "regression":
                result.update(status="failed", findings=[{"code": "runtime", "message": "Regression"}])
            if fault == "missing_recheck_frames":
                result["visual_evidence"] = {"status": "skipped"}
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=model) as provider,
        patch("validation.service.validate", side_effect=validate),
    ):
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    maker.refresh_from_db()
    assert run.status == "succeeded", run.error
    calls = [call.args[0]["operation"] for call in provider.call_args_list]
    assert calls[:2] == ["create", "visual_review"] and calls.count("visual_review") == 1
    assert calls.count("visual_patch") == (
        fault in {"none", "patch_refusal", "patch_invalid", "regression", "missing_recheck_frames"}
    )
    original = run.revisions.order_by("number").first()
    accepted = maker.current_revision
    assert (
        accepted.checks == original.checks and accepted.requirement_manifest == original.requirement_manifest
    )
    assert accepted.files["game.js"] == original.files["game.js"]
    assert (accepted.id != original.id) == (fault == "none")
    assert accepted.accepted and run.attempts == len(calls) <= run.max_model_calls
    assert all(i.state in {"settled", "failed"} for i in run.invocations.all())
    assert run.visual_state["phase"] in {"done", "skipped", "reverted"}


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["budget", "frames", "disabled", "deadline"])
def test_visual_review_skips_without_affecting_game_acceptance(maker, case):
    run = start(maker)
    if case == "budget":
        run.model_call_limit = 2
    if case == "disabled":
        run.visual_review_enabled = False
    run.save()

    def validate(html, checks, **kwargs):
        result = browser(html, checks, **kwargs)
        if case == "frames":
            result["visual_evidence"] = {}
        if case == "deadline":
            Run.objects.filter(pk=run.id).update(model_call_deadline=timezone.now() - timedelta(seconds=1))
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=response_for) as provider,
        patch("validation.service.validate", side_effect=validate),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert [c.args[0]["operation"] for c in provider.call_args_list] == ["create"]


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["unknown", "cancel"])
def test_visual_interruption_preserves_candidate_and_never_repeats_call(maker, case):
    run = start(maker)

    def model(request, **kwargs):
        result = response_for(request, **kwargs)
        if request["operation"] == "visual_review":
            if case == "unknown":
                raise GenerationError("lost", "Неизвестный исход", outcome_unknown=True)
            cancel_run(Run.objects.get(pk=run.id))
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=model) as provider,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    maker.refresh_from_db()
    assert run.status == ("unknown" if case == "unknown" else "cancelled"), run.error
    assert provider.call_count == 2 and run.candidate_revision and not maker.current_revision
    assert run.candidate_revision.reports.filter(status="passed").exists()
    assert not run.invocations.filter(request__operation="visual_patch").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("fault", ["report", "packet", "revision"])
def test_saved_visual_receipt_cannot_apply_to_stale_evidence(maker, fault):
    run = start(maker)

    def model(request, **kwargs):
        result = response_for(request, **kwargs)
        if request["operation"] == "visual_review":
            base = Run.objects.get(pk=run.id).candidate_revision
            report = base.reports.latest("id")
            if fault == "report":
                report.pk = None
                report.save()
            elif fault == "packet":
                value = deepcopy(report.visual_evidence)
                value["frames"][0]["sha256"] = "stale"
                report.visual_evidence = value
                report.save(update_fields=["visual_evidence"])
            else:
                result["response"]["base_revision"] = "another revision"
        return result

    with (
        patch("generation.providers.fake.generate", side_effect=model) as provider,
        patch("validation.service.validate", side_effect=browser),
    ):
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded" and provider.call_count == 2
    assert run.visual_state["phase"] == "skipped" and run.revisions.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["visual_review", "visual_patch"])
def test_worker_reentry_consumes_durable_visual_receipt_once(maker, operation):
    from studio.services import settle_invocation
    from studio.tasks import recover_expired

    class Crash(BaseException):
        pass

    run = start(maker)

    def saved(ident, **kwargs):
        receipt = settle_invocation(ident, **kwargs)
        if (kwargs.get("response") or {}).get("operation") == operation:
            raise Crash()
        return receipt

    with (
        patch("generation.providers.fake.generate", side_effect=response_for) as provider,
        patch("validation.service.validate", side_effect=browser),
    ):
        with patch("studio.tasks.settle_invocation", side_effect=saved), pytest.raises(Crash):
            process_run(str(run.id))
        before = provider.call_count
        Run.objects.filter(pk=run.id).update(lease_until=timezone.now() - timedelta(seconds=1))
        recover_expired()
        process_run(str(run.id))
        process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == "succeeded", run.error
    assert run.attempts == provider.call_count == 3
    assert provider.call_count - before == (operation == "visual_review")
    assert run.revisions.count() == 2 and run.invocations.filter(state="settled").count() == 3
