"""Persisted human approval gates. Only the coordinator can release them."""

from copy import deepcopy

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from prompt2play.contracts import BuildPlan, GameSpec

from . import services, workflow
from .errors import Conflict
from .models import Job, Project, Version


def require_approved_plan(job):
    key = job.review.get("plan_key")
    if not key or job.review.get("approved_plan_key") != key:
        raise Conflict("Подтвердите план перед генерацией кода.", code="approval_required")
    return workflow.store().read_json(key)


def record_plan(job_id, runner, values):
    workflow.require_role(runner, "generator")
    try:
        GameSpec(values["spec"])
        BuildPlan(values["plan"])
    except (ValueError, TypeError) as exc:
        raise ValidationError(str(exc)) from exc
    payload = {name: values[name] for name in ("spec", "plan")}
    with transaction.atomic():
        job = services.fence(
            job_id, runner, values["lease_token"], stage_fence=values["stage_fence"]
        )
        if job.stage not in ("plan", "repair"):
            raise Conflict("Planning is not the current stage.", code="stage_conflict")
        intent, key = workflow.store().prepare(payload)
        workflow.store().commit(intent, key)
        review = deepcopy(job.review)
        changed = review.get("plan_key") != key
        review["plan_key"] = key
        review["plan_feedback_round"] = len(review.get("feedback", []))
        waiting = job.creation_mode == "pro" and review.get("approved_plan_key") != key
        changes = {"review": review, "updated_at": timezone.now()}
        if waiting:
            review["resume_stage"] = job.stage
            changes.update(
                status="waiting",
                stage="review_plan",
                progress=20,
                stage_fence=F("stage_fence") + 1,
                lease_hash="",
                lease_expires_at=None,
            )
        Job.objects.filter(pk=job.pk).update(**changes)
        if changed or waiting:
            services.event(
                job,
                "План готов. Изучите правила и оформление, подтвердите или предложите изменения."
                if waiting
                else "План игры сохранён. Правила, оформление и проверки доступны для просмотра.",
                stage="review_plan" if waiting else "plan",
                data={"plan_key": key},
            )
        from .pauses import hold_pending

        hold_pending(job.pk)
        return {"waiting": waiting, "plan_key": key}


def worker_review_context(job):
    previous = job.review.get("previous_plan_key")
    return {
        "user_feedback": job.review.get("feedback", []),
        "previous_proposal": workflow.store().read_json(previous) if previous else {},
    }


def insights(job):
    proposal = None
    if job.review.get("plan_key"):
        proposal = workflow.store().read_json(job.review["plan_key"])
    else:
        # Existing Lite runs already have completed planner receipts. They become
        # inspectable without changing their in-flight prompt or replaying calls.
        receipt = (
            job.invocations.filter(operation="plan", state="completed")
            .order_by("-created_at", "-id")
            .first()
        )
        if receipt and receipt.response_key:
            data = workflow.store().read_json(receipt.response_key).get("data", {})
            if "game_spec" in data and "build_plan" in data:
                proposal = {"spec": data["game_spec"], "plan": data["build_plan"]}
    candidate = job.active_candidate
    payload = workflow.candidate_payload(candidate) if candidate and candidate.committed else {}
    if proposal is None and payload:
        proposal = {"spec": payload["spec"], "plan": payload["plan"]}
    provenance = payload.get("provenance", {})
    author_steps, draft_reviews = [], []
    if not payload:
        for receipt in job.invocations.filter(
            state="completed", operation__in=["author", "visual_review"]
        ).order_by("created_at", "id")[:64]:
            if not receipt.response_key:
                continue
            data = workflow.store().read_json(receipt.response_key).get("data", {})
            if receipt.operation == "visual_review":
                draft_reviews.append(data)
            else:
                author_steps.append(
                    {
                        "summary": data.get("summary", ""),
                        "operations": [
                            {"op": item.get("op", ""), "path": item.get("path", "")}
                            for item in data.get("operations", [])
                            if isinstance(item, dict)
                        ],
                    }
                )
        if draft_reviews:
            provenance = {"visual_quality": {"reviews": draft_reviews, "draft_only": True}}
    report = candidate.result.report if candidate and hasattr(candidate, "result") else None
    return {
        "proposal_current": job.review.get("plan_feedback_round", 0)
        == len(job.review.get("feedback", [])),
        "job_id": str(job.pk),
        "proposal": proposal,
        "summary": candidate.summary if candidate else "",
        "files": sorted(payload.get("files", {})),
        "provenance": provenance,
        "author_steps": author_steps,
        "validation": report,
        "draft_diagnostic": workflow.store().read_json(job.checkpoint["browser_diagnostic"])[
            "report"
        ]
        if job.checkpoint.get("browser_diagnostic")
        else None,
        "feedback": job.review.get("feedback", []),
        "approval": job.stage.removeprefix("review_") if job.status == "waiting" else None,
        "version_id": str(job.result_version_id) if job.result_version_id else None,
    }


