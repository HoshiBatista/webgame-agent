"""Explicit recovery from obsolete authoring limits, using only saved receipts."""

from copy import deepcopy

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from prompt2play.generation import GenerationControl, GenerationHarness
from prompt2play.generation.gateway import GatewayReply
from prompt2play.workers.runner import generation_request

from . import services, workflow
from .drafts import draft_scope, load_draft
from .errors import Conflict
from .models import Job, Project
from .representations import job_data, version_data
from .reviews import worker_review_context

LIMIT_ERRORS = {
    "ProviderError: Provider returned invalid structured JSON; maxItems at /operations",
    "GenerationStopped: Draft operation budget exceeded",
    "GenerationStopped: Quick-check budget exceeded",
    "GenerationStopped: Attempt exhausted its turn budget without submitting a candidate",
    "GenerationStopped: Visual source review still requires changes; candidate not submitted",
    "GenerationStopped: Repeated identical tool call batch",
    "GenerationStopped: Repeated no-op writes",
}


class ReceiptsExhausted(Exception):
    pass


def reconstruct_draft(job):
    """No provider, no network, no generated execution. Reapply recorded data."""
    existing = load_draft(job)
    if existing:
        return existing
    if job.attempts or job.review.get("feedback"):
        raise Conflict(
            "Legacy recovery requires an unambiguous first attempt.", code="not_resumable"
        )
    receipts = []
    for invocation in job.invocations.filter(state="completed").order_by("created_at", "id"):
        if not invocation.response_key:
            raise Conflict("Completed response is missing.", code="not_resumable")
        receipts.append((invocation, workflow.store().read_json(invocation.response_key)))
    if not receipts:
        raise Conflict("No saved generation responses.", code="not_resumable")
    snapshots = []

    class ReceiptGateway:
        name = job.provider
        model = job.model
        capabilities = frozenset({"structured_output", "file_operations"})

        def generate(self, _prompt, _schema, role, control, **_kwargs):
            control.guard()
            if not receipts:
                raise ReceiptsExhausted()
            invocation, response = receipts.pop(0)
            if invocation.operation != role:
                raise Conflict(
                    "Saved response sequence differs from this workflow.", code="not_resumable"
                )
            return GatewayReply(
                response["data"], response["usage"], invocation.invocation_key, reused=True
            )

    claim = {
        "job": {**job_data(job), "checkpoint": job.checkpoint},
        **worker_review_context(job),
        "base_version": version_data(job.base_version, detail=True)
        if job.base_version_id
        else None,
    }
    try:
        GenerationHarness(on_checkpoint=lambda state: snapshots.append(deepcopy(state))).attempt(
            generation_request(claim, "single_author"),
            ReceiptGateway(),
            GenerationControl.bounded(),
        )
    except ReceiptsExhausted:
        pass
    if receipts or not snapshots or not snapshots[-1]["files"]:
        raise Conflict("No complete saved draft could be reconstructed.", code="not_resumable")
    return snapshots[-1]


def resume_authoring(job_id):
    with transaction.atomic():
        original = Job.objects.get(pk=job_id)
        Project.objects.filter(pk=original.project_id).update(updated_at=F("updated_at"))
        Job.objects.filter(pk=job_id).update(updated_at=F("updated_at"))
        job = Job.objects.get(pk=job_id)
        if (
            job.status != "failed"
            or job.stage not in ("plan", "repair")
            or job.error not in LIMIT_ERRORS
        ):
            raise Conflict(
                "Only a failed obsolete authoring limit may resume.", code="not_resumable"
            )
        if Job.objects.filter(
            project_id=job.project_id, status__in=["queued", "running", "waiting", "paused"]
        ).exists():
            raise Conflict("The project already has an active job.", code="active_job")
        # A transport timeout/unknown call must not turn into permission for a new call.
        latest = job.invocations.order_by("-created_at", "-id").first()
        if latest is None or latest.actual_usage is None or latest.state == "reserved":
            raise Conflict("The last model invocation is not reconciled.", code="not_resumable")
        draft = reconstruct_draft(job)
        # This is an explicit new continuation, not an ambiguous old dispatch.
        # Keep the source/review feedback, but use a distinct request identity.
        field = "review_feedback" if draft["phase"] == "review" else "feedback"
        draft[field].append(
            {
                "error": "The previous attempt stopped at an obsolete operation/turn limit. Continue from these saved files; the rejected response was not applied.",
                "recovery": job.resume_count + 1,
            }
        )
        intent, key = workflow.store().prepare(draft)
        workflow.store().commit(intent, key)
        Job.objects.filter(pk=job.pk).update(
            status="queued",
            error="",
            resume_count=F("resume_count") + 1,
            stage_fence=F("stage_fence") + 1,
            lease_hash="",
            lease_expires_at=None,
            checkpoint={
                **job.checkpoint,
                "authoring_draft": {"key": key, "scope": draft_scope(job)},
            },
            updated_at=timezone.now(),
        )
        services.event(
            job,
            "Запуск продолжен с сохранённого черновика после снятия ограничения числа правок. Расходы и денежный лимит сохранены.",
            level="warning",
            data={
                "reason": "obsolete_authoring_limit",
                "previous_error": job.error,
                "draft_key": key,
                "turn": draft["turn"],
            },
        )
        job.refresh_from_db()
        return job
