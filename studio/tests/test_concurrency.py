"""Real PostgreSQL races: constraints and budget admission, not mocked locks."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connections
from django.test import TransactionTestCase, override_settings

from studio.models import Budget, Chat, Revision, User
from studio.services import DomainError, create_run, finish_run, rename_chat, reserve_invocation


@override_settings(GAMEFORGE_RUN_INLINE=False, GAMEFORGE_PROVIDER="codex", GAMEFORGE_MODEL="gpt-6-luna")
class RaceTests(TransactionTestCase):
    def setUp(self):
        publication = patch("studio.tasks.process_run.delay")
        publication.start()
        self.addCleanup(publication.stop)

    def test_manual_rename_wins_when_generation_finishes_at_the_same_time(self):
        user = User.objects.create_user(username="rename-owner")
        chat = Chat.objects.create(owner=user)
        run = create_run(chat, {"prompt": "Игра про звёзды", "idempotency_key": "new", "model_profile": ""})
        run.fence = uuid.uuid4()
        run.save(update_fields=["fence"])
        revision = Revision.objects.create(
            chat=chat,
            run=run,
            number=1,
            title="Название модели",
            files={},
            html="<canvas></canvas>",
            artifact_hash="race",
        )
        barrier = Barrier(2)

        def compete(action):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                if action == "rename":
                    rename_chat(chat, "Моё ручное название")
                else:
                    self.assertTrue(finish_run(run.id, run.fence, "succeeded", "Готово", revision=revision))
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(compete, ["rename", "finish"]))
        chat.refresh_from_db()
        self.assertEqual(chat.title, "Моё ручное название")
        self.assertTrue(chat.title_is_custom)
        self.assertEqual(chat.current_revision_id, revision.pk)

    def test_case_insensitive_registration_race(self):
        barrier = Barrier(2)

        def create(name):
            close_old_connections()
            try:
                barrier.wait()
                try:
                    User.objects.create_user(username=name, password="sample-password")
                    return "created"
                except IntegrityError:
                    return "duplicate"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, ["Creator", "cREATOR"]))
        self.assertCountEqual(results, ["created", "duplicate"])
        self.assertEqual(User.objects.count(), 1)

    def test_two_chats_cannot_double_spend_last_reservation(self):
        user = User.objects.create_user(username="owner")
        Budget.objects.create(pk=1, limit_usd=Decimal("0.314"))
        chats = [Chat.objects.create(owner=user) for _ in range(2)]
        # This race uses the explicitly configured Luna tariff, not the account's Pro default.
        runs = [create_run(chat, {"prompt": "A mini game", "idempotency_key": "new", "model_profile": ""}) for chat in chats]
        barrier = Barrier(2)

        def reserve(run):
            close_old_connections()
            try:
                barrier.wait()
                try:
                    reserve_invocation(run, {})
                    return "reserved"
                except DomainError as exc:
                    return exc.code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, runs))
        self.assertCountEqual(results, ["reserved", "budget_exhausted"])
