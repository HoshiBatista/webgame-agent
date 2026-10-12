"""Fenced immutable authoring snapshots, separate from submitted candidates."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from prompt2play.contracts.models import digest
from prompt2play.generation.draft_state import validate_draft_state
from prompt2play.contracts.adaptive import PIPELINE_VERSION
from prompt2play.generation.supervisor import SUPERVISOR_SCHEMA, validate_decision

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
        changed_plan = digest(proposal) != digest({"spec": draft["spec"], "plan": draft["plan"]})
        controller = draft.get("adaptive")
        decision = controller["decisions"][-1] if controller and controller["decisions"] else None
        if changed_plan:
            if (
                job.checkpoint.get("pipeline_version") != PIPELINE_VERSION
                or not decision
                or decision["action"] != "revise_plan"
            ):
                raise Conflict("Draft differs from the current plan.", code="plan_conflict")
            from prompt2play.contracts.mechanics import preserve_mechanics

            if proposal["spec"] != draft["spec"]:
                raise Conflict(
                    "Requirements cannot change through a technical decision.", code="plan_conflict"
                )
            preserve_mechanics(proposal["plan"]["mechanics"], draft["plan"]["mechanics"])
            raw_decision = {k: decision[k] for k in SUPERVISOR_SCHEMA["properties"]}
            validate_decision(
                raw_decision, controller, {f["path"] for f in proposal["plan"]["files"]}
            )
            receipt_found = any(
                workflow.store().read_json(r.response_key).get("data") == raw_decision
                for r in job.invocations.filter(operation="supervisor", state="completed")
                if r.response_key
            )
            if not receipt_found:
                raise Conflict("A saved supervisor receipt is required.", code="missing_decision")
        if controller and job.checkpoint.get("authoring_draft"):
            old = (
                workflow.store().read_json(job.checkpoint["authoring_draft"]["key"]).get("adaptive")
            )
            if old and controller["versions"][: len(old["versions"])] != old["versions"]:
                raise Conflict("Immutable contract history changed.", code="contract_conflict")
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
        waiting = False
        if changed_plan:
            from .reviews import record_plan

            waiting = record_plan(
                job_id, runner, {**values, "spec": draft["spec"], "plan": draft["plan"]}
            )["waiting"]
        return {"saved": True, "key": key, "waiting": waiting}
