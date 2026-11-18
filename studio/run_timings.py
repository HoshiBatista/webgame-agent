"""Elapsed time from stored receipts, including overlapping experimental branches."""

from django.utils import timezone


def covered_seconds(intervals):
    """Length of the union. Two jobs running for the same second count once."""
    total = 0.0
    last_end = 0.0
    for start, end in sorted(intervals):
        total += max(0.0, end - max(last_end, start))
        last_end = max(end, last_end)
    return total


def run_timings(run, invocations):
    end = run.finished_at or timezone.now()
    total = max(0.0, (end - run.created_at).total_seconds())

    def offset(moment):
        return max(0.0, min(total, (moment - run.created_at).total_seconds()))

    def interval(start_time, end_time):
        start = offset(start_time)
        return start, max(start, offset(end_time or end))

    calls = []
    intervals = []
    for call in invocations:
        if not call.sent_at:
            continue
        start, stop = interval(call.sent_at, call.finished_at)
        intervals.append((start, stop))
        calls.append({
            "attempt": call.attempt,
            "role": call.request.get("pro_parallel_branch") or call.request.get("operation"),
            "state": call.state,
            "start_seconds": round(start, 3),
            "wall_seconds": round(stop - start, 3),
        })

    first_claim = run.events.filter(kind__in=("generating", "checking")).order_by(
        "created_at", "id"
    ).values_list("created_at", flat=True).first()
    queue = offset(first_claim) if first_claim else run.metrics.get("queue_seconds")
    if queue is None and not calls and (run.status in ("queued", "cancelled") or run.stage == "waiting_capacity"):
        queue = total

    checks = list(run.validations.order_by("created_at").values(
        "created_at", "finished_at", "status", "timings"
    ))
    validation_intervals = [interval(job["created_at"], job["finished_at"]) for job in checks]
    return {
        "total_seconds": round(total, 3),
        "initial_queue_seconds": None if queue is None else round(min(total, queue), 3),
        "provider_wall_seconds": round(covered_seconds(intervals), 3),
        "provider_sum_seconds": round(sum(stop - start for start, stop in intervals), 3),
        "packaging_seconds": run.metrics.get("packaging_seconds"),
        "validation_wall_seconds": round(covered_seconds(validation_intervals), 3),
        "calls": calls,
        "validations": [{
            "status": job["status"],
            "start_seconds": round(start, 3),
            "wall_seconds": round(stop - start, 3),
            "queue_seconds": job["timings"].get("queue_seconds"),
            "execution_seconds": job["timings"].get("execution_seconds"),
        } for job, (start, stop) in zip(checks, validation_intervals, strict=True)],
    }
