"""Real PostgreSQL races: constraints and budget admission, not mocked locks."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connections
from django.test import TransactionTestCase, override_settings

from studio.models import Budget, Chat, User
from studio.services import DomainError, create_run, reserve_invocation


@override_settings(GAMEFORGE_RUN_INLINE=False, GAMEFORGE_PROVIDER="codex", GAMEFORGE_MODEL="gpt-6-luna")
class RaceTests(TransactionTestCase):
    def setUp(self):
        publication = patch("studio.tasks.process_run.delay")
        publication.start()
        self.addCleanup(publication.stop)

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
        runs = [create_run(chat, {"prompt": "A mini game", "idempotency_key": "new"}) for chat in chats]
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
