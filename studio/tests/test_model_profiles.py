"""User choices, immutable runs and Codex access boundaries; no model calls."""
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.apps import apps
from django.db import connection
from django.test import Client, RequestFactory

from generation.service import estimate_reservation
from studio.model_profiles import can_use_pro
from studio.models import Chat, Invocation, Outbox, Preference, Revision, Run, User
from studio.services import create_run, preference_for, tariff
from studio.tasks import request_for


@pytest.fixture
def profiles(settings):
    settings.GAMEFORGE_PROVIDER = 'relay'
    settings.GAMEFORGE_MODEL = 'qwen38'
    settings.GAMEFORGE_LITE_PROVIDER = ''
    settings.GAMEFORGE_LITE_MODEL = ''
    settings.GAMEFORGE_PRO_PROVIDER = 'codex'
    settings.GAMEFORGE_PRO_ENABLED = True
    settings.GAMEFORGE_PRO_ACCESS = 'local'
    settings.GAMEFORGE_PRO_USER_IDS = frozenset()
    settings.GAMEFORGE_LOCAL_ONLY = True
    settings.GAMEFORGE_APP_ORIGIN = 'http://127.0.0.1:8000'
    settings.ALLOWED_HOSTS = ['testserver', 'public.test', '127.0.0.1']
    with (patch('studio.services.schedule'),
          patch('generation.providers.codex.available_models', return_value=[{'id': 'gpt-6-sol'}]),
          patch('generation.providers.codex.verify_cli_contract', return_value='verified')):
        yield


@pytest.fixture
def client_chat(db, profiles):
    user = User.objects.create_user(username='operator', is_staff=True)
    client = Client()
    client.force_login(user)
    return client, Chat.objects.create(owner=user)


def submit(client, chat, **fields):
    return client.post(f'/api/chats/{chat.id}/runs/', {
        'prompt': 'Сделай змейку', 'idempotency_key': 'first', **fields,
    }, content_type='application/json')


def test_preferences_choose_exact_sol_without_generation(client_chat):
    client, chat = client_chat
    caps = client.get('/api/session/').json()['capabilities']
    assert caps['default_model_profile'] == 'pro'
    assert client.get('/api/preferences/').json()['model_profile'] == 'pro'
    assert [(p['id'], p['model'], p['available']) for p in caps['model_profiles']] == [
        ('pro', 'gpt-6-sol', True), ('lite', 'qwen38', True)]
    saved = client.patch('/api/preferences/', {'model_profile': 'pro'}, content_type='application/json')
    assert saved.status_code == 200
    assert saved.json()['model_profile'] == 'pro'
    assert not Run.objects.exists() and not Invocation.objects.exists() and not Outbox.objects.exists()
    result = submit(client, chat)
    assert result.status_code == 202
    assert result.json()['provider'] == 'codex'
    assert result.json()['model'] == 'gpt-6-sol'
    assert result.json()['model_label'] == 'Pro'


def test_explicit_choice_overrides_default_and_freezes_run(client_chat, settings):
    client, chat = client_chat
    pref = preference_for(chat.owner)
    pref.model_profile = 'pro'
    pref.save()
    r = submit(client, chat, model_profile='lite', provider='codex')
    assert r.status_code == 202
    run = Run.objects.get(pk=r.json()['id'])
    assert (run.provider, run.model, run.model_profile) == ('relay', 'qwen38', 'lite')
    settings.GAMEFORGE_LITE_MODEL = 'changed-api-model'
    # Same logical operation must return its saved choice, never a second inference.
    replay = submit(client, chat, model_profile='lite')
    assert replay.status_code == 202
    assert replay.json()['id'] == str(run.id)
    assert replay.json()['model'] == 'qwen38'
    assert request_for(run, None, [])['provider'] == 'relay'
    assert request_for(run, None, [])['model'] == 'qwen38'
    assert submit(client, chat, model_profile='pro').status_code == 409
    assert Run.objects.count() == 1


def test_retry_without_profile_ignores_changed_preference(client_chat):
    client, chat = client_chat
    client.patch('/api/preferences/', {'model_profile': 'lite'}, content_type='application/json')
    first = submit(client, chat)
    client.patch('/api/preferences/', {'model_profile': 'pro'}, content_type='application/json')
    retry = submit(client, chat)
    assert retry.status_code == 202
    assert retry.json()['id'] == first.json()['id']
    assert retry.json()['provider'] == 'relay'


