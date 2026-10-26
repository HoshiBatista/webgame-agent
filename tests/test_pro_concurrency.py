import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connections

from generation.providers.fake import fixture_response
from generation.providers.fake import generate as fake_generate
from studio.models import Budget, Chat, Run, User
from studio.services import DomainError, cancel_run, create_run, reserve_invocation
from studio.tasks import claim_run, process_run, reconcile_relay_cancellations
from tests import test_codex_api as fixtures

api = fixtures.api
run = fixtures.run


def another(run, *, planning=False):
    result = create_run(Chat.objects.create(owner=run.chat.owner), {
        'prompt': 'Сделай игру', 'idempotency_key': str(uuid.uuid4()), 'model_profile': 'pro',
        'model_call_limit': 3 if planning else 1,
    })
    result.planning_required = planning
    result.save(update_fields=['planning_required'])
    return result


@pytest.mark.django_db(transaction=True)
def test_two_games_have_independent_receipts_and_third_waits(run, api, settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 2
    second, third = another(run), another(run)
    process_run(str(run.id))
    process_run(str(second.id))
    process_run(str(third.id))
    assert len(api.jobs) == 2 and not third.invocations.exists()
    first_id, second_id = str(run.invocations.get().id), str(second.invocations.get().id)
    response = fixture_response()
    response['title'] = 'Вторая игра'
    api.finish(second_id, response)
    process_run(str(second.id))
    second.refresh_from_db()
    assert second.status == 'succeeded' and second.candidate_revision.title == 'Вторая игра'
    assert run.invocations.get().state == 'sent' and not run.candidate_revision
    process_run(str(third.id))
    assert len(api.jobs) == 3 and third.invocations.count() == 1
    api.finish(first_id, fixture_response())
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == 'succeeded'
    assert run.candidate_revision_id != second.candidate_revision_id
    assert run.candidate_revision.chat_id == run.chat_id
    assert sum(method == 'PUT' for method, _ in api.calls) == 3


@pytest.mark.django_db(transaction=True)
def test_pending_cancellation_keeps_slot_without_blocking_other_receipt(run, api, settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 2
    second, third = another(run), another(run)
    process_run(str(run.id))
    process_run(str(second.id))
    cancel_run(run)
    api.fail = 503
    reconcile_relay_cancellations()
    process_run(str(third.id))
    assert not third.invocations.exists()
    api.fail = None
    api.finish(str(second.invocations.get().id), fixture_response())
    process_run(str(second.id))
    second.refresh_from_db()
    assert second.status == 'succeeded'
    reconcile_relay_cancellations()
    assert run.invocations.get().state not in {'reserved', 'sent'}
    process_run(str(third.id))
    assert third.invocations.count() == 1


@pytest.mark.django_db(transaction=True)
def test_reduced_capacity_can_receive_both_admitted_jobs(run, api, settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 2
    second = another(run)
    for job in [run, second]:
        process_run(str(job.id))
        api.finish(str(job.invocations.get().id), fixture_response())
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 1
    for job in [run, second]:
        process_run(str(job.id))
        job.refresh_from_db()
        assert job.status == 'succeeded'
        assert job.invocations.count() == 1
    assert api.inferences == 2


@pytest.mark.django_db(transaction=True)
def test_retrieved_plan_waits_for_capacity_before_next_model_step(run, api, settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 2
    planned = another(run, planning=True)
    process_run(str(run.id))
    process_run(str(planned.id))
    inv = planned.invocations.get()
    response = fake_generate(inv.request, on_event=lambda _: None, is_cancelled=lambda: False)['response']
    api.finish(str(inv.id), response)
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 1
    process_run(str(planned.id))
    planned.refresh_from_db()
    assert planned.status == 'queued' and planned.game_plan == response['plan']
    assert planned.invocations.count() == 1 and planned.attempts == 1
    assert planned.error == {}
    api.finish(str(run.invocations.get().id), fixture_response())
    process_run(str(run.id))
    process_run(str(planned.id))
    assert planned.invocations.count() == 2
    assert planned.invocations.order_by('attempt').last().request['operation'] == 'create'


@pytest.mark.django_db(transaction=True)
def test_processing_and_remote_wait_are_counted_as_union(run, api, settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 2
    processing, third = another(run), another(run)
    process_run(str(run.id))  # One queued run with an admitted remote job.
    assert claim_run(processing.id)  # A different processing run, no invocation yet.
    assert claim_run(third.id) is False
    with pytest.raises(DomainError, match='свободное место') as error:
        reserve_invocation(third, {'operation': 'create'})
    assert error.value.code == 'provider_busy' and not third.invocations.exists()


@pytest.mark.django_db(transaction=True)
def test_processing_and_its_invocation_are_one_slot(run, api, settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 2
    process_run(str(run.id))
    assert claim_run(run.id)
    assert claim_run(another(run).id)


@pytest.mark.django_db(transaction=True)
def test_parallel_admission_is_atomic_and_does_not_raise_lite_or_cli_limit(settings):
    settings.GAMEFORGE_CODEX_API_CONCURRENCY = 2
    settings.GAMEFORGE_PROVIDER_CONCURRENCY = 1
    Budget.objects.get_or_create(pk=1)
    user = User.objects.create_user(username='parallel')
    jobs = [Run.objects.create(chat=Chat.objects.create(owner=user), provider='codex_api',
                               idempotency_key=str(i), prompt='test') for i in range(6)]
    barrier = Barrier(len(jobs))

    def attempt(job):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return bool(claim_run(job.id))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        assert sum(pool.map(attempt, jobs)) == 2
    assert Run.objects.filter(status='generating', provider='codex_api').count() == 2
    for provider in ['relay', 'codex']:
        first, second = [Run.objects.create(chat=Chat.objects.create(owner=user), provider=provider,
                                            idempotency_key=str(i), prompt='test') for i in range(2)]
        assert claim_run(first.id)
        assert claim_run(second.id) is False


@pytest.mark.django_db(transaction=True)
def test_same_chat_still_rejects_second_active_game(run):
    with pytest.raises(DomainError) as error:
        create_run(run.chat, {'prompt':'Ещё игра','idempotency_key':'two','model_profile':'pro'})
    assert error.value.code == 'chat_busy'
