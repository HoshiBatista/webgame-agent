from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from studio.models import Chat, Run, RunEvent, User
from studio.run_timings import run_timings


@pytest.mark.django_db
def test_timeline_counts_concurrent_calls_once_and_stops_at_cancellation():
    start = timezone.now() - timedelta(seconds=20)
    chat = Chat.objects.create(owner=User.objects.create(username="timeline"))
    run = Run.objects.create(chat=chat, status="cancelled", finished_at=start + timedelta(seconds=16))
    Run.objects.filter(pk=run.pk).update(created_at=start)
    run.refresh_from_db()
    claim = RunEvent.objects.create(run=run, kind="generating")
    RunEvent.objects.filter(pk=claim.pk).update(created_at=start + timedelta(seconds=2))

    def call(attempt, role, sent, finished=None):
        return SimpleNamespace(attempt=attempt, request={"pro_parallel_branch": role},
            state="sent" if finished is None else "settled",
            sent_at=start + timedelta(seconds=sent),
            finished_at=None if finished is None else start + timedelta(seconds=finished))

    report = run_timings(run, [call(1, "scene", 4, 13), call(2, "graphics", 7, 10), call(3, "audio", 11),
                               call(4, "repair", 15, 14)])
    assert report["initial_queue_seconds"] == 2
    assert report["total_seconds"] == 16
    assert report["provider_wall_seconds"] == 12
    assert report["provider_sum_seconds"] == 17
    assert [(row["role"], row["wall_seconds"]) for row in report["calls"]] == [
        ("scene", 9), ("graphics", 3), ("audio", 5), ("repair", 0)]
    assert report["packaging_seconds"] is None
