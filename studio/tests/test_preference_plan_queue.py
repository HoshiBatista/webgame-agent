from unittest.mock import patch

import pytest

from studio.models import Chat, Run, User
from studio.services import create_run, preference_for
from studio.tasks import claim_run, request_for
from tests.test_plan_preferences import WISH


@pytest.mark.django_db
def test_planning_keeps_preferences_saved_at_start_after_account_edit(settings):
    settings.GAMEFORGE_PROVIDER = 'fake'
    settings.GAMEFORGE_MODEL = 'fixture'
    owner = User.objects.create_user(username='source-check')
    preference = preference_for(owner)
    preference.notes = [WISH]
    preference.save()
    chat = Chat.objects.create(owner=owner)
    with patch('studio.services.schedule'):
        run = create_run(chat, {'prompt': 'Сделай только один уровень.', 'idempotency_key': 'snapshot'})
    run.planning_required = True
    run.save(update_fields=['planning_required'])
    preference.notes = ['Новое пожелание']
    preference.save()
    request = request_for(run, None, [])
    assert request['operation'] == 'plan' and request['plan_provenance'] == 1
    assert request['preferences'] == [WISH]
    assert request['game_request'] == 'Сделай только один уровень.'
    assert 'Новое пожелание' not in request['preferences']


@pytest.mark.django_db
def test_capacity_wait_is_explained_once_and_clears_on_admission(settings):
    settings.GAMEFORGE_PROVIDER = 'fake'
    settings.GAMEFORGE_MODEL = 'fixture'
    settings.GAMEFORGE_PROVIDER_CONCURRENCY = 1
    owner = User.objects.create_user(username='queue-check')
    with patch('studio.services.schedule'):
        first = create_run(Chat.objects.create(owner=owner), {'prompt': 'Игра', 'idempotency_key': 'busy'})
        waiting = create_run(Chat.objects.create(owner=owner), {'prompt': 'Игра', 'idempotency_key': 'waiting'})
    Run.objects.filter(pk=first.pk).update(status='generating')
    assert claim_run(waiting.pk) is False
    assert claim_run(waiting.pk) is False
    waiting.refresh_from_db()
    assert waiting.stage == 'waiting_capacity' and waiting.status == 'queued'
    assert not waiting.invocations.exists()
    assert waiting.events.filter(kind='waiting_capacity').count() == 1
    Run.objects.filter(pk=first.pk).update(status='succeeded')
    admitted = claim_run(waiting.pk)
    assert admitted.status == admitted.stage == 'generating'
    assert 'заняты' not in admitted.message
