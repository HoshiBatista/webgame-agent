import hashlib
import json
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from generation.providers.fake import fixture_response
from studio.models import Budget, Chat, Invocation, Publication, Revision, User
from studio.services import budget_snapshot, create_run, reserve_invocation, settle_invocation, usage_cost
from studio.tasks import process_run, recover_expired

HTML = "<html><body><canvas></canvas><script>let x=1;</script></body></html>"


def artifact(title="Generated"):
    return {
        "files": {"index.html": HTML},
        "html": HTML,
        "artifact_hash": hashlib.sha256(HTML.encode()).hexdigest(),
        "file_hashes": {"index.html": hashlib.sha256(HTML.encode()).hexdigest()},
        "design": {"summary": "Independent game"},
        # Packaging is mocked in these workflow tests; its output must still
        # satisfy the admission contract before another repair can be reserved.
        "checks": fixture_response()["checks"],
        "title": title,
        "diff": [],
    }


def response():
    return {
        "response": {"status": "ok", "operation": "create"},
        "usage": {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 50},
        "provider": "fake",
        "model": "fixture",
        "invocation_id": "test",
        "elapsed_seconds": 0.1,
    }


PASS = {
    "status": "passed",
    "findings": [],
    "facts": [{"actual_input": True}],
    "environment": {"version": "test"},
    "elapsed_seconds": 0.01,
}
FAIL = {
    "status": "failed",
    "findings": [{"code": "runtime_or_network", "errors": ["TypeError: input handler failed"]}],
    "facts": [],
}


