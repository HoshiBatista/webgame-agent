"""Small polling reads; artifacts/checkpoints are loaded only by their consumers."""

from django.db.models import Case, Prefetch, Value, When

from .models import Job, Project


def public_jobs():
    return Job.objects.defer("checkpoint", "lease_hash")


def public_projects():
    # Django implements a sliced related prefetch with a partitioned window:
    # at most one job per project, including when many projects have history.
    recent = (
        public_jobs()
        .annotate(
            _active_first=Case(
                When(status__in=["queued", "running", "waiting"], then=Value(0)),
                default=Value(1),
            )
        )
        .order_by("_active_first", "-created_at", "-id")[:1]
    )
    return (
        Project.objects.select_related("latest_version")
        .only(
            "id",
            "title",
            "prompt",
            "created_at",
            "updated_at",
            "latest_version__number",
        )
        .prefetch_related(Prefetch("jobs", queryset=recent, to_attr="_recent_jobs"))
    )
