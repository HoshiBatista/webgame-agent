from django.conf import settings
from django.core import signing
from django.utils import timezone

from .services import budget_snapshot


def preview_url(revision):
    token = signing.dumps(
        {"revision": str(revision.id), "hash": revision.artifact_hash}, salt="game-preview", compress=True
    )
    return f"{settings.GAMEFORGE_PREVIEW_ORIGIN}/preview/{token}/"


def revision_data(revision):
    if revision is None:
        return None
    report = revision.reports.order_by("-id").first()
    return {
        "id": str(revision.id),
        "title": revision.title,
        "number": revision.number,
        "artifact_hash": revision.artifact_hash,
        "design": revision.design,
        "checks": revision.checks,
        "created_at": revision.created_at.isoformat(),
        "accepted": revision.accepted,
        "verification": revision.verification,
        "preview_url": preview_url(revision),
        "export_url": f"/api/revisions/{revision.id}/export/",
        "parent_id": str(revision.parent_id) if revision.parent_id else None,
        "report": {
            "status": report.status,
            "findings": report.findings,
            "facts": report.facts,
            "elapsed_seconds": report.elapsed_seconds,
        }
        if report
        else None,
    }


def run_data(run, budget=None):
    if run is None:
        return None
    elapsed = ((run.finished_at or timezone.now()) - run.created_at).total_seconds()
    return {
        "id": str(run.id),
        "chat_id": str(run.chat_id),
        "operation": run.operation,
        "status": run.status,
        "stage": run.stage,
        "message": run.message,
        "prompt": run.prompt,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "base_revision_id": str(run.base_revision_id) if run.base_revision_id else None,
        "candidate_revision_id": str(run.candidate_revision_id) if run.candidate_revision_id else None,
        "result_revision_id": str(run.result_revision_id) if run.result_revision_id else None,
        "error": run.error,
        "can_cancel": run.status in run.ACTIVE,
        "can_continue": run.status in ("needs_attention", "unverified", "failed", "cancelled")
        and not run.invocations.filter(state="unknown").exists(),
        "can_confirm": run.status == "unverified" and bool(run.candidate_revision_id),
        "attempts": run.attempts,
        "elapsed_seconds": elapsed,
        "events_url": f"/api/runs/{run.id}/events/",
        "budget": budget if budget is not None else budget_snapshot(),
        "metrics": run.metrics,
    }


def chat_data(chat, detail=False):
    budget = budget_snapshot() if detail else None
    active = chat.runs.filter(status__in=("queued", "generating", "checking")).order_by("-created_at").first()
    data = {
        "id": str(chat.id),
        "title": chat.title,
        "audience": chat.audience,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
        "current_revision": revision_data(chat.current_revision),
        "active_run": run_data(active, budget),
        "source_publication": str(chat.source_publication_id) if chat.source_publication_id else None,
    }
    if detail:
        last = chat.runs.order_by("-created_at").first()
        data.update(
            {
                "candidate_revision": revision_data(last.candidate_revision) if last else None,
                "messages": [
                    {
                        "id": str(m.id),
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at.isoformat(),
                        "run_id": str(m.run_id) if m.run_id else None,
                    }
                    for m in chat.messages.all()
                ],
                "revisions": [revision_data(v) for v in chat.revisions.all()],
                "runs": [run_data(r, budget) for r in chat.runs.order_by("-created_at")[:30]],
            }
        )
    return data


def publication_data(publication, user=None):
    own = bool(user and user.is_authenticated and publication.owner_id == user.id)
    auth = bool(user and user.is_authenticated)
    return {
        "id": str(publication.id),
        "title": publication.title,
        "author": {"id": publication.owner_id, "username": publication.owner.username}
        if auth
        else {"username": publication.owner.username},
        "created_at": publication.created_at.isoformat(),
        "updated_at": publication.updated_at.isoformat(),
        "revision_id": str(publication.revision_id),
        "artifact_hash": publication.revision.artifact_hash,
        "preview_url": preview_url(publication.revision),
        "thumbnail_url": f"/api/publications/{publication.id}/thumbnail/"
        if publication.revision.reports.exclude(screenshot_base64="").exists()
        else None,
        "likes": publication.likes.count(),
        "liked": publication.likes.filter(user=user).exists() if auth else False,
        "is_owner": own,
        "source_chat_id": str(publication.source_chat_id)
        if own and publication.source_chat and not publication.source_chat.deleted_at
        else None,
        "verification": publication.revision.verification,
        "public_url": f"{settings.GAMEFORGE_APP_ORIGIN}/games/{publication.id}",
    }
