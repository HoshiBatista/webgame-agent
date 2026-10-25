import importlib
import uuid

from django.apps import apps
from django.test import Client, TestCase, override_settings

from generation.providers.fake import fixture_response
from studio.acceptance import assess
from studio.models import Chat, CheckReport, Invocation, Publication, Revision, User
from studio.services import cancel_run, create_run, finish_run
from studio.tasks import check_identity
from studio.titles import title_from_prompt


@override_settings(GAMEFORGE_RUN_INLINE=False, GAMEFORGE_PROVIDER="fake", GAMEFORGE_MODEL="fixture")
class ChatTitleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="title-owner")
        self.other = User.objects.create_user(username="other-owner")
        self.chat = Chat.objects.create(owner=self.user)
        self.client.force_login(self.user)

    def run_and_revision(self):
        run = create_run(self.chat, {"prompt": "Сделай игру про звёзды", "idempotency_key": "first"})
        run.fence = uuid.uuid4()
        run.save(update_fields=["fence"])
        revision = Revision.objects.create(
            chat=self.chat,
            run=run,
            number=1,
            title="Звёздный сад",
            files={},
            html="<canvas></canvas>",
            artifact_hash="fixture",
            file_hashes={},
        )
        return run, revision

    def test_new_chat_has_default_name_and_explicit_creation_title_is_custom(self):
        self.assertEqual(self.chat.title, "Новая игра")
        for title in (None, "", "   "):
            data = {} if title is None else {"title": title}
            response = self.client.post("/api/chats/", data, content_type="application/json")
            self.assertEqual(response.status_code, 201)
            saved = Chat.objects.get(pk=response.json()["id"])
            self.assertEqual(saved.title, "Новая игра")
            self.assertFalse(saved.title_is_custom)
        response = self.client.post("/api/chats/", {"title": "Новая игра"}, content_type="application/json")
        custom = Chat.objects.get(pk=response.json()["id"])
        self.assertTrue(custom.title_is_custom)
        create_run(custom, {"prompt": "Другой запрос", "idempotency_key": "new"})
        custom.refresh_from_db()
        self.assertEqual(custom.title, "Новая игра")

    def test_first_prompt_sets_short_title_without_model_calls_and_generation_refines_it(self):
        run, revision = self.run_and_revision()
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.title, "Сделай игру про звёзды")
        self.assertFalse(Invocation.objects.exists())
        duplicate = create_run(self.chat, {"prompt": run.prompt, "idempotency_key": "first"})
        self.assertEqual(duplicate.pk, run.pk)
        self.assertTrue(finish_run(run.id, run.fence, "succeeded", "Готово", revision=revision))
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.title, revision.title)
        self.assertFalse(self.chat.title_is_custom)

    def test_only_first_prompt_names_an_unfinished_chat(self):
        first = create_run(self.chat, {"prompt": "  Игра\nпро  звёзды  ", "idempotency_key": "first"})
        cancel_run(first)
        create_run(self.chat, {"prompt": "Продолжи", "idempotency_key": "second"})
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.title, "Игра про звёзды")

    def test_manual_name_survives_late_generation_and_does_not_rename_publication_or_game(self):
        run, revision = self.run_and_revision()
        publication = Publication.objects.create(
            owner=self.user, source_chat=self.chat, revision=revision, title="Публичное название"
        )
        response = self.client.patch(
            f"/api/chats/{self.chat.id}/", {"title": "  Моя  любимая игра "}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Моя любимая игра")
        finish_run(run.id, run.fence, "succeeded", "Готово", revision=revision)
        self.chat.refresh_from_db()
        self.assertTrue(self.chat.title_is_custom)
        self.assertEqual(self.chat.title, "Моя любимая игра")
        self.assertEqual(self.client.get("/api/chats/").json()["results"][0]["title"], self.chat.title)
        publication.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(publication.title, "Публичное название")
        self.assertEqual(revision.title, "Звёздный сад")
        self.assertFalse(Invocation.objects.exists())

    def test_same_name_still_counts_as_manual_and_is_not_overwritten(self):
        run, revision = self.run_and_revision()
        self.chat.refresh_from_db()
        self.client.patch(
            f"/api/chats/{self.chat.id}/", {"title": self.chat.title}, content_type="application/json"
        )
        finish_run(run.id, run.fence, "succeeded", "Готово", revision=revision)
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.title, run.prompt)
        self.assertTrue(self.chat.title_is_custom)

    def test_invalid_title_and_foreign_or_deleted_chat_cannot_be_changed(self):
        for title in (None, "", " \n ", 7, [], {}, "x" * 161):
            with self.subTest(title=title):
                response = self.client.patch(
                    f"/api/chats/{self.chat.id}/", {"title": title}, content_type="application/json"
                )
                self.assertEqual(response.status_code, 400)
        other = Chat.objects.create(owner=self.other)
        self.assertEqual(
            self.client.patch(
                f"/api/chats/{other.id}/", {"title": "Чужое"}, content_type="application/json"
            ).status_code,
            404,
        )
        self.client.delete(f"/api/chats/{self.chat.id}/")
        self.assertEqual(
            self.client.patch(
                f"/api/chats/{self.chat.id}/", {"title": "Удалённое"}, content_type="application/json"
            ).status_code,
            404,
        )
        self.chat.refresh_from_db()
        self.assertEqual(self.chat.title, "Новая игра")
        self.assertFalse(self.chat.title_is_custom)

    def test_manual_confirmation_uses_game_name_only_when_chat_name_is_automatic(self):
        for custom in (False, True):
            with self.subTest(custom=custom):
                self.chat = Chat.objects.create(owner=self.user)
                run, revision = self.run_and_revision()
                if custom:
                    self.client.patch(
                        f"/api/chats/{self.chat.id}/",
                        {"title": "Ручное имя"},
                        content_type="application/json",
                    )
                run.status = "unverified"
                run.candidate_revision = revision
                run.save(update_fields=["status", "candidate_revision"])
                checks = fixture_response()["checks"]
                revision.checks = checks
                revision.save(update_fields=["checks"])
                result = {
                    "status": "unverified",
                    "findings": [{"code": "check_unverified", "check_id": checks[-1]["id"]}],
                    "gates": {"syntax": True, "runtime": True, "surface": True},
                    "stages": [{"stage": "syntax", "status": "passed"}],
                    "facts": [
                        {
                            **{k: c[k] for k in ("id", "category", "requirement", "viewport")},
                            "surface": {
                                "canvases": [{"visible": True, "width": 300, "height": 300}],
                                "overflow": False,
                            },
                        }
                        for c in checks
                    ],
                }
                report = CheckReport.objects.create(
                    revision=revision,
                    validation_run=run,
                    status="unverified",
                    checks=checks,
                    identity=check_identity(revision),
                    assessment=assess(result, checks, []),
                )
                response = self.client.post(
                    f"/api/runs/{run.id}/confirm/",
                    {"confirmed": True, "artifact_hash": revision.artifact_hash, "report_id": report.pk},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)
                self.chat.refresh_from_db()
                self.assertEqual(self.chat.title, "Ручное имя" if custom else revision.title)

    def test_migration_preserves_existing_names_and_fills_empty_ones(self):
        empty = Chat.objects.create(owner=self.user, title="")
        existing = Chat.objects.create(owner=self.user, title="Моё прежнее название")
        migration = importlib.import_module("studio.migrations.0011_chat_titles")
        migration.preserve_existing_titles(apps, None)
        empty.refresh_from_db()
        existing.refresh_from_db()
        self.assertEqual(empty.title, "Новая игра")
        self.assertFalse(empty.title_is_custom)
        self.assertTrue(existing.title_is_custom)
        self.assertEqual(existing.title, "Моё прежнее название")

    def test_rename_requires_authentication_and_csrf_and_cannot_disable_custom_flag(self):
        client = Client(enforce_csrf_checks=True)
        path = f"/api/chats/{self.chat.id}/"
        payload = {"title": "Новое имя", "title_is_custom": False}
        self.assertEqual(client.patch(path, payload, content_type="application/json").status_code, 403)
        client.force_login(self.user)
        self.assertEqual(client.patch(path, payload, content_type="application/json").status_code, 403)
        session = client.get("/api/session/").json()
        response = client.patch(
            path, payload, content_type="application/json", HTTP_X_CSRFTOKEN=session["csrfToken"]
        )
        self.assertEqual(response.status_code, 200)
        self.chat.refresh_from_db()
        self.assertTrue(self.chat.title_is_custom)


class PromptTitleTests(TestCase):
    def test_short_titles_preserve_words_and_normalize_whitespace(self):
        self.assertEqual(title_from_prompt("  Лисёнок\nсобирает   звёзды  "), "Лисёнок собирает звёзды")
        title = title_from_prompt("Лисёнок собирает звёзды " * 8)
        self.assertLessEqual(len(title), 60)
        self.assertTrue(title.endswith("…"))
        self.assertLessEqual(len(title_from_prompt("я" * 120)), 60)