def test_continue_on_pro_preserves_candidate_and_old_run(client_chat):
    client, chat = client_chat
    first = submit(client, chat, model_profile='lite')
    old = Run.objects.get(pk=first.json()['id'])
    candidate = Revision.objects.create(chat=chat, number=1, files={}, html='', artifact_hash='hash')
    old.candidate_revision = candidate
    old.status = 'needs_attention'
    old.save()
    r = client.post(f'/api/runs/{old.id}/continue/', {'model_profile': 'pro', 'idempotency_key': 'repair'},
                    content_type='application/json')
    assert r.status_code == 202
    repair = Run.objects.get(pk=r.json()['id'])
    assert (repair.provider, repair.model, repair.operation) == ('codex', 'gpt-6-sol', 'repair')
    assert repair.candidate_revision == candidate and repair.continued_from == old
    old.refresh_from_db()
    assert (old.provider, old.model_profile, old.status) == ('relay', 'lite', 'needs_attention')


def test_local_account_can_use_pro_without_staff(client_chat):
    client, chat = client_chat
    chat.owner.is_staff = False
    chat.owner.save(update_fields=['is_staff'])
    session = client.get('/api/session/').json()
    assert session['capabilities']['model_profiles'][0]['available']
    assert session['preferences']['model_profile'] == 'pro'
    response = submit(client, chat)
    assert response.status_code == 202 and response.json()['model_profile'] == 'pro'
    assert not Invocation.objects.exists()


@pytest.mark.parametrize('boundary', ['remote', 'public_origin', 'disabled', 'shared'])
def test_pro_cannot_be_exposed_by_relay_default_or_continuation(client_chat, settings, boundary):
    client, chat = client_chat
    old = create_run(chat, {'prompt': 'Сделай игру', 'idempotency_key': 'old', 'model_profile': 'pro'})
    old.status = 'failed'
    old.save()
    extra = {}
    if boundary == 'remote':
        extra = {'REMOTE_ADDR': '203.0.113.7', 'HTTP_HOST': '127.0.0.1'}
    elif boundary == 'public_origin':
        settings.GAMEFORGE_APP_ORIGIN = 'https://public.test'
    elif boundary == 'disabled':
        settings.GAMEFORGE_PRO_ENABLED = False
    else:
        settings.GAMEFORGE_LOCAL_ONLY = False
    caps = client.get('/api/session/', **extra).json()['capabilities']
    assert not caps['model_profiles'][0]['available']
    for path, data in [
        (f'/api/chats/{chat.id}/runs/', {'prompt':'New', 'idempotency_key':'new', 'model_profile':'pro'}),
        (f'/api/runs/{old.id}/continue/', {'idempotency_key':'repair'}),
    ]:
        response = client.post(path, data, content_type='application/json', **extra)
        assert response.status_code in (403, 409)
    settings.GAMEFORGE_PROVIDER = 'codex'
    # Legacy requests cannot bypass the boundary with the global Codex default.
    legacy = client.post(f'/api/chats/{chat.id}/runs/', {
        'prompt': 'Legacy', 'idempotency_key': 'legacy', 'model_profile': '',
    }, content_type='application/json', **extra)
    assert legacy.status_code == 403
    assert Run.objects.count() == 1


def test_bad_profile_or_model_never_falls_back(client_chat):
    client, chat = client_chat
    for value in ['fastest', ['pro'], None]:
        assert submit(client, chat, model_profile=value).status_code == 400
    assert submit(client, chat, model_profile='pro', model='gpt-6.1-sol').status_code == 400
    with patch('generation.providers.codex.available_models', return_value=[]):
        assert submit(client, chat, model_profile='pro').status_code == 409
    assert not Run.objects.exists()


def configure_cloud(settings, owner):
    settings.GAMEFORGE_LOCAL_ONLY = False
    settings.GAMEFORGE_APP_ORIGIN = 'https://public.test'
    settings.GAMEFORGE_PRO_ACCESS = 'restricted'
    settings.GAMEFORGE_PRO_USER_IDS = frozenset({owner.pk})
    owner.is_staff = False
    owner.save()