def decide_review(job_id, *, stage_fence, action, feedback=""):
    with transaction.atomic():
        original = Job.objects.get(pk=job_id)
        Project.objects.filter(pk=original.project_id).update(updated_at=F("updated_at"))
        Job.objects.filter(pk=job_id).update(updated_at=F("updated_at"))
        job = Job.objects.get(pk=job_id)
        if (
            job.creation_mode != "pro"
            or job.status != "waiting"
            or job.stage not in ("review_plan", "review_build")
            or job.stage_fence != stage_fence
        ):
            raise Conflict(
                "Предложение уже изменилось. Обновите данные перед подтверждением.",
                code="stale_approval",
            )
        review = deepcopy(job.review)
        changes = {
            "stage_fence": F("stage_fence") + 1,
            "updated_at": timezone.now(),
            "lease_hash": "",
            "lease_expires_at": None,
            "error": "",
            "review": review,
        }
        stage = job.stage.removeprefix("review_")
        if action == "approve":
            if stage == "plan":
                if not review.get("plan_key"):
                    raise Conflict("Сохранённый план недоступен.", code="missing_plan")
                review["approved_plan_key"] = review["plan_key"]
                changes.update(status="queued", stage=review.get("resume_stage", "plan"))
            else:
                version = Version.objects.filter(
                    pk=job.result_version_id, candidate__job=job
                ).first()
                if version is None or not workflow.version_eligible(version):
                    raise Conflict(
                        "Сборка не прошла обязательные проверки.", code="validation_required"
                    )
                workflow.candidate_payload(version.candidate)
                Project.objects.filter(pk=job.project_id).update(
                    latest_version=version, updated_at=timezone.now()
                )
                changes.update(status="completed", stage="done", progress=100)
            message = (
                "План подтверждён. Продолжаем создание игры."
                if stage == "plan"
                else "Вы приняли проверенную сборку. Версия стала основной."
            )
        elif action == "revise":
            feedback = feedback.strip()
            history = review.setdefault("feedback", [])
            if (
                not feedback
                or len(feedback) > 12000
                or sum(len(item["text"]) for item in history) + len(feedback) > 48000
            ):
                raise ValidationError(
                    "Опишите изменения: до 12 000 символов, до 48 000 в истории согласования."
                )
            history.append({"stage": stage, "text": feedback})
            review["previous_plan_key"] = review.get("plan_key")
            review.pop("approved_plan_key", None)
            if stage == "build":
                review["manual_revisions"] = review.get("manual_revisions", 0) + 1
            # A requested plan correction must go through planning even when a
            # repair would otherwise reuse the previous candidate's plan.
            checkpoint = {**job.checkpoint, "strategy": "replan"}
            changes.update(
                status="queued",
                stage="repair" if job.active_candidate_id else "plan",
                checkpoint=checkpoint,
            )
            message = "Замечания сохранены. Готовим обновлённый план в том же бюджете; код продолжится после подтверждения."
        else:
            raise ValidationError("Unknown approval action.")
        Job.objects.filter(pk=job.pk).update(**changes)
        services.event(
            job,
            message,
            data={
                "action": action,
                "review_stage": stage,
                "feedback_round": len(review.get("feedback", [])),
            },
        )
        job.refresh_from_db()
        return job
