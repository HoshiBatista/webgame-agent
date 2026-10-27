from django.test import Client, TestCase, override_settings

from studio.models import Chat, Feedback, Invocation, Preference, PromptTemplate, Run, User
from studio.services import create_run


@override_settings(GAMEFORGE_RUN_INLINE=False, GAMEFORGE_PROVIDER="fake", GAMEFORGE_MODEL="fixture")
class PersonalContentTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="template-owner")
        self.other = User.objects.create_user(username="template-other")
        self.client.force_login(self.owner)

    def patch_preferences(self, data):
        return self.client.patch('/api/preferences/', data, content_type='application/json')

    def test_notes_allow_free_text_many_lines_and_exact_unicode_limit(self):
        for notes in (["я" * 3000], ["🪴" * 3000], ["Пожелание"] * 100,
                      ["Первый абзац", "", ("Второй абзац длиннее прежнего лимита " * 20).strip()]):
            result = self.patch_preferences({'notes': notes})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['notes'], notes)
        for notes in (["я" * 3001], ["🪴" * 3001], ["я" * 1500, "я" * 1500],
                      "обычный текст вместо массива", [123], None):
            before = Preference.objects.get(user=self.owner).notes
            self.assertEqual(self.patch_preferences({'notes': notes}).status_code, 400)
            self.assertEqual(Preference.objects.get(user=self.owner).notes, before)
        self.assertEqual(self.patch_preferences({'notes': []}).json()['notes'], [])

    def test_wishes_are_preserved_in_next_generation_snapshot(self):
        notes = ["Много места для игры. " * 100, "", "Текст после пустой строки."]
        self.patch_preferences({'notes': notes})
        chat = Chat.objects.create(owner=self.owner)
        run = create_run(chat, {'prompt': 'Игра про звёзды', 'idempotency_key': 'wishes'})
        self.assertEqual(run.preferences_snapshot, notes)
        self.assertFalse(Invocation.objects.exists())

    def test_feedback_capacity_keeps_existing_text_and_reports_unadded_wishes(self):
        text = "а" * 2980
        self.patch_preferences({'notes': [text]})
        chat = Chat.objects.create(owner=self.owner)
        response = self.client.post(f'/api/chats/{chat.id}/feedback/',
            {'rating': 3, 'reasons': ['Крупный текст', 'Длинное пожелание, которое уже не помещается']},
            content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['preferences_full'])
        self.assertEqual(response.json()['preferences']['notes'], [text, 'Крупный текст'])
        self.assertEqual(len(Feedback.objects.get().reasons), 2)
        self.assertFalse(Invocation.objects.exists())
        self.patch_preferences({'notes': [str(i) for i in range(20)]})
        response = self.client.post(f'/api/chats/{chat.id}/feedback/',
            {'rating': 3, 'reasons': ['Новая идея', 'Новая идея']}, content_type='application/json')
        self.assertEqual(len(response.json()['preferences']['notes']), 21)
        self.assertFalse(response.json()['preferences_full'])

    def test_preferences_return_only_current_account_settings(self):
        expected = {"theme", "notes", "model_profile"}
        self.assertEqual(set(self.client.get('/api/preferences/').json()), expected)
        response = self.patch_preferences({'theme': 'dark', 'notes': ['Крупный текст']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), expected)
        self.assertEqual(response.json()['notes'], ['Крупный текст'])
        session_preferences = self.client.get('/api/session/').json()['preferences']
        self.assertEqual(set(session_preferences), expected)
        self.assertEqual(session_preferences['theme'], 'dark')

    def test_private_template_lifecycle_and_no_generation(self):
        payload = {'title': 'Карточки памяти', 'description': 'Сделай игру на память.\n\nКрупные карточки.'}
        created = self.client.post('/api/templates/', payload, content_type='application/json')
        self.assertEqual(created.status_code, 201)
        url = f"/api/templates/{created.json()['id']}/"
        self.assertEqual(self.client.get(url).json()['description'], payload['description'])
        self.assertEqual(len(self.client.get('/api/templates/?q=памяти').json()['results']), 1)
        self.assertEqual(self.client.get('/api/templates/?q=звёзды').json()['results'], [])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/api/templates/').json()['results'], [])
        for method in ('get', 'patch', 'delete'):
            self.assertEqual(getattr(self.client, method)(url, {}, content_type='application/json').status_code, 404)
        self.assertEqual(Client().get('/api/templates/').status_code, 403)
        self.assertEqual(Client().post('/api/templates/', payload, content_type='application/json').status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post('/api/templates/', payload, content_type='application/json').status_code, 403)
        self.client.force_login(self.owner)
        updated = self.client.patch(url, {'title': 'Новая игра', 'description': 'Другое описание'}, content_type='application/json')
        self.assertEqual(updated.json()['title'], 'Новая игра')
        self.assertEqual(updated.json()['description'], 'Другое описание')
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertFalse(PromptTemplate.objects.exists())
        self.assertFalse(Run.objects.exists())
        self.assertFalse(Invocation.objects.exists())

    def test_template_boundaries_and_failed_patch_are_atomic(self):
        self.assertEqual(self.client.post('/api/templates/', [], content_type='application/json').status_code, 400)
        payload = {'title': '🪴' * 50, 'description': '🌙' * 3000}
        created = self.client.post('/api/templates/', payload, content_type='application/json')
        self.assertEqual(created.status_code, 201)
        url = f"/api/templates/{created.json()['id']}/"
        self.assertEqual(self.client.patch(url, [], content_type='application/json').status_code, 400)
        for patch in ({'title': 'x' * 51}, {'description': 'x' * 3001}, {'title': '  '},
                      {'description': ''}, {'title': None}, {'description': []},
                      {'title': 'Valid title', 'description': 'x' * 3001}):
            self.assertEqual(self.client.patch(url, patch, content_type='application/json').status_code, 400)
            saved = self.client.get(url).json()
            self.assertEqual({k: saved[k] for k in payload}, payload)