@pytest.mark.parametrize('provider', ['codex', 'codex_api'])
def test_all_cloud_accounts_get_pro_including_accounts_created_later(client_chat, settings, provider):
    client, chat = client_chat
    configure_cloud(settings, chat.owner)
    settings.GAMEFORGE_PRO_ACCESS = 'authenticated'
    settings.GAMEFORGE_PRO_PROVIDER = provider
    # A leftover allowlist must not prevent later accounts from using Pro.
    extra = {'secure': True, 'HTTP_HOST': 'public.test', 'REMOTE_ADDR': '203.0.113.7'}
    with patch('generation.providers.codex_api.available_models', return_value=[{'id': 'gpt-6-sol'}]):
        for user in [chat.owner, User.objects.create_user(username='new-member')]:
            client.force_login(user)
            session = client.get('/api/session/', **extra).json()
            assert session['preferences']['model_profile'] == 'pro'
            assert session['capabilities']['default_model_profile'] == 'pro'
            assert session['capabilities']['model_profiles'][0]['available']
            assert not user.is_staff
            fresh_chat = client.post('/api/chats/', {}, content_type='application/json', **extra)
            assert fresh_chat.status_code == 201
            result = client.post(f"/api/chats/{fresh_chat.json()['id']}/runs/", {
                'prompt': 'Game', 'idempotency_key': 'new-default',
            }, content_type='application/json', **extra)
            assert result.status_code == 202
            assert (result.json()['provider'], result.json()['model_profile']) == (provider, 'pro')
        assert not Invocation.objects.exists()


def test_saved_lite_is_preserved_for_new_chats_and_notes_updates(client_chat):
    client, chat = client_chat
    response = client.patch('/api/preferences/', {'model_profile': 'lite'}, content_type='application/json')
    assert response.status_code == 200
    client.patch('/api/preferences/', {'notes': ['Спокойный темп']}, content_type='application/json')
    assert client.get('/api/session/').json()['preferences']['model_profile'] == 'lite'
    fresh_chat = Chat.objects.create(owner=chat.owner)
    result = submit(client, fresh_chat)
    assert result.status_code == 202 and result.json()['model_profile'] == 'lite'


def test_unset_preferences_migrate_to_pro_without_rewriting_saved_choices_or_runs(client_chat):
    _, chat = client_chat
    blank = Preference.objects.create(user=chat.owner, model_profile='')
    lite = Preference.objects.create(user=User.objects.create_user(username='lite-member'), model_profile='lite')
    pro = Preference.objects.create(user=User.objects.create_user(username='pro-member'), model_profile='pro')
    old = create_run(chat, {'prompt': 'Game', 'idempotency_key': 'old-lite', 'model_profile': 'lite'})
    migration = import_module('studio.migrations.0021_pro_default')
    migration.use_pro_for_unset_preferences(apps, SimpleNamespace(connection=connection))
    for preference, expected in [(blank, 'pro'), (lite, 'lite'), (pro, 'pro')]:
        preference.refresh_from_db()
        assert preference.model_profile == expected
    old.refresh_from_db()
    assert (old.model_profile, old.provider, old.model) == ('lite', 'relay', 'qwen38')


def test_new_default_never_silently_falls_back_when_pro_is_unavailable(client_chat):
    client, chat = client_chat
    with patch('generation.providers.codex.available_models', return_value=[]):
        session = client.get('/api/session/').json()
        assert session['preferences']['model_profile'] == session['capabilities']['default_model_profile'] == 'pro'
        assert not session['capabilities']['model_profiles'][0]['available']
        assert submit(client, chat).status_code == 409
    assert not Run.objects.exists() and not Invocation.objects.exists()


@pytest.mark.parametrize('boundary', ['guest', 'inactive', 'http', 'wrong_host'])
def test_all_account_access_still_requires_active_login_and_matching_https(client_chat, settings, boundary):
    _, chat = client_chat
    configure_cloud(settings, chat.owner)
    settings.GAMEFORGE_PRO_ACCESS = 'authenticated'
    request = RequestFactory().get('/api/session/', secure=boundary != 'http',
                                   HTTP_HOST='127.0.0.1' if boundary == 'wrong_host' else 'public.test')
    request.user = chat.owner
    if boundary == 'guest':
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
    if boundary == 'inactive':
        request.user.is_active = False
    assert not can_use_pro(request)


def test_explicit_cloud_member_can_use_pro_without_staff(client_chat, settings):
    client, chat = client_chat
    configure_cloud(settings, chat.owner)
    extra = {'secure': True, 'HTTP_HOST': 'public.test', 'REMOTE_ADDR': '203.0.113.7'}
    options = client.get('/api/session/', **extra).json()['capabilities']['model_profiles']
    assert all(p['available'] for p in options)
    result = client.post(f'/api/chats/{chat.pk}/runs/', {
        'prompt': 'Game', 'idempotency_key': 'cloud', 'model_profile': 'pro',
    }, content_type='application/json', **extra)
    assert result.status_code == 202
    assert result.json()['model'] == 'gpt-6-sol'
    assert result.json()['provider'] == 'codex'


