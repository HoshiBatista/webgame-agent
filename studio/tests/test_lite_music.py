import pytest

from generation.experience import RECIPE
from generation.helpers import catalog
from generation.music import MARKER
from studio.tasks import process_run
from studio.tests.test_relay import environment as relay_environment

environment = relay_environment


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('invalid_score', [False, True])
def test_music_uses_separate_durable_call_and_never_repeats_after_restart(environment, monkeypatch, invalid_score):
    from tests.test_music import music_response

    run, _, executor, calls = environment
    run.requirement_manifest[MARKER] = 1
    run.helper_catalog = catalog()
    run.save(update_fields=['requirement_manifest', 'helper_catalog'])
    if invalid_score:
        monkeypatch.setattr('tests.test_music.music_response', lambda req: {**music_response(req), 'instruments': []})
    process_run(str(run.id))
    executor.step()
    executor.step()
    process_run(str(run.id))
    run.refresh_from_db()
    first = run.candidate_revision
    inv = run.invocations.get(request__operation='music')
    assert inv.state == 'sent'
    assert inv.request['base_revision'] == str(first.id)
    assert inv.request['relay']['payload']['messages'][0]['content'].startswith('Compose an original')
    process_run(str(run.id))
    assert run.invocations.count() == 2
    executor.step()
    executor.step()
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == 'succeeded', run.error
    result = run.result_revision
    assert result.checks == first.checks
    assert all(result.files[p] == c for p, c in first.files.items() if p != 'index.html')
    assert (RECIPE in result.files) is not invalid_score
    assert (result.id == first.id) is invalid_score
    assert len(calls) == 2
    process_run(str(run.id))
    assert len(calls) == 2 and run.invocations.count() == 2


@pytest.mark.django_db(transaction=True)
def test_music_respects_explicit_call_limit(environment):
    run, _, executor, calls = environment
    run.requirement_manifest[MARKER] = 1
    run.helper_catalog = catalog()
    run.model_call_limit = 1
    run.save(update_fields=['requirement_manifest', 'helper_catalog', 'model_call_limit'])
    process_run(str(run.id))
    executor.step()
    executor.step()
    process_run(str(run.id))
    run.refresh_from_db()
    assert run.status == 'succeeded', run.error
    assert len(calls) == 1 and not run.invocations.filter(request__operation='music').exists()
