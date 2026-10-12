"""Planning replies are checkpoints too, including proposals needing correction."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from prompt2play.contracts.models import stable
from . import services, workflow
from .drafts import draft_scope
from .errors import Conflict
from .models import Job


def load_planning(job):
    saved = job.checkpoint.get("planning", {})
    if saved.get("scope") != draft_scope(job):
        return {}
    value = workflow.store().read_json(saved["key"])
    if saved.get("reset_stall"):
        value["repeat_count"] = 0
    return value


def save_state(job, state):
    intent, key = workflow.store().prepare(state)
    workflow.store().commit(intent, key)
    Job.objects.filter(pk=job.pk).update(
        checkpoint={**job.checkpoint, "planning": {"key": key, "scope": draft_scope(job)}},
        updated_at=timezone.now(),
    )
    return key


def remember_response(job, proposal):
    state = load_planning(job)
    save_state(job, {**state, "proposal": proposal, "needs_validation": True})


def record_planning(job_id, runner, values):
    workflow.require_role(runner, "generator")
    state = values["planning"]
    if not isinstance(state.get("proposal"), dict) or len(stable(state).encode()) > 1000000:
        raise ValidationError("Invalid planning checkpoint")
    with transaction.atomic():
        job = services.fence(
            job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
        )
        if job.stage not in ("plan", "repair"):
            raise Conflict("Planning is not the current stage.", code="stage_conflict")
        key = save_state(job, state)
        feedback = state.get("feedback", {})
        services.event(
            job,
            "План требует исправления: " + str(feedback.get("error", "формат ответа"))[:1200],
            level="warning",
            data={
                "correction": state.get("correction", 0),
                "same_problem_count": state.get("repeat_count", 0),
                "planning_key": key,
            },
        )
        return {"saved": True}