@override_settings(
    GAMEFORGE_RUN_INLINE=False,
    GAMEFORGE_PROVIDER="fake",
    GAMEFORGE_MODEL="fixture",
    GAMEFORGE_LEASE_SECONDS=100,
)
class DomainTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="Maker", password="correct-password")
        self.other = User.objects.create_user(username="Other", password="correct-password")
        self.chat = Chat.objects.create(owner=self.user)
        self.client.force_login(self.user)

    def make_run(self, chat=None, key="request", prompt="Make a game"):
        target = chat or self.chat
        target.refresh_from_db()
        data = {"prompt": prompt, "idempotency_key": key}
        if target.current_revision:
            data.update(source_revision_id=str(target.current_revision_id),
                        source_artifact_hash=target.current_revision.artifact_hash)
        return create_run(target, data)

    def test_username_database_case_insensitive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="mAKER", password="secret")
        c = Client()
        s = c.post(
            "/api/login/",
            {"username": "MAKER", "password": "correct-password"},
            content_type="application/json",
        )
        self.assertEqual(s.status_code, 200)

    def test_unavailable_chat_has_safe_message_and_cannot_start_generation(self):
        foreign = Chat.objects.create(owner=self.other)
        self.chat.deleted_at = timezone.now()
        self.chat.save(update_fields=['deleted_at'])
        for ident in [self.chat.id, foreign.id, uuid.uuid4()]:
            with self.subTest(chat=ident):
                for response in [
                    self.client.get(f'/api/chats/{ident}/'),
                    self.client.post(f'/api/chats/{ident}/runs/',
                                     {'prompt': 'Make a game', 'idempotency_key': 'missing-chat'},
                                     content_type='application/json'),
                ]:
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json(), {'error': {
                        'code': 'chat_not_found',
                        'message': 'Этот чат удалён или недоступен. Создайте новую игру.',
                        'details': None,
                    }})
        self.assertFalse(Invocation.objects.exists())
        self.assertFalse(self.chat.runs.exists())
        self.assertFalse(foreign.runs.exists())

    def test_csrf_login_and_authenticated_mutation(self):
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(
            c.post(
                "/api/login/",
                {"username": "Maker", "password": "correct-password"},
                content_type="application/json",
            ).status_code,
            403,
        )
        token = c.get("/api/session/").json()["csrfToken"]
        login = c.post(
            "/api/login/",
            {"username": "maker", "password": "correct-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(c.post("/api/chats/", {}, content_type="application/json").status_code, 403)
        self.assertEqual(
            c.post(
                "/api/chats/", {}, content_type="application/json", HTTP_X_CSRFTOKEN=login.json()["csrfToken"]
            ).status_code,
            201,
        )

    def test_bootstrap_does_not_replace_password(self):
        with patch.dict(
            os.environ,
            {"DJANGO_SUPERUSER_USERNAME": "admin", "DJANGO_SUPERUSER_PASSWORD": "original-password"},
        ):
            call_command("bootstrap")
        with patch.dict(
            os.environ,
            {"DJANGO_SUPERUSER_USERNAME": "ADMIN", "DJANGO_SUPERUSER_PASSWORD": "replacement-password"},
        ):
            call_command("bootstrap")
        self.assertTrue(User.objects.get(username="admin").check_password("original-password"))

    def test_idempotency_and_single_writer(self):
        run = self.make_run()
        self.assertEqual(self.make_run().id, run.id)
        self.assertEqual(
            self.client.post(
                f"/api/chats/{self.chat.id}/runs/",
                {"prompt": "Different", "idempotency_key": "request"},
                content_type="application/json",
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                f"/api/chats/{self.chat.id}/runs/",
                {"prompt": "Other", "idempotency_key": "second"},
                content_type="application/json",
            ).status_code,
            409,
        )
        second = Chat.objects.create(owner=self.user)
        self.assertNotEqual(self.make_run(second).id, run.id)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/api/chats/{self.chat.id}/").status_code, 404)

    def test_generation_duplicate_delivery_and_saved_result(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()) as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS) as check,
        ):
            process_run(str(run.id))
            process_run(str(run.id))
        run.refresh_from_db()
        self.chat.refresh_from_db()
        self.assertEqual(run.status, "succeeded", run.error)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(self.chat.current_revision_id, run.result_revision_id)
        self.assertEqual(Revision.objects.count(), 1)
        self.assertEqual(run.invocations.get().state, "settled")

    def test_bounded_auto_repairs_then_explicit_continuation(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()) as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=FAIL),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "needs_attention", run.error)
        self.assertEqual(model.call_count, 2)
        self.assertEqual([call.args[0]["operation"] for call in model.call_args_list],
                         ["create", "repair"])
        candidate = run.candidate_revision
        next_run = create_run(self.chat, {"idempotency_key": "continue"}, continued_from=run)
        with (
            patch("generation.service.generate", return_value=response()) as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(next_run.id))
        self.assertEqual(model.call_args.args[0]["base_revision"], str(candidate.id))
        self.assertEqual(model.call_args.args[0]["operation"], "repair")

    def test_cancel_late_response_preserves_current(self):
        run = self.make_run()

        def cancel_inside(*args, **kwargs):
            self.client.post(f"/api/runs/{run.id}/cancel/", {}, content_type="application/json")
            return response()

        with (
            patch("generation.service.generate", side_effect=cancel_inside),
            patch("generation.artifacts.materialize") as pack,
            patch("validation.service.validate") as check,
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.chat.refresh_from_db()
        self.assertEqual(run.status, "cancelled")
        self.assertIsNone(self.chat.current_revision)
        pack.assert_not_called()
        check.assert_not_called()
        self.assertIsNotNone(run.invocations.get().response)

    def test_unknown_does_not_blind_retry(self):
        from generation.errors import GenerationError

        run = self.make_run()
        with (
            patch(
                "generation.service.generate",
                side_effect=GenerationError("connection_lost", "Lost", outcome_unknown=True),
            ),
            patch("generation.artifacts.materialize"),
            patch("validation.service.validate"),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "unknown", run.error)
        self.assertEqual(
            self.client.post(
                f"/api/runs/{run.id}/continue/", {}, content_type="application/json"
            ).status_code,
            409,
        )

    def test_explicit_unknown_retry_preserves_liability_and_is_idempotent(self):
        base = Revision.objects.create(chat=self.chat, number=1, accepted=True,
                                       verification="automatic", **artifact())
        self.chat.current_revision = base
        self.chat.save(update_fields=["current_revision"])
        run = self.make_run(prompt="Improve the controls")
        run.status = "unknown"
        run.save(update_fields=["status"])
        inv = Invocation.objects.create(run=run, attempt=1, state="unknown", request={},
                                        reservation_usd=Decimal("0.314"))
        Budget.objects.get_or_create(pk=1)
        data = self.client.get(f"/api/runs/{run.id}/").json()
        self.assertTrue(data["can_retry_unknown"])
        self.assertFalse(data["can_continue"])
        path = f"/api/runs/{run.id}/continue/"
        for consent in (None, False, "true"):
            self.assertEqual(self.client.post(path, {"accept_unknown_cost": consent},
                                             content_type="application/json").status_code, 409)
        body = {"accept_unknown_cost": True, "idempotency_key": "explicit-retry"}
        first = self.client.post(path, body, content_type="application/json")
        second = self.client.post(path, body, content_type="application/json")
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(budget_snapshot()["unknown_usd"], 0.314)
        inv.refresh_from_db()
        self.assertEqual(inv.state, "unknown")
        self.assertIsNone(inv.cost_usd)
        self.assertEqual(self.chat.runs.count(), 2)
        with patch("generation.service.generate", return_value=response()) as model, \
             patch("generation.artifacts.materialize", return_value=artifact()), \
             patch("validation.service.validate", return_value=PASS):
            process_run(first.json()["id"])
        self.assertEqual(model.call_args.args[0]["operation"], "edit")
        self.assertEqual(model.call_args.args[0]["base_revision"], str(base.id))
        self.assertEqual(model.call_args.args[0]["prompt"], run.prompt)
        base.refresh_from_db()
        self.assertEqual(base.html, HTML)
        run.refresh_from_db()
        self.assertEqual(run.status, "unknown")
        self.assertEqual(budget_snapshot()["unknown_usd"], 0.314)
        # A fresh retry must not reapply an old instruction to a newer working game.
        body["idempotency_key"] = "another-retry"
        rejected = self.client.post(path, body, content_type="application/json")
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "retry_base_changed")
        self.assertFalse(self.client.get(f"/api/runs/{run.id}/").json()["can_retry_unknown"])

    def test_new_request_after_unknown_uses_displayed_source_and_keeps_liability(self):
        historical = Revision.objects.create(chat=self.chat, number=1, accepted=True, **artifact("First"))
        current = Revision.objects.create(chat=self.chat, number=2, accepted=True, **artifact("Current"))
        self.chat.current_revision = current
        self.chat.save(update_fields=["current_revision"])
        original = self.make_run(prompt="Old instruction")
        original.status = "unknown"
        original.save(update_fields=["status"])
        inv = Invocation.objects.create(run=original, attempt=1, state="unknown", request={},
                                        reservation_usd=Decimal("0.314"))
        Budget.objects.get_or_create(pk=1)
        path = f"/api/chats/{self.chat.id}/runs/"
        body = {
            "prompt": "New instruction", "audience": "children", "idempotency_key": "new-after-unknown",
            "source_revision_id": str(historical.id), "source_artifact_hash": historical.artifact_hash,
            "source_is_historical": True, "acknowledge_unknown_run_id": str(original.id),
        }
        self.assertEqual(self.client.post(path, body, content_type="application/json").status_code, 409)
        body["accept_unknown_cost"] = True
        created = self.client.post(path, body, content_type="application/json")
        self.assertEqual(created.status_code, 202, created.content)
        duplicate = self.client.post(path, body, content_type="application/json")
        self.assertEqual(created.json()["id"], duplicate.json()["id"])
        run = self.chat.runs.get(pk=created.json()["id"])
        self.assertEqual(run.operation, "edit")
        self.assertEqual(run.source_revision_id, historical.id)
        self.assertEqual(run.base_revision_id, current.id)
        self.assertIsNone(run.continued_from_id)
        self.assertEqual(run.audience, "children")
        self.assertEqual(run.events.get(kind="explicit_retry").details["unknown_invocation_ids"], [str(inv.id)])
        with patch("generation.service.generate", return_value=response()) as model, \
             patch("generation.artifacts.materialize", return_value=artifact()), \
             patch("validation.service.validate", return_value=PASS):
            process_run(str(run.id))
        self.assertEqual(model.call_args.args[0]["base_revision"], str(historical.id))
        self.assertEqual(model.call_args.args[0]["prompt"], "New instruction")
        self.assertEqual(model.call_args.args[0]["audience"], "children")
        self.assertEqual(budget_snapshot()["unknown_usd"], 0.314)
        inv.refresh_from_db()
        self.assertEqual(inv.state, "unknown")

    def test_unknown_acknowledgement_cannot_reference_another_chat(self):
        other = self.make_run(Chat.objects.create(owner=self.other))
        result = self.client.post(f"/api/chats/{self.chat.id}/runs/", {
            "prompt": "New game", "idempotency_key": "foreign-unknown",
            "acknowledge_unknown_run_id": str(other.id), "accept_unknown_cost": True,
        }, content_type="application/json")
        self.assertEqual(result.status_code, 409)
        self.assertFalse(self.chat.runs.exists())

    def test_cancellation_reply_is_saved_once_and_survives_a_new_request(self):
        run = self.make_run()
        path = f"/api/runs/{run.id}/cancel/"
        for _ in range(2):
            self.assertEqual(self.client.post(path, {}, content_type="application/json").status_code, 200)
        self.make_run(key="next", prompt="Another game")
        messages = run.chat_messages.filter(role="assistant")
        self.assertEqual(messages.count(), 1)
        self.assertIn("Генерация остановлена", messages.get().content)
        history = self.client.get(f"/api/chats/{self.chat.id}/").json()["messages"]
        saved = next(item for item in history if item["id"] == str(messages.get().id))
        self.assertEqual(saved["generation"]["status"], "cancelled")

    def test_infrastructure_continue_rechecks_without_model(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()),
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch(
                "validation.service.validate", return_value={"status": "infrastructure_error", "findings": []}
            ),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "failed", run.error)
        follow = create_run(self.chat, {"idempotency_key": "resume"}, continued_from=run)
        with (
            patch("generation.service.generate") as model,
            patch("generation.artifacts.materialize"),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(follow.id))
        model.assert_not_called()
        follow.refresh_from_db()
        self.assertEqual(follow.status, "succeeded")

    def test_recovery_uses_saved_response(self):
        run = self.make_run()
        run.status = "generating"
        run.fence = __import__("uuid").uuid4()
        run.lease_until = timezone.now() - timedelta(seconds=1)
        run.attempts = 1
        run.save()
        Invocation.objects.create(
            run=run,
            attempt=1,
            request={"base_revision": None, "operation": "create"},
            response={"status": "ok"},
            state="returned",
            cost_usd=0,
            finished_at=timezone.now(),
        )
        recover_expired()
        with (
            patch("generation.service.generate") as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(run.id))
        model.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, "succeeded", run.error)

    def test_unknown_usage_reserved_classification(self):
        run = self.make_run()
        run.provider = "codex"
        run.model = "gpt-6-luna"
        run.save()
        inv = reserve_invocation(run, {})
        self.assertEqual(budget_snapshot()["reserved_usd"], float(inv.reservation_usd))
        inv.state = "sent"
        inv.sent_at = timezone.now()
        inv.save()
        settle_invocation(inv.id, error={"code": "lost"}, unknown=True)
        snapshot = budget_snapshot()
        self.assertEqual(snapshot["reserved_usd"], 0)
        self.assertEqual(snapshot["unknown_usd"], float(inv.reservation_usd))
        self.assertEqual(snapshot["available_usd"], float(Decimal(50) - inv.reservation_usd))

    def test_cached_usage_cost(self):
        self.assertEqual(
            usage_cost(
                {"input_tokens": 1000000, "cached_input_tokens": 900000, "output_tokens": 1000},
                {"input": 2, "cached": 0.1, "output": 10},
            ),
            Decimal(".300000"),
        )

    def test_unknown_partial_usage_holds_full_liability_until_final_receipt(self):
        run = self.make_run()
        run.provider = "codex"
        run.model = "gpt-6-luna"
        run.save()
        inv = reserve_invocation(run, {"operation": "create"})
        inv.state = "sent"
        inv.sent_at = timezone.now()
        inv.save()
        partial = {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 50}
        settle_invocation(inv.id, usage=partial, error={"code": "connection_lost"}, unknown=True)
        inv.refresh_from_db()
        self.assertIsNone(inv.cost_usd)
        self.assertEqual(inv.usage, partial)
        snapshot = budget_snapshot()
        self.assertEqual(snapshot["spent_usd"], 0)
        self.assertEqual(snapshot["reserved_usd"], 0)
        self.assertEqual(snapshot["unknown_usd"], float(inv.reservation_usd))
        final = {**partial, "output_tokens": 150}
        settle_invocation(inv.id, response=response()["response"], usage=final)
        snapshot = budget_snapshot()
        self.assertEqual(snapshot["unknown_usd"], 0)
        self.assertEqual(snapshot["reserved_usd"], 0)
        self.assertEqual(snapshot["spent_usd"], float(usage_cost(final, inv.price)))
        self.assertEqual(snapshot["available_usd"], 50 - snapshot["spent_usd"])

    def test_known_provider_rejection_releases_reservation_without_cost(self):
        for sent in (False, True):
            with self.subTest(sent=sent):
                run = self.make_run(Chat.objects.create(owner=self.user))
                run.provider = "codex"
                run.model = "gpt-6-luna"
                run.save()
                inv = reserve_invocation(run, {"operation": "create"})
                if sent:
                    inv.sent_at = timezone.now()
                    inv.state = "sent"
                    inv.save()
                settle_invocation(inv.id, error={"code": "provider_http_error"}, unknown=False)
                inv.refresh_from_db()
                self.assertEqual(inv.cost_usd, 0)
                self.assertEqual(inv.state, "failed")
        snapshot = budget_snapshot()
        self.assertEqual(snapshot["spent_usd"], 0)
        self.assertEqual(snapshot["reserved_usd"], 0)
        self.assertEqual(snapshot["unknown_usd"], 0)

    @patch('validation.service.environment_identity', return_value='test-validator')
    def test_unverified_needs_confirmation(self, _identity):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()),
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch(
                "validation.service.validate",
                return_value={"status": "unverified", "environment": "test-validator", "findings": [{"message": "Check end condition"}],
                              "gates": {"syntax": True, "runtime": True, "surface": True},
                              "stages": [{"stage": "syntax", "status": "passed"}],
                              "facts": [{**{k: c[k] for k in ("id", "category", "requirement", "viewport")},
                                         "surface": {"canvases": [{"visible": True, "width": 300, "height": 300}], "overflow": False}}
                                        for c in artifact()["checks"]]},
            ),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "unverified")
        self.assertEqual(
            self.client.post(
                "/api/publications/",
                {"chat_id": str(self.chat.id), "title": "Game", "revision_id": str(run.candidate_revision_id)},
                content_type="application/json",
            ).status_code,
            201,
        )
        self.assertEqual(
            self.client.post(
                f"/api/runs/{run.id}/confirm/", {"confirmed": True,
                    "artifact_hash": run.candidate_revision.artifact_hash,
                    "report_id": run.candidate_revision.reports.get().id}, content_type="application/json"
            ).status_code,
            200,
        )
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.current_revision.verification, "manual")

    def test_publication_snapshot_remix_and_delete_chat(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()),
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(run.id))
        self.chat.refresh_from_db()
        pub = self.client.post(
            "/api/publications/",
            {"chat_id": str(self.chat.id), "title": "Shared"},
            content_type="application/json",
        ).json()
        self.client.force_login(self.other)
        remix = self.client.post(
            f"/api/publications/{pub['id']}/remix/", {}, content_type="application/json"
        ).json()
        self.assertEqual(remix["messages"], [])
        self.assertEqual(remix["current_revision"]["artifact_hash"], pub["artifact_hash"])
        for _ in range(2):
            self.client.put(
                f"/api/publications/{pub['id']}/like/", {"liked": True}, content_type="application/json"
            )
        self.assertEqual(Publication.objects.get(pk=pub["id"]).likes.count(), 1)
        self.client.force_login(self.user)
        self.assertEqual(self.client.delete(f"/api/chats/{self.chat.id}/").status_code, 204)
        self.assertEqual(self.client.get(f"/api/publications/{pub['id']}/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/chats/{self.chat.id}/").status_code, 404)

    def test_events_reconnect_and_private_diagnostics(self):
        run = self.make_run()
        event_id = run.events.first().id
        response = self.client.get(f"/api/runs/{run.id}/events/?after={event_id}")
        content = b"".join(response.streaming_content).decode()
        self.assertNotIn("event: progress", content)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/api/runs/{run.id}/diagnostics/").status_code, 404)

    def test_feedback_saved_before_background_processing_changes_preferences(self):
        revision = Revision.objects.create(chat=self.chat, number=1, **artifact())
        response = self.client.post(
            f"/api/chats/{self.chat.id}/feedback/",
            {"rating": 3, "reasons": ["Make controls larger"], "revision_id": str(revision.id)},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Invocation.objects.count(), 0)
        self.assertEqual(self.client.get("/api/preferences/").json()["notes"], [])
        self.assertEqual(response.json()["feedback"]["custom_reason"], "Make controls larger")
        self.assertEqual(response.json()["feedback"]["processing_status"], "queued")

    def test_preview_isolation_same_bytes(self):
        revision = Revision.objects.create(
            chat=self.chat, number=1, **{k: v for k, v in artifact().items() if k != "diff"}
        )
        url = self.client.get(f"/api/revisions/{revision.id}/preview/").json()["url"]
        from urllib.parse import urlparse

        path = urlparse(url).path
        self.assertEqual(self.client.get(path).status_code, 403)
        response = self.client.get(path, HTTP_HOST="localhost:8001")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), HTML)
        self.assertIn("connect-src 'none'", response["Content-Security-Policy"])
        controlled = self.client.get(path + '?audio_control=1', HTTP_HOST="localhost:8001")
        self.assertEqual(controlled.status_code, 200)
        self.assertTrue(controlled.content.decode().endswith(HTML))
        self.assertIn('gameforge:audio-ready', controlled.content.decode())
        self.assertEqual(controlled['Content-Security-Policy'], response['Content-Security-Policy'])
        revision.refresh_from_db()
        self.assertEqual(revision.html, HTML)

    def test_logout_returns_a_clean_guest_session_without_another_round_trip(self):
        result = self.client.post('/api/logout/').json()
        self.assertTrue(result['ok'])
        self.assertIsNone(result['user'])
        self.assertIsNone(result['budget'])
        self.assertEqual(result['preferences']['notes'], [])
        self.assertTrue(result['csrfToken'])
        self.assertEqual(self.client.get(f'/api/chats/{self.chat.id}/').status_code, 403)

    def test_contract_error_gets_one_repair(self):
        from generation.errors import ContractError

        run = self.make_run()
        invalid = ContractError(
            "invalid_schema",
            "Missing required checks",
            usage=response()["usage"],
            raw_response={"bad": "reply"},
        )
        with (
            patch("generation.service.generate", side_effect=[invalid, response()]) as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "succeeded", run.error)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args.args[0]["findings"][0]["code"], "invalid_schema")
        self.assertEqual(model.call_args.args[0]["operation"], "create")

    def test_cancelled_complete_response_can_resume_without_rebilling(self):
        run = self.make_run()

        def late_result(*a, **kw):
            self.client.post(f"/api/runs/{run.id}/cancel/", {}, content_type="application/json")
            return response()

        with patch("generation.service.generate", side_effect=late_result):
            process_run(str(run.id))
        run.refresh_from_db()
        follow = create_run(self.chat, {"idempotency_key": "resume"}, continued_from=run)
        with (
            patch("generation.service.generate") as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(follow.id))
        model.assert_not_called()
        follow.refresh_from_db()
        self.assertEqual(follow.status, "succeeded", follow.error)

    def test_lost_queue_delivery_is_redispatched(self):
        from studio.models import Outbox
        from studio.tasks import dispatch_outbox

        run = self.make_run()
        Outbox.objects.filter(run=run).update(dispatched_at=timezone.now() - timedelta(minutes=1))
        with patch("studio.tasks.process_run.delay") as delivery:
            dispatch_outbox()
        delivery.assert_called_once_with(str(run.id))

    def test_immediate_delivery_runs_only_after_database_commit(self):
        with (
            patch("studio.tasks.process_run.delay") as delivery,
            self.captureOnCommitCallbacks(execute=True),
        ):
            run = self.make_run()
            delivery.assert_not_called()
        delivery.assert_called_once_with(str(run.id))

    def test_outbox_publisher_does_not_overwrite_busy_worker_reset(self):
        from studio.models import Outbox
        from studio.tasks import dispatch_run

        run = self.make_run()

        def worker_busy(run_id):
            self.assertIsNotNone(Outbox.objects.get(run_id=run_id).dispatched_at)
            Outbox.objects.filter(run_id=run_id).update(dispatched_at=None)

        with patch("studio.tasks.process_run.delay", side_effect=worker_busy):
            self.assertTrue(dispatch_run(run.id))
        self.assertIsNone(Outbox.objects.get(run=run).dispatched_at)

    def test_broker_failure_keeps_durable_outbox_for_retry(self):
        from studio.models import Outbox
        from studio.tasks import dispatch_outbox, dispatch_run

        run = self.make_run()
        with patch("studio.tasks.process_run.delay", side_effect=ConnectionError("broker unavailable")):
            self.assertFalse(dispatch_run(run.id))
        self.assertIsNone(Outbox.objects.get(run=run).dispatched_at)
        with patch("studio.tasks.process_run.delay") as delivery:
            dispatch_outbox()
        delivery.assert_called_once_with(str(run.id))

    def test_periodic_queue_maintenance_does_not_accumulate_late_acks(self):
        from django.conf import settings

        from studio.tasks import dispatch_outbox, recover_expired

        self.assertFalse(dispatch_outbox.acks_late)
        self.assertFalse(recover_expired.acks_late)
        for periodic in settings.CELERY_BEAT_SCHEDULE.values():
            self.assertLessEqual(periodic["options"]["expires"], periodic["schedule"])

    def test_finishing_worker_immediately_wakes_waiting_outbox(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()),
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
            patch("studio.tasks.dispatch_outbox") as dispatch,
            self.captureOnCommitCallbacks(execute=True),
        ):
            process_run(str(run.id))
            dispatch.assert_not_called()
        dispatch.assert_called_once_with()

    def test_lost_worker_before_send_preserves_reservation_for_recovery(self):
        run = self.make_run()
        run.status = "generating"
        run.lease_until = timezone.now() - timedelta(seconds=1)
        run.attempts = 1
        run.save()
        Invocation.objects.create(run=run, attempt=1, request={}, state="reserved", reservation_usd=1)
        recover_expired()
        self.assertEqual(budget_snapshot()["reserved_usd"], 1)
        self.assertEqual(run.invocations.get().state, "reserved")
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")

    def test_late_receipt_resolves_unknown_for_explicit_continue(self):
        run = self.make_run()
        run.status = "unknown"
        run.save()
        Budget.objects.get_or_create(pk=1)
        inv = Invocation.objects.create(
            run=run,
            attempt=1,
            request={"base_revision": None, "operation": "create"},
            state="unknown",
            sent_at=timezone.now(),
            finished_at=timezone.now(),
            reservation_usd=1,
            price={"input": 0, "cached": 0, "output": 0},
        )
        settle_invocation(inv.id, response=response()["response"], usage=response()["usage"])
        run.refresh_from_db()
        self.assertEqual(run.status, "needs_attention")
        follow = create_run(self.chat, {"idempotency_key": "late"}, continued_from=run)
        with (
            patch("generation.service.generate") as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(follow.id))
        model.assert_not_called()
        follow.refresh_from_db()
        self.assertEqual(follow.status, "succeeded")

    def test_nullable_screenshot_does_not_lose_validation(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()),
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch(
                "validation.service.validate",
                return_value={"status": "unverified", "findings": [], "screenshot_base64": None},
            ),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "needs_attention", run.error)
        self.assertEqual(run.candidate_revision.reports.get().screenshot_base64, "")

    def test_unexpected_exception_trace_is_private(self):
        run = self.make_run()
        with patch("studio.tasks._execute", side_effect=RuntimeError("private-test-detail")):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("private-test-detail", run.private_diagnostics[0]["traceback"])
        self.assertNotIn("private-test-detail", json.dumps(self.client.get(f"/api/runs/{run.id}/").json()))
        self.assertIn(
            "private-test-detail", json.dumps(self.client.get(f"/api/runs/{run.id}/diagnostics/").json())
        )

    def test_postsend_storage_failure_preserves_unknown_liability(self):
        run = self.make_run()

        def interrupted(active, *args):
            Invocation.objects.create(
                run=active, attempt=1, request={}, state="sent", sent_at=timezone.now(), reservation_usd=1
            )
            raise RuntimeError("Receipt store interrupted")

        with patch("studio.tasks._execute", side_effect=interrupted):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "unknown")
        self.assertEqual(budget_snapshot()["reserved_usd"], 0)
        self.assertEqual(budget_snapshot()["unknown_usd"], 1)
        self.assertFalse(self.client.get(f"/api/runs/{run.id}/").json()["can_continue"])

    def test_candidate_storage_error_keeps_receipt_for_free_continuation(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()) as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("studio.tasks.store_candidate", side_effect=IntegrityError("candidate storage failed")),
            patch("validation.service.validate") as check,
        ):
            process_run(str(run.id))
        model.assert_called_once()
        check.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.invocations.get().state, "returned")
        self.assertFalse(run.events.filter(kind="contract_error").exists())
        self.assertIn("candidate storage failed", run.private_diagnostics[0]["traceback"])
        follow = create_run(self.chat, {"idempotency_key": "storage-fixed"}, continued_from=run)
        with (
            patch("generation.service.generate") as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(follow.id))
        model.assert_not_called()
        follow.refresh_from_db()
        self.assertEqual(follow.status, "succeeded", follow.error)
        self.assertEqual(follow.metrics["model_calls"], 0)

    def test_unexpected_materializer_error_does_not_spend_auto_repair(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()) as model,
            patch("generation.artifacts.materialize", side_effect=RuntimeError("packaging bug")),
            patch("validation.service.validate") as check,
        ):
            process_run(str(run.id))
        model.assert_called_once()
        check.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.invocations.get().state, "returned")
        self.assertEqual(run.error["code"], "internal_error")

    def test_private_provider_receipt_and_generation_fingerprints_are_saved(self):
        from generation.prompts import system_prompt
        from generation.schema import CONTRACT_VERSION, response_schema
        from studio.services import fingerprint

        run = self.make_run()
        receipt = {
            **response(),
            "provider_metadata": {"thread_id": "provider-thread", "turn_id": "provider-turn"},
            "invocation_id": "local-execution-id",
        }
        with (
            patch("generation.service.generate", return_value=receipt),
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            process_run(str(run.id))
        inv = run.invocations.get()
        self.assertEqual(inv.provider_invocation_id, "provider-turn")
        self.assertEqual(inv.provider_metadata["thread_id"], "provider-thread")
        self.assertEqual(inv.provider_metadata["execution_id"], "local-execution-id")
        self.assertEqual(
            inv.request["generation_contract"],
            {
                "system_prompt_sha256": hashlib.sha256(system_prompt(inv.request).encode()).hexdigest(),
                "response_schema_sha256": fingerprint(response_schema(inv.request)),
                "pipeline_version": CONTRACT_VERSION,
                "max_repair_attempts": 3,
                "reported_findings": 0,
                "focused_findings": 0,
            },
        )
        regular = json.dumps(self.client.get(f"/api/runs/{run.id}/").json())
        self.assertNotIn("provider-thread", regular)
        private = self.client.get(f"/api/runs/{run.id}/diagnostics/").json()["invocations"][0]
        self.assertEqual(private["provider_invocation_id"], "provider-turn")
        self.assertEqual(private["provider_metadata"]["thread_id"], "provider-thread")

    def test_provider_error_metadata_remains_available_for_reconciliation(self):
        from generation.errors import GenerationError

        run = self.make_run()
        error = GenerationError("connection_lost", "Lost", outcome_unknown=True)
        error.provider_metadata = {"thread_id": "lost-thread", "turn_id": "lost-turn"}
        with patch("generation.service.generate", side_effect=error):
            process_run(str(run.id))
        inv = run.invocations.get()
        self.assertEqual(inv.state, "unknown")
        self.assertEqual(inv.provider_invocation_id, "lost-turn")
        self.assertEqual(inv.provider_metadata["thread_id"], "lost-thread")

    def test_continue_preserves_selected_provider_and_model(self):
        run = self.make_run()
        run.status = "failed"
        run.provider = "codex"
        run.model = "gpt-6.1-sol"
        run.save()
        follow = create_run(self.chat, {"idempotency_key": "preserve-model"}, continued_from=run)
        self.assertEqual(follow.provider, "codex")
        self.assertEqual(follow.model, "gpt-6.1-sol")

    def test_empty_edit_cannot_claim_success_or_create_identical_revision(self):
        from generation.providers.fake import fixture_response

        initial = self.make_run()
        with patch("validation.service.validate", return_value=PASS):
            process_run(str(initial.id))
        self.chat.refresh_from_db()
        base = self.chat.current_revision
        edit = self.make_run(key="empty-edit", prompt="Добавь второй уровень")
        empty = {
            **fixture_response(),
            "operation": "edit",
            "base_revision": str(base.id),
            "files": [],
            "patches": [],
            "checks": [],
            "message": "Добавлен второй уровень",
        }
        with (
            patch("generation.service.generate", return_value={**response(), "response": empty}) as model,
            patch("validation.service.validate") as check,
        ):
            process_run(str(edit.id))
        check.assert_not_called()
        self.assertEqual(model.call_count, 4)
        edit.refresh_from_db()
        self.chat.refresh_from_db()
        self.assertEqual(edit.status, "needs_attention")
        self.assertEqual(edit.error["details"][0]["code"], "no_changes")
        self.assertIsNone(edit.result_revision_id)
        self.assertIsNone(edit.candidate_revision_id)
        self.assertEqual(self.chat.current_revision_id, base.id)
        self.assertEqual(self.chat.revisions.count(), 1)
        self.assertNotIn("Добавлен второй уровень", edit.message)

    def test_empty_edit_uses_one_auto_correction_before_checking_new_version(self):
        from generation.providers.fake import fixture_response, generate

        initial = self.make_run()
        with patch("validation.service.validate", return_value=PASS):
            process_run(str(initial.id))
        self.chat.refresh_from_db()
        base = self.chat.current_revision
        edit = self.make_run(key="repair-empty-edit", prompt="Измени фон")
        empty = {
            **fixture_response(),
            "operation": "edit",
            "base_revision": str(base.id),
            "files": [],
            "patches": [],
            "checks": [],
            "message": "Готово",
        }
        corrected = generate(
            {"operation": "edit", "files": base.files, "checks": base.checks, "base_revision": base.id},
            on_event=lambda _: None,
            is_cancelled=lambda: False,
        )
        with (
            patch(
                "generation.service.generate",
                side_effect=[{**response(), "response": empty}, corrected],
            ) as model,
            patch("validation.service.validate", return_value=PASS) as check,
        ):
            process_run(str(edit.id))
        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args.args[0]["findings"][0]["code"], "no_changes")
        self.assertEqual(model.call_args.args[0]["operation"], "edit")
        check.assert_called_once()
        edit.refresh_from_db()
        self.assertEqual(edit.status, "succeeded", edit.error)
        self.assertNotEqual(edit.result_revision.artifact_hash, base.artifact_hash)
        self.assertEqual(self.chat.revisions.count(), 2)

    def test_explicit_unchanged_is_neutral_without_revision_validation_or_retry(self):
        from generation.providers.fake import fixture_response

        initial = self.make_run()
        with patch("validation.service.validate", return_value=PASS):
            process_run(str(initial.id))
        self.chat.refresh_from_db()
        base = self.chat.current_revision
        edit = self.make_run(key="explicit-unchanged", prompt="Добавь второй уровень")
        unchanged = {
            **fixture_response(),
            "status": "unchanged",
            "operation": "edit",
            "base_revision": str(base.id),
            "files": [],
            "patches": [],
            "checks": [],
            "message": "Второй уровень уже существует; уточните желаемые отличия.",
        }
        with (
            patch("generation.service.generate", return_value={**response(), "response": unchanged}) as model,
            patch("validation.service.validate") as check,
        ):
            process_run(str(edit.id))
        model.assert_called_once()
        check.assert_not_called()
        edit.refresh_from_db()
        self.chat.refresh_from_db()
        self.assertEqual(edit.status, "needs_attention", edit.error)
        self.assertEqual(edit.error["code"], "unchanged")
        self.assertIn(unchanged["message"], edit.message)
        self.assertEqual(edit.invocations.get().state, "settled")
        self.assertEqual(edit.metrics["check_seconds"], 0)
        self.assertEqual(edit.metrics["model_calls"], 1)
        self.assertIsNone(edit.result_revision_id)
        self.assertIsNone(edit.candidate_revision_id)
        self.assertEqual(self.chat.current_revision_id, base.id)
        self.assertEqual(self.chat.revisions.count(), 1)

    def test_fake_queue_batches_one_three_ten_are_isolated(self):
        from studio.tasks import dispatch_outbox

        for count in (1, 3, 10):
            runs = [
                self.make_run(
                    Chat.objects.create(owner=self.user), key=f"batch-{count}-{n}", prompt=f"Fixture {n}"
                )
                for n in range(count)
            ]
            queued = []
            with patch("studio.tasks.process_run.delay", side_effect=lambda run_id: queued.append(run_id)):
                dispatch_outbox()
            self.assertEqual(set(queued), {str(run.id) for run in runs})
            with (
                patch("generation.service.generate", return_value=response()) as model,
                patch("generation.artifacts.materialize", return_value=artifact()),
                patch("validation.service.validate", return_value=PASS),
            ):
                for run_id in queued:
                    process_run(run_id)
                for run_id in queued:
                    process_run(run_id)
            self.assertEqual(model.call_count, count)
            for run in runs:
                run.refresh_from_db()
                self.assertEqual(run.status, "succeeded", run.error)
                self.assertEqual(run.result_revision.chat_id, run.chat_id)
                self.assertEqual(run.invocations.count(), 1)

    def test_model_tariff_multipliers_do_not_leak_into_local_provider(self):
        from studio.services import tariff

        usage = {"input_tokens": 1000000, "cached_input_tokens": 900000, "output_tokens": 1000}
        self.assertEqual(usage_cost(usage, tariff("codex", "gpt-6.1-sol")), Decimal(".595000"))
        self.assertEqual(tariff("vllm", "gpt-6.1-sol"), {})

    def test_unknown_tariff_blocks_before_provider_call(self):
        run = self.make_run()
        run.provider = "vllm"
        run.model = "unpriced-local"
        run.save()
        with patch("generation.service.generate") as model:
            process_run(str(run.id))
        model.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.error["code"], "pricing_unavailable")
        self.assertEqual(run.invocations.count(), 0)

    def test_changed_validator_rechecks_saved_candidate_before_paid_repair(self):
        run = self.make_run()
        with (
            patch("validation.service.environment_identity", return_value="old-validator"),
            patch("generation.service.generate", return_value=response()),
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=FAIL),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "needs_attention")
        run.candidate_revision.reports.update(identity='old-validator-policy')
        follow = create_run(self.chat, {"idempotency_key": "new-validator"}, continued_from=run)
        with (
            patch("validation.service.environment_identity", return_value="fixed-validator"),
            patch("generation.service.generate") as model,
            patch("validation.service.validate", return_value=PASS) as check,
        ):
            process_run(str(follow.id))
        model.assert_not_called()
        check.assert_called_once()
        follow.refresh_from_db()
        self.assertEqual(follow.status, "succeeded", follow.error)

    def test_resumed_check_duration_attributed_to_executing_run(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()),
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch(
                "validation.service.validate",
                return_value={"status": "infrastructure_error", "findings": [], "elapsed_seconds": 2},
            ),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        follow = create_run(self.chat, {"idempotency_key": "timed-recheck"}, continued_from=run)
        with (
            patch("generation.service.generate") as model,
            patch("validation.service.validate", return_value={**PASS, "elapsed_seconds": 13}),
        ):
            process_run(str(follow.id))
        model.assert_not_called()
        follow.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(follow.metrics["check_seconds"], 13)
        self.assertEqual(follow.metrics["model_calls"], 0)
        self.assertEqual(run.metrics["check_seconds"], 2)

    def test_unverified_finishes_without_a_generic_autofix(self):
        run = self.make_run()
        uncertain = {
            "status": "unverified",
            "findings": [{"message": "Submitted action did not reach its target"}],
        }
        with (
            patch("generation.service.generate", return_value=response()) as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", side_effect=[uncertain, PASS]),
        ):
            process_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "needs_attention", run.error)
        self.assertEqual(model.call_count, 1)
        self.assertIsNotNone(run.finished_at)

    def test_infrastructure_failure_never_requests_model_repair(self):
        run = self.make_run()
        with (
            patch("generation.service.generate", return_value=response()) as model,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch(
                "validation.service.validate",
                return_value={
                    "status": "infrastructure_error",
                    "findings": [{"message": "No sandbox process"}],
                },
            ),
        ):
            process_run(str(run.id))
        model.assert_called_once()
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
