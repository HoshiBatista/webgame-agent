"""Race the actual file-backed SQLite database, not its shared-memory test variant."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


SCRIPT = r"""
import django
django.setup()
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from django.core.management import call_command
from django.db import close_old_connections, connections
from django.db.models.query import QuerySet
from django.utils import timezone
from prompt2play.adapters.django.forge.authentication import secret_hash
from prompt2play.adapters.django.forge.errors import Conflict
from prompt2play.adapters.django.forge.models import Job, Project, Runner, Version, empty_usage
from prompt2play.adapters.django.forge import services
from prompt2play.adapters.django.forge.models import User
from prompt2play.adapters.django.forge.tests.evidence_fixtures import bound_report
from prompt2play.adapters.django.forge.views import RunnerRevokeView
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory, force_authenticate

call_command('migrate', verbosity=0, interactive=False)
project = Project.objects.create(title='Concurrent', prompt='Race')
job = Job.objects.create(project=project, kind='generate', prompt='Race', provider='codex')
runners = [Runner.objects.create(name=str(i), token_hash=secret_hash('token' + str(i))) for i in range(2)]
barrier = Barrier(2, timeout=10)
original_update = QuerySet.update
def simultaneous_update(query, **values):
    if query.model is Job and values.get('status') == 'running':
        barrier.wait()
    return original_update(query, **values)
def claim(runner):
    close_old_connections()
    try:
        return services.claim_job(runner, {'providers': ['codex']})
    finally:
        connections.close_all()
with patch.object(QuerySet, 'update', simultaneous_update), ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(claim, runners))
winners = [(index, result) for index, result in enumerate(results) if result[0] is not None]
assert len(winners) == 1, results
winner_index, (claimed, lease) = winners[0]
job.refresh_from_db()
assert job.runner_id == runners[winner_index].pk
assert job.lease_hash == secret_hash(lease)

barrier = Barrier(2, timeout=10)
original_fence = services.fence
def simultaneous_fence(*args, **kwargs):
    barrier.wait()
    return original_fence(*args, **kwargs)
def complete(_):
    close_old_connections()
    try:
        version = services.complete_job(job.pk, runners[winner_index], {
            'lease_token': lease, 'html': '<html>fixture</html>', 'files': {}, 'spec': {},
            'summary': 'Race fixture', 'usage': empty_usage(),
            'validation': bound_report({}, '<html>fixture</html>', {})})
        return str(version.pk)
    except Conflict:
        return None
    finally:
        connections.close_all()
with patch.object(services, 'fence', simultaneous_fence), ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(complete, range(2)))
assert sum(result is not None for result in results) == 1, results
assert Version.objects.filter(project=project).count() == 1
project.refresh_from_db()
job.refresh_from_db()
assert project.latest_version_id == job.result_version_id
assert job.status == 'completed'
print('Concurrent SQLite claim and completion: exactly one winner each.')

# Cancellation and completion must linearize as one terminal outcome. Both
# paths start with a conditional write, including on SQLite without row locks.
def artifact(raw_lease):
    return dict(lease_token=raw_lease, html='<html>race fixture</html>', files={},
                spec={}, summary='Race fixture', usage=empty_usage(),
                validation=bound_report({}, '<html>race fixture</html>', {}))

for iteration in range(4):
    project = Project.objects.create(title='Cancel race', prompt='Race')
    job = Job.objects.create(project=project, kind='generate', prompt='Race', provider='codex')
    runner = runners[winner_index]
    claimed, lease = services.claim_job(runner, {'providers': ['codex']})
    assert claimed.pk == job.pk
    barrier = Barrier(2, timeout=10)
    def finish_or_cancel(action):
        close_old_connections()
        try:
            barrier.wait()
            if action == 'cancel':
                return services.cancel_job(job.pk).status
            try:
                services.complete_job(job.pk, runner, artifact(lease))
                return 'completed'
            except Conflict:
                return 'fenced'
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(finish_or_cancel, ['complete', 'cancel']))
    job.refresh_from_db(); project.refresh_from_db()
    assert job.status in ('completed', 'cancelled'), outcomes
    assert Version.objects.filter(project=project).count() == (job.status == 'completed'), outcomes
    assert project.latest_version_id == job.result_version_id
    assert ('fenced' in outcomes) == (job.status == 'cancelled'), outcomes

# Race the actual revoke view (commit Runner, then expire Job) against the
# opposite worker lock order (Job, then Runner). No deadlock or stale publish.
user = User.objects.create(username='race-admin')
runner = Runner.objects.create(name='Revoke race', token_hash=secret_hash('revoke-race'))
project = Project.objects.create(title='Revoke race', prompt='Race')
job = Job.objects.create(project=project, kind='generate', prompt='Race', provider='codex')
claimed, lease = services.claim_job(runner, {'providers': ['codex']})
barrier = Barrier(2, timeout=10)
def finish_or_revoke(action):
    close_old_connections()
    try:
        barrier.wait()
        if action == 'revoke':
            request = APIRequestFactory().post('/api/runners/revoke/', {}, format='json')
            force_authenticate(request, user=user)
            response = RunnerRevokeView.as_view()(request, pk=runner.pk)
            assert response.status_code == 200, response.data
            return 'revoked'
        try:
            services.complete_job(job.pk, runner, artifact(lease))
            return 'completed'
        except (Conflict, AuthenticationFailed):
            return 'fenced'
    finally:
        connections.close_all()
with ThreadPoolExecutor(max_workers=2) as pool:
    outcomes = list(pool.map(finish_or_revoke, ['complete', 'revoke']))
job.refresh_from_db(); runner.refresh_from_db(); project.refresh_from_db()
assert runner.revoked
assert Version.objects.filter(project=project).count() == ('completed' in outcomes), outcomes
assert project.latest_version_id == job.result_version_id
try:
    services.complete_job(job.pk, runner, artifact(lease))
except (Conflict, AuthenticationFailed):
    pass
else:
    raise AssertionError('Revoked runner published a stale artifact')
if job.status == 'running':
    assert job.lease_expires_at <= timezone.now()
    replacement, replacement_lease = services.claim_job(runners[winner_index], {'providers': ['codex']})
    assert replacement.pk == job.pk and replacement_lease != lease
print('Concurrent SQLite cancellation and revocation: terminal outcomes and fences preserved.')
"""


class FileSQLiteConcurrencyTests(SimpleTestCase):
    def test_real_concurrent_claim_and_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "DJANGO_DB_PATH": str(Path(directory) / "race.sqlite3"),
            }
            env.pop("DATABASE_URL", None)
            for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
                env.pop(name, None)
            result = subprocess.run(
                [sys.executable, "-c", SCRIPT],
                cwd=settings.BASE_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=40,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("exactly one winner each", result.stdout)
            self.assertIn("terminal outcomes and fences preserved", result.stdout)
