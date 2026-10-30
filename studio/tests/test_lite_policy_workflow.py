from unittest.mock import patch

import pytest

from generation import lite
from generation.providers.fake import generate as fake_generate
from studio.models import Chat, Invocation, User
from studio.services import create_run
from studio.tasks import process_run, request_for


@pytest.fixture
def run(settings):
    settings.GAMEFORGE_PROVIDER = 'fake'
    settings.GAMEFORGE_MODEL = 'fixture'
    with (patch('studio.services.schedule'), patch('studio.tasks.dispatch_run'),
          patch('studio.tasks.dispatch_outbox')):
        chat = Chat.objects.create(owner=User.objects.create_user(username='lite-policy'))
        current = create_run(chat, {'prompt': 'Собери три звезды', 'idempotency_key': 'lite-policy'})
        current.provider, current.model = 'relay', 'qwen38'
        current.planning_required = True
        current.model_call_limit = 1
        current.save()
        yield current


@pytest.mark.django_db
@pytest.mark.parametrize('provider,strategy,profile,expected', [
    ('relay', 'lite', 'full', True), ('vllm', 'lite', 'full', True),
    ('codex_api', 'pro', 'full', False), ('codex', 'pro', 'full', False),
    ('relay', 'lite', 'compact', False), ('fake', 'lite', 'full', False),
])
def test_new_request_marker_is_limited_to_remote_full_lite(run, provider, strategy, profile, expected):
    run.provider, run.generation_strategy, run.generation_profile = provider, strategy, profile
    request = request_for(run, None, [])
    assert ('lite_policy' in request) is expected
    if expected:
        assert request['lite_policy'] == lite.VERSION


@pytest.mark.django_db(transaction=True)
def test_returned_legacy_plan_is_saved_without_another_call_and_receipt_is_preserved(run):
    request = request_for(run, None, [])
    request.pop('lite_policy', None)
    response = fake_generate(request, on_event=lambda _: None, is_cancelled=lambda: False)['response']
    Invocation.objects.create(run=run, attempt=1, state='returned', request=request,
                              response=response, raw_response=response)
    run.attempts = 1
    run.save(update_fields=['attempts'])
    with patch('generation.service.generate') as model:
        process_run(str(run.id))
    model.assert_not_called()
    run.refresh_from_db()
    assert run.game_plan == response['plan']
    assert isinstance(run.game_plan['requirements'], list)
    assert run.requirement_manifest['requirements'] == run.game_plan['requirements']
    assert run.invocations.get().response == response
    assert run.invocations.get().state == 'settled'
    assert run.error['code'] == 'plan_without_game'
    assert run.attempts == 1 and not run.chat.revisions.exists()


@pytest.mark.django_db
@pytest.mark.parametrize('provider,profile,expected_plan', [
    ('relay', 'full', False), ('vllm', 'full', False),
    ('relay', 'compact', True), ('codex', 'full', True), ('codex_api', 'full', True),
])
def test_new_full_lite_restores_direct_creation_and_four_call_limit(settings, provider, profile, expected_plan):
    settings.GAMEFORGE_PROVIDER = provider
    settings.GAMEFORGE_MODEL = 'gpt-6-sol' if provider.startswith('codex') else 'qwen38'
    settings.GAMEFORGE_LITE_PROVIDER = provider
    settings.GAMEFORGE_LITE_MODEL = 'qwen38'
    settings.GAMEFORGE_PRO_PROVIDER = provider
    settings.GAMEFORGE_MAX_REPAIR_ATTEMPTS = 3
    with (patch('studio.services.schedule'), patch('studio.services.unavailable_reason', return_value=''),
          patch('studio.model_profiles.unavailable_reason', return_value='')):
        chat = Chat.objects.create(owner=User.objects.create_user(username='direct-lite'))
        run = create_run(chat, {'prompt': 'замути змейку для бабушки', 'idempotency_key': 'direct',
                               'generation_profile': profile,
                               'model_profile': 'pro' if provider.startswith('codex') else 'lite'})
    assert run.planning_required is expected_plan
    assert run.max_model_calls == (5 if expected_plan else 4)
    assert request_for(run, None, [])['operation'] == ('plan' if expected_plan else 'create')
    from generation.experience import PATH
    from generation.schema import response_schema

    assert (PATH in run.helper_catalog) is expected_plan
    if not expected_plan:
        assert 'assets' not in response_schema(request_for(run, None, []))['properties']
        assert run.requirement_manifest['require_keyboard'] is True
    else:
        assert 'require_keyboard' not in run.requirement_manifest
    assert not run.invocations.exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('with_assets', [False, True])
def test_lite_edit_preserves_existing_media_choice(run, settings, with_assets):
    from generation.artifacts import materialize
    from generation.experience import PATH
    from generation.providers.fake import fixture_response
    from studio.tasks import store_candidate

    source = store_candidate(run, materialize(fixture_response(with_assets=with_assets), operation='create'), None)
    run.status = 'needs_attention'
    run.save(update_fields=['status'])
    settings.GAMEFORGE_LITE_PROVIDER = 'relay'
    settings.GAMEFORGE_LITE_MODEL = 'qwen38'
    with (patch('studio.services.unavailable_reason', return_value=''),
          patch('studio.model_profiles.unavailable_reason', return_value='')):
        edit = create_run(run.chat, {'prompt': 'Сделай фон светлее', 'idempotency_key': 'edit-preserve-media',
                                    'model_profile': 'lite', 'source_revision_id': str(source.id),
                                    'source_artifact_hash': source.artifact_hash})
    assert (PATH in edit.helper_catalog) is with_assets
    assert edit.source_revision_id == source.id
    source.refresh_from_db()
    assert ('game-assets.json' in source.files) is with_assets
