from unittest.mock import patch

import pytest

from generation.providers.fake import generate as fake_generate
from studio.models import Chat, CheckReport, Invocation, User
from studio.replies import run_reply
from studio.serialization import run_data
from studio.services import create_run, finish_run
from studio.tasks import process_run
from tests.test_validation import fixture_report


@pytest.fixture
def completed_run(settings):
    settings.GAMEFORGE_PROVIDER = "fake"
    settings.GAMEFORGE_MODEL = "fixture"
    with (
        patch("studio.services.schedule"),
        patch("studio.tasks.dispatch_outbox"),
        patch("studio.tasks.dispatch_run"),
        patch("validation.service.environment_identity", return_value="reply-test"),
    ):
        chat = Chat.objects.create(owner=User.objects.create_user(username="reply-owner"))
        run = create_run(chat, {"prompt": "Собрать звёзды", "idempotency_key": "reply"})
        run.planning_required = False
        run.save(update_fields=["planning_required"])

        def response(request, **kwargs):
            result = fake_generate(request, **kwargs)
            result["response"]["message"] = "Соберите три звезды касанием. Управление простое, а цель видна сразу."
            return result

        with (
            patch("generation.providers.fake.generate", side_effect=response) as model,
            patch("validation.service.validate", side_effect=lambda html, checks, **kwargs: fixture_report(html, checks)),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        assert run.status == "succeeded", run.error
        assert model.call_count == 1  # The quick review adds no separate model stage.
        yield run


@pytest.mark.django_db
def test_completion_keeps_player_quality_text_and_adds_actual_verification(completed_run):
    run = completed_run
    reply = run.chat_messages.get(role="assistant").content
    assert reply.startswith("Соберите три звезды касанием. Управление простое, а цель видна сразу.")
    assert reply.endswith("Выполненные проверки пройдены — можно пробовать играть.")
    assert "пройдены" in run_data(run)["message"]
    assert run.invocations.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("problem", ["missing", "stale", "checks", "failed", "later_failure", "gates", "action", "other_version"])
def test_success_label_is_not_enough_to_announce_passed_checks(completed_run, problem):
    run = completed_run
    report = run.result_revision.reports.latest("id")
    if problem == "missing":
        report.delete()
    elif problem == "later_failure":
        CheckReport.objects.create(
            revision=run.result_revision, validation_run=run, status="failed", identity=report.identity,
        )
    elif problem == "other_version":
        revision = run.result_revision
        revision.artifact_hash = "different-game"
        revision.save(update_fields=["artifact_hash"])
    else:
        if problem == "stale":
            report.assessment["artifact_evidence"]["artifact_hash"] = "different-game"
        elif problem == "checks":
            report.checks = []
        elif problem == "failed":
            report.status = "failed"
        else:
            report.assessment["gates_passed" if problem == "gates" else "action"] = False if problem == "gates" else "review"
        report.save()
    reply = run_reply(run, "Всё проверено!")
    assert "подтвердить не удалось" in reply
    assert "пройдены" not in reply and "Всё проверено" not in reply


@pytest.mark.django_db
def test_result_uses_its_own_message_not_a_later_rejected_patch_or_check_review(completed_run):
    run = completed_run
    for attempt, operation, revision in [(2, "repair", None), (3, "check_repair", run.result_revision)]:
        Invocation.objects.create(
            run=run, attempt=attempt, state="settled", request={"operation": operation}, revision=revision,
            response={"status": "ok", "message": "Добавлены новые уровни и музыка."},
        )
    run.chat_messages.filter(role="assistant").delete()
    # Re-enter completion before an accepted base is advanced, as on a normal finish.
    run.chat.current_revision = run.base_revision
    run.chat.save(update_fields=["current_revision"])
    assert finish_run(run.id, run.fence, "succeeded", "Internal", revision=run.result_revision)
    reply = run.chat_messages.get(role="assistant").content
    assert "Соберите три звезды" in reply
    assert "уровни и музыка" not in reply


@pytest.mark.django_db
def test_technical_reply_is_private_and_terminal_fallback_hides_internal_errors(completed_run):
    run = completed_run
    invocation = run.invocations.get()
    invocation.response["message"] = "Исправлена функция updateScore() в game.js. Всё проверено!"
    invocation.raw_response = dict(invocation.response)
    invocation.save()
    run.chat_messages.filter(role="assistant").delete()
    run.chat.current_revision = run.base_revision
    run.chat.save(update_fields=["current_revision"])
    finish_run(run.id, run.fence, "succeeded", "Internal syntax details", revision=run.result_revision)
    assert run.chat_messages.get(role="assistant").content == (
        "Игра готова. Выполненные проверки пройдены — можно пробовать играть."
    )
    invocation.refresh_from_db()
    assert "game.js" in invocation.response["message"]
    assert invocation.raw_response == invocation.response
    run.status = "failed"
    run.message = "TypeError: undefined in game.js"
    run.error = {"code": "validator_unavailable", "message": run.message}
    data = run_data(run)
    assert "временно недоступна" in data["message"]
    assert "TypeError" not in data["message"]


@pytest.mark.django_db
def test_manual_acceptance_does_not_claim_automatic_success(completed_run):
    run = completed_run
    run.result_revision.verification = "manual"
    run.result_revision.save(update_fields=["verification"])
    assert "вашей проверки" in run_data(run)["message"]
    assert "пройдены" not in run_reply(run)
