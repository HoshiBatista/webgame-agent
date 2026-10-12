"""Celery entry points; PostgreSQL remains the workflow source of truth."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy import select

from prompt2play.adapters.artifacts import ArtifactStore
from prompt2play.adapters.openai_gateway import OpenAIModelGateway
from prompt2play.application.workflow import generate_run, specify_run, validate_run
from prompt2play.config import get_settings
from prompt2play.db import SessionLocal
from prompt2play.models import OutboxEvent

settings = get_settings()
celery_app = Celery("prompt2play", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    broker_transport_options={"visibility_timeout": 900},
    task_routes={
        "prompt2play.specify": {"queue": "models"},
        "prompt2play.generate": {"queue": "models"},
        "prompt2play.repair": {"queue": "models"},
        "prompt2play.validate": {"queue": "validation"},
        "prompt2play.dispatch_outbox": {"queue": "workflow"},
    },
    beat_schedule={"recover-outbox": {"task": "prompt2play.dispatch_outbox", "schedule": 5.0}},
)


def _gateway() -> OpenAIModelGateway:
    return OpenAIModelGateway(settings)


def _artifacts() -> ArtifactStore:
    return ArtifactStore(settings.artifact_root)


@celery_app.task(name="prompt2play.specify", acks_late=True)  # type: ignore[untyped-decorator]
def specify_task(run_id: str) -> bool:
    result = specify_run(SessionLocal, _gateway, UUID(run_id))
    dispatch_outbox.delay()
    return result


@celery_app.task(  # type: ignore[untyped-decorator]
    name="prompt2play.generate", acks_late=True, soft_time_limit=240, time_limit=270
)
def generate_task(run_id: str) -> bool:
    result = generate_run(SessionLocal, _gateway, _artifacts(), UUID(run_id))
    dispatch_outbox.delay()
    return result


@celery_app.task(  # type: ignore[untyped-decorator]
    name="prompt2play.repair", acks_late=True, soft_time_limit=240, time_limit=270
)
def repair_task(run_id: str) -> bool:
    result = generate_run(SessionLocal, _gateway, _artifacts(), UUID(run_id), repair=True)
    dispatch_outbox.delay()
    return result


@celery_app.task(  # type: ignore[untyped-decorator]
    name="prompt2play.validate", acks_late=True, soft_time_limit=75, time_limit=90
)
def validate_task(run_id: str) -> bool:
    result = validate_run(SessionLocal, _artifacts(), settings, UUID(run_id))
    dispatch_outbox.delay()
    return result


TASK_NAMES = {
    "specify": "prompt2play.specify",
    "generate": "prompt2play.generate",
    "repair": "prompt2play.repair",
    "validate": "prompt2play.validate",
}


@celery_app.task(  # type: ignore[untyped-decorator]
    name="prompt2play.dispatch_outbox", acks_late=True
)
def dispatch_outbox() -> int:
    """Publish pending stage commands, leaving failures durable for Beat recovery."""

    sent = 0
    with SessionLocal() as session, session.begin():
        events = session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id)
            .limit(50)
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            task_name = TASK_NAMES.get(event.event_type)
            if task_name is None:
                event.attempts += 1
                continue
            celery_app.send_task(task_name, kwargs=event.payload)
            event.published_at = datetime.now(UTC)
            event.attempts += 1
            sent += 1
    return sent