@pytest.mark.parametrize('cloud', [False, 'restricted', 'authenticated'])
def test_guest_session_remains_available_without_pro(client_chat, settings, cloud):
    client, chat = client_chat
    extra = {}
    if cloud:
        configure_cloud(settings, chat.owner)
        settings.GAMEFORGE_PRO_ACCESS = cloud
        extra = {'secure': True, 'HTTP_HOST': 'public.test'}
    client.logout()
    result = client.get('/api/session/', **extra)
    assert result.status_code == 200
    assert result.json()['user'] is None
    assert not result.json()['capabilities']['model_profiles'][0]['available']
    assert client.post(f'/api/chats/{chat.pk}/runs/', {
        'prompt': 'Game', 'idempotency_key': 'guest', 'model_profile': 'pro',
    }, content_type='application/json', **extra).status_code == 403
    assert not Run.objects.exists()


@pytest.mark.parametrize('access,boundary', [
    (access, boundary)
    for access in ['restricted', 'authenticated']
    for boundary in ['http', 'wrong_host', 'local_mode', 'disabled']
] + [('restricted', 'other_user')])
def test_cloud_pro_rejects_bypass_including_inherited_runs(client_chat, settings, access, boundary):
    client, chat = client_chat
    configure_cloud(settings, chat.owner)
    settings.GAMEFORGE_PRO_ACCESS = access
    old = create_run(chat, {'prompt': 'Game', 'idempotency_key': 'old', 'model_profile': 'pro'})
    old.status = 'failed'
    old.save()
    extra = {'secure': True, 'HTTP_HOST': 'public.test'}
    if boundary == 'other_user':
        settings.GAMEFORGE_PRO_USER_IDS = frozenset({chat.owner.pk + 1})
        chat.owner.is_staff = True  # Staff is not a bypass of the cloud allowlist.
        chat.owner.save()
    elif boundary == 'http':
        extra['secure'] = False
    elif boundary == 'wrong_host':
        extra['HTTP_HOST'] = '127.0.0.1'
    elif boundary == 'local_mode':
        settings.GAMEFORGE_PRO_ACCESS = 'local'
    else:
        settings.GAMEFORGE_PRO_ENABLED = False
    options = client.get('/api/session/', **extra).json()['capabilities']['model_profiles']
    assert not options[0]['available'] and options[1]['available']
    for path, data in [
        (f'/api/chats/{chat.pk}/runs/', {'prompt': 'New', 'idempotency_key': 'new', 'model_profile': 'pro'}),
        (f'/api/runs/{old.pk}/continue/', {'idempotency_key': 'repair'}),
        (f'/api/chats/{chat.pk}/runs/', {'prompt': 'Game', 'idempotency_key': 'old', 'model_profile': 'pro'}),
    ]:
        assert client.post(path, data, content_type='application/json', **extra).status_code in (403, 409)
    settings.GAMEFORGE_PROVIDER = 'codex'
    response = client.post(f'/api/chats/{chat.pk}/runs/', {
        'prompt': 'Legacy', 'idempotency_key': 'legacy', 'model_profile': '',
    }, content_type='application/json', **extra)
    assert response.status_code == 403
    assert Run.objects.count() == 1


def test_fixture_mode_does_not_accidentally_select_a_real_model(client_chat, settings):
    client, chat = client_chat
    preference = preference_for(chat.owner)
    preference.model_profile = 'pro'
    preference.save()
    settings.GAMEFORGE_PROVIDER = 'fake'
    settings.GAMEFORGE_MODEL = 'fixture'
    assert client.get('/api/session/').json()['capabilities']['model_profiles'] == []
    result = submit(client, chat, model='fixture')
    assert result.status_code == 202 and result.json()['provider'] == 'fake'


def test_sol_has_accountable_tariff_and_reservation():
    price = tariff('codex', 'gpt-6-sol')
    assert price['cached'] == .20
    assert estimate_reservation({'provider':'codex', 'model':'gpt-6-sol'}, price) == Decimal('6.28')


def test_switching_provider_keeps_unknown_cost_confirmation(client_chat):
    client, chat = client_chat
    old = create_run(chat, {'prompt': 'Game', 'idempotency_key': 'old', 'model_profile': 'lite'})
    old.status = 'unknown'
    old.save()
    inv = Invocation.objects.create(run=old, attempt=1, state='unknown', request={}, reservation_usd=2)
    path = f'/api/runs/{old.id}/continue/'
    data = {'idempotency_key': 'retry', 'model_profile': 'pro'}
    assert client.post(path, data, content_type='application/json').status_code == 409
    allowed = client.post(path, {**data, 'accept_unknown_cost': True}, content_type='application/json')
    assert allowed.status_code == 202
    assert allowed.json()['provider'] == 'codex'
    inv.refresh_from_db()
    assert inv.state == 'unknown' and inv.cost_usd is None and inv.reservation_usd == 2
