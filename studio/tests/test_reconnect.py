"""A browser disconnect is unrelated to the lifetime of a persisted model job."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.db import connections
from django.test import Client, TransactionTestCase, override_settings

from studio.models import Chat, Outbox, Run, User
from studio.tasks import dispatch_outbox, process_run
from studio.tests.test_domain import PASS, artifact, response


@override_settings(GAMEFORGE_PROVIDER="fake", GAMEFORGE_MODEL="fixture", GAMEFORGE_LEASE_SECONDS=100)
class ReconnectTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="correct-password")
        self.other = User.objects.create_user(username="other", password="correct-password")
        self.chat = Chat.objects.create(owner=self.user)
        self.client.force_login(self.user)
        self.path = f"/api/chats/{self.chat.id}/runs/"
        self.payload = {"prompt": "Make a game", "idempotency_key": "same-browser-operation"}

    def test_disconnect_during_generation_and_new_session_retrieves_one_saved_result(self):
        started, release = Event(), Event()

        def model(*args, **kwargs):
            started.set()
            assert release.wait(10), "Test model was not released"
            assert not kwargs["is_cancelled"]()
            return response()

        def worker(ident):
            try:
                process_run(ident)
            finally:
                connections.close_all()

        with (
            patch("studio.tasks.process_run.delay") as delivery,
            patch("generation.service.generate", side_effect=model) as generate,
            patch("generation.artifacts.materialize", return_value=artifact()),
            patch("validation.service.validate", return_value=PASS),
        ):
            accepted = self.client.post(self.path, self.payload, content_type="application/json")
            self.assertEqual(accepted.status_code, 202)
            ident = accepted.json()["id"]
            delivery.assert_called_once_with(ident)
            generate.assert_not_called()
            self.assertTrue(Outbox.objects.filter(run_id=ident).exists())
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker, ident)
                try:
                    self.assertTrue(started.wait(5))
                    stream = self.client.get(f"/api/runs/{ident}/events/")
                    first = next(iter(stream.streaming_content)).decode()
                    cursor = first.split("id: ")[1].split("\n")[0]
                    stream.close()  # Browser stops receiving events mid-generation.
                    self.client.logout()
                    self.assertEqual(Run.objects.get(pk=ident).status, "generating")
                    self.assertFalse(Run.objects.get(pk=ident).cancel_requested)
                finally:
                    release.set()
                future.result(timeout=10)

            returning = Client()
            returning.force_login(self.user)
            saved = returning.get(f"/api/chats/{self.chat.id}/").json()
            self.assertIsNone(saved["active_run"])
            self.assertEqual(saved["runs"][0]["status"], "succeeded")
            self.assertEqual(saved["current_revision"]["id"], saved["runs"][0]["result_revision_id"])
            self.assertEqual([m["role"] for m in saved["messages"]], ["user", "assistant"])
            events = returning.get(f"/api/runs/{ident}/events/", HTTP_LAST_EVENT_ID=cursor)
            replay = b"".join(events.streaming_content).decode()
            self.assertIn('"kind": "succeeded"', replay)
            self.assertNotIn('"kind": "queued"', replay)
            # Losing the original 202 and retrying its key cannot create a second inference.
            retry = returning.post(self.path, self.payload, content_type="application/json")
            self.assertEqual(retry.json()["id"], ident)
            process_run(ident)  # Redelivery is harmless as well.
            generate.assert_called_once()
            self.assertEqual(Run.objects.count(), 1)

            for client in (Client(), self.client):
                if client is self.client:
                    client.force_login(self.other)
                for path in (
                    f"/api/chats/{self.chat.id}/", f"/api/runs/{ident}/",
                    f"/api/runs/{ident}/events/", f"/api/runs/{ident}/diagnostics/",
                    f"/api/revisions/{saved['current_revision']['id']}/source/",
                ):
                    self.assertIn(client.get(path).status_code, (403, 404))

    def test_lost_submission_ack_and_broker_failure_leave_deliverable_work(self):
        with patch("studio.tasks.process_run.delay", side_effect=ConnectionError("broker offline")):
            accepted = self.client.post(self.path, self.payload, content_type="application/json")
        self.assertEqual(accepted.status_code, 202)
        ident = accepted.json()["id"]
        self.assertIsNone(Outbox.objects.get(run_id=ident).dispatched_at)
        self.client.logout()  # No browser needs to remain connected to dispatch the job.
        with patch("studio.tasks.process_run.delay") as delivery:
            dispatch_outbox()
        delivery.assert_called_once_with(ident)
        self.assertEqual(Run.objects.get(pk=ident).status, "queued")
