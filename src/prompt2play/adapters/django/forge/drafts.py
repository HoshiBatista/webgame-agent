"""Fenced immutable authoring snapshots, separate from submitted candidates."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from prompt2play.contracts.models import digest
from prompt2play.generation.draft_state import validate_draft_state

from . import services, workflow
from .errors import Conflict
from .models import Job


def draft_scope(job):
    return {
        "attempt": job.attempts + 1,
        "stage": job.stage,
        "feedback_round": len(job.review.get("feedback", [])),
    }


def load_draft(job):
    saved = job.checkpoint.get("authoring_draft")
    if not saved or saved.get("scope") != draft_scope(job):
        return {}
    draft = workflow.store().read_json(saved["key"])
    validate_draft_state(draft)
    return draft


def record_draft(job_id, runner, values):
    workflow.require_role(runner, "generator")
    draft = values["draft"]
    try:
        validate_draft_state(draft)
    except (ValueError, TypeError) as exc:
        raise ValidationError(str(exc)) from exc
    with transaction.atomic():
        job = services.fence(
            job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
        )
        if job.stage not in ("plan", "repair"):
            raise Conflict("Generation is not the current stage.", code="stage_conflict")
        from .reviews import require_approved_plan

        if job.creation_mode == "pro":
            proposal = require_approved_plan(job)
        elif job.review.get("plan_key"):
            proposal = workflow.store().read_json(job.review["plan_key"])
        else:
            raise Conflict("Save the plan before the draft.", code="missing_plan")
        if digest(proposal) != digest({"spec": draft["spec"], "plan": draft["plan"]}):
            raise Conflict("Draft differs from the current plan.", code="plan_conflict")
        intent, key = workflow.store().prepare(draft)
        workflow.store().commit(intent, key)
        previous = job.checkpoint.get("authoring_draft", {})
        Job.objects.filter(pk=job.pk).update(
            checkpoint={
                **job.checkpoint,
                "authoring_draft": {"key": key, "scope": draft_scope(job)},
            },
            updated_at=timezone.now(),
        )
        if previous.get("key") != key:
            services.event(
                job,
                "Черновик сохранён. Создание можно продолжить с этого шага.",
                stage="visual_review" if draft["phase"] == "review" else "author",
                data={"turn": draft["turn"], "phase": draft["phase"], "draft_key": key},
            )
        return {"saved": True, "key": key}
