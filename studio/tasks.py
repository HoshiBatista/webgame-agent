import logging
import threading
import time
import traceback
import uuid
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import close_old_connections, connections, transaction
from django.db.models import Max, Q
from django.utils import timezone

from .models import Budget, Chat, CheckReport, Invocation, Outbox, Revision, Run
from .services import (
    DomainError,
    event,
    fingerprint,
    finish_run,
    preference_for,
    reserve_invocation,
    settle_invocation,
)


def dispatch_run(run_id):
    """Claim a durable notification before publishing, without overwriting worker updates."""
    retry_before = timezone.now() - timedelta(seconds=15)
    with transaction.atomic():
        row = (
            Outbox.objects.select_for_update(of=("self",), skip_locked=True)
            .filter(run_id=run_id, run__status="queued")
            .filter(Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=retry_before))
            .first()
        )
        if row is None:
            return False
        sent_at = timezone.now()
        row.dispatched_at = sent_at
        row.save(update_fields=["dispatched_at"])
    try:
        process_run.delay(str(run_id))
    except Exception as exc:
        # The committed outbox remains the retry authority if broker publication fails.
        Outbox.objects.filter(run_id=run_id, dispatched_at=sent_at).update(dispatched_at=None)
        logging.getLogger(__name__).warning("dispatch_failed run=%s type=%s", run_id, type(exc).__name__)
        return False
    return True


@shared_task(acks_late=False)
def dispatch_outbox():
    retry_before = timezone.now() - timedelta(seconds=15)
    for run_id in (
        Outbox.objects.filter(run__status="queued")
        .filter(Q(dispatched_at__isnull=True) | Q(dispatched_at__lt=retry_before, run__status="queued"))
        .order_by("created_at")
        .values_list("run_id", flat=True)[:100]
    ):
        dispatch_run(run_id)


@shared_task(acks_late=False)
def recover_expired():
    # Requests abandoned during cancellation still retain a liability, never an active reservation forever.
    abandoned = Invocation.objects.filter(
        state__in=["reserved", "sent"], run__status="cancelled", run__lease_until__lt=timezone.now()
    )
    for inv in abandoned:
        settle_invocation(
            inv.id,
            error={"code": "worker_lost", "message": "Выполнение отменено; ответ провайдера не получен."},
            unknown=bool(inv.sent_at),
        )
    for ident in Run.objects.filter(
        status__in=["generating", "checking"], lease_until__lt=timezone.now()
    ).values_list("id", flat=True):
        with transaction.atomic():
            run = Run.objects.select_for_update().get(pk=ident)
            if (
                run.status not in ("generating", "checking")
                or not run.lease_until
                or run.lease_until >= timezone.now()
            ):
                continue
            unresolved = run.invocations.filter(state="sent")
            if unresolved.exists():
                unresolved.update(
                    state="unknown",
                    finished_at=timezone.now(),
                    error={
                        "code": "worker_lost",
                        "message": "Worker завершился после отправки запроса; ответ и расход требуют сверки.",
                    },
                )
                run.status = "unknown"
                run.message = "Связь с выполнением потеряна после отправки модели. Повтор заблокирован до сверки ответа и расхода."
                run.error = {"code": "outcome_unknown", "message": run.message}
                run.finished_at = timezone.now()
                event(run, "unknown", run.message)
            else:
                run.invocations.filter(state="reserved").update(
                    state="failed", cost_usd=0, finished_at=timezone.now()
                )
                # Returned responses and candidates are durable; process_run reuses them.
                run.status = "queued"
                run.message = "Восстанавливаем сохранённый шаг после перезапуска."
                Outbox.objects.update_or_create(run=run, defaults={"dispatched_at": None})
                event(run, "recovered", run.message)
            run.fence = None
            run.lease_until = None
            run.save()


@transaction.atomic
def claim_run(run_id):
    Budget.objects.get_or_create(pk=1, defaults={"limit_usd": settings.GAMEFORGE_BUDGET_USD})
    Budget.objects.select_for_update().get(pk=1)
    run = (
        Run.objects.select_for_update(of=("self",))
        .select_related("chat", "chat__owner", "base_revision", "candidate_revision", "continued_from")
        .get(pk=run_id)
    )
    if run.status != "queued" or run.cancel_requested or run.chat.deleted_at:
        return None
    # Count in-flight model requests, including cancellation until transport has really stopped.
    active = (
        Invocation.objects.filter(state__in=["reserved", "sent"], run__provider=run.provider)
        .exclude(run=run)
        .count()
    )
    processing = (
        Run.objects.filter(provider=run.provider, status__in=["generating", "checking"])
        .exclude(pk=run.pk)
        .count()
    )
    if max(active, processing) >= settings.GAMEFORGE_PROVIDER_CONCURRENCY:
        return False
    run.fence = uuid.uuid4()
    run.lease_until = timezone.now() + timedelta(seconds=settings.GAMEFORGE_LEASE_SECONDS)
    run.status = "generating"
    run.stage = "generating"
    run.message = (
        "Создаём игру одним запросом."
        if run.operation == "create"
        else "Готовим точечные изменения сохранённой игры."
    )
    run.metrics = {**run.metrics, "queue_seconds": (timezone.now() - run.created_at).total_seconds()}
    run.save()
    event(run, "generating", run.message)
    return run


class Lease:
    def __init__(self, run):
        self.id, self.fence = run.id, run.fence
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._renew, daemon=True)

    def _renew(self):
        while not self.stop.wait(max(1, settings.GAMEFORGE_LEASE_SECONDS / 3)):
            close_old_connections()
            try:
                if not Run.objects.filter(
                    pk=self.id, fence=self.fence, status__in=Run.ACTIVE, cancel_requested=False
                ).update(lease_until=timezone.now() + timedelta(seconds=settings.GAMEFORGE_LEASE_SECONDS)):
                    break
            finally:
                connections.close_all()

    def cancelled(self):
        return not Run.objects.filter(
            pk=self.id,
            fence=self.fence,
            status__in=Run.ACTIVE,
            cancel_requested=False,
            chat__deleted_at__isnull=True,
        ).exists()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=2)


@transaction.atomic
def store_candidate(run, materialized, base):
    Chat.objects.select_for_update().get(pk=run.chat_id)
    current = Run.objects.select_for_update().get(pk=run.id)
    if current.fence != run.fence or current.cancel_requested:
        return None
    number = (Revision.objects.filter(chat_id=run.chat_id).aggregate(n=Max("number"))["n"] or 0) + 1
    revision = Revision.objects.create(
        chat_id=run.chat_id,
        run=run,
        parent=base,
        number=number,
        title=materialized.get("title", "Мини-игра")[:160],
        files=materialized["files"],
        html=materialized["html"],
        artifact_hash=materialized["artifact_hash"],
        file_hashes=materialized.get("file_hashes", {}),
        design=materialized.get("design", {}),
        checks=materialized.get("checks", []),
        diff=materialized.get("diff", []),
    )
    current.candidate_revision = revision
    current.status = "checking"
    current.stage = "checking"
    current.message = "Проверяем загрузку, управление и игровой результат."
    current.save()
    event(current, "checking", current.message)
    return revision


def request_for(run, base, findings):
    import hashlib

    from generation.prompts import repair_evidence, system_prompt
    from generation.schema import RESPONSE_SCHEMA

    # Only a materialized candidate establishes fixed requirements for repair.
    operation = "create" if base is None else "edit" if base.id == run.base_revision_id else "repair"
    request = {
        "operation": operation,
        "prompt": run.prompt,
        "audience": run.audience,
        "preferences": preference_for(run.chat.owner).notes,
        "base_revision": str(base.id) if base else None,
        "files": base.files if base else {},
        "design": base.design if base else {},
        "checks": base.checks if base else [],
        "findings": findings,
        "provider": run.provider,
        "model": run.model,
        "generation_contract": {
            "system_prompt_sha256": hashlib.sha256(system_prompt(operation).encode()).hexdigest(),
            "response_schema_sha256": fingerprint(RESPONSE_SCHEMA),
        },
    }

    if base is not None and findings:
        report = base.reports.order_by("-id").first()
        # A patch/packaging error must not be paired with an unrelated older browser report.
        if report and report.findings == findings and report.status in {"failed", "unverified"}:
            request["validation_evidence"] = repair_evidence({"status": report.status, "facts": report.facts})

    if run.provider == "vllm":
        from .services import tariff

        price = tariff(run.provider, run.model)
        request["execution_limits"] = {key: price.get(key) for key in ("context_window", "max_output_tokens")}
    return request


def record_exception(run, exc, stage):
    diagnostics = list(Run.objects.get(pk=run.id).private_diagnostics)
    diagnostics.append(
        {
            "stage": stage,
            "type": type(exc).__name__,
            "traceback": traceback.format_exc()[-20000:],
            "at": timezone.now().isoformat(),
        }
    )
    Run.objects.filter(pk=run.id).update(private_diagnostics=diagnostics[-10:])
    logging.getLogger(__name__).error("run_failed run=%s stage=%s type=%s", run.id, stage, type(exc).__name__)


def check_identity(revision):
    from validation import service

    environment = service.environment_identity()
    return fingerprint(
        {"artifact": revision.artifact_hash, "checks": revision.checks, "validator": environment}
    )


def error_data(exc):
    return {
        "code": getattr(exc, "code", "internal_error"),
        "message": getattr(
            exc, "message", "Внутренняя ошибка. Сохранённый результат доступен для продолжения."
        ),
    }


@shared_task(bind=True, max_retries=None)
def process_run(self, run_id):
    from generation.artifacts import materialize
    from generation.service import generate
    from validation.service import validate

    run = claim_run(run_id)
    if run is False:
        # The durable dispatcher is the single retry source; no parallel Celery retry chains.
        Outbox.objects.filter(run_id=run_id).update(dispatched_at=None)
        return
    if run is None:
        return
    with Lease(run) as lease:
        try:
            _execute(run, lease, generate, materialize, validate)
        except Exception as exc:
            record_exception(run, exc, "pipeline")
            # If storage failed after sending, the request may still be billable.
            unresolved = run.invocations.filter(state="sent")
            ambiguous = unresolved.exists()
            unresolved.update(
                state="unknown",
                finished_at=timezone.now(),
                error={
                    "code": "receipt_storage_failed",
                    "message": "Ответ после отправки не был надёжно сохранён.",
                },
            )
            run.invocations.filter(state="reserved").update(
                state="failed", cost_usd=0, finished_at=timezone.now()
            )
            # Never let a crashed task trigger Celery's blind paid retry.
            finish_run(
                run.id,
                run.fence,
                "unknown" if ambiguous else "failed",
                "Не удалось завершить шаг. Сохранённые ответы и черновик доступны для продолжения.",
                error=error_data(exc),
            )
    # Capacity has just been released. Wake durable waiting jobs now, not at the next beat tick.
    transaction.on_commit(dispatch_outbox, robust=True)


def _execute(run, lease, generate, materialize, validate):
    from generation.errors import ContractError

    base = run.candidate_revision or run.base_revision
    findings = []
    # A continued infrastructure failure only needs validation, not another model call.
    pending = (
        run.candidate_revision
        if run.candidate_revision
        and (
            run.candidate_revision.run_id == run.id
            or (
                run.continued_from
                and (
                    (run.continued_from.error or {}).get("code") == "validator_unavailable"
                    or not run.candidate_revision.reports.exists()
                )
            )
        )
        else None
    )
    if run.candidate_revision and run.continued_from:
        previous_report = run.candidate_revision.reports.order_by("-id").first()
        if previous_report and previous_report.identity != check_identity(run.candidate_revision):
            # A validator fix invalidates evidence, not game code; recheck before another paid edit.
            pending = run.candidate_revision
    preserved_response = (
        run.continued_from.invocations.filter(state="returned", revision__isnull=True)
        .order_by("attempt")
        .first()
        if run.continued_from
        else None
    )
    if run.continued_from and not pending:
        previous = run.continued_from
        report = base.reports.order_by("-id").first() if base else None
        findings = (
            report.findings if report else [previous.error or {"message": "Продолжить сохранённый запрос."}]
        )
    while not lease.cancelled():
        run.refresh_from_db()
        inv = (
            run.invocations.filter(state="returned", revision__isnull=True).order_by("attempt").first()
            or preserved_response
        )
        preserved_response = None
        if inv is not None:
            # Exact request base is durable: recovery cannot apply a saved patch to a later draft.
            base_id = inv.request.get("base_revision")
            response_base = Revision.objects.filter(pk=base_id).first() if base_id else None
            response = inv.response
            if response.get("status") == "scope_refusal":
                inv.state = "settled"
                inv.save(update_fields=["state"])
                finish_run(
                    run.id,
                    run.fence,
                    "needs_attention",
                    response.get("message") or "Уточните объём мини-игры.",
                    error={"code": "scope_refusal", "message": response.get("message", "Уточните запрос.")},
                )
                return
            try:
                packaging_started = time.monotonic()
                artifact = materialize(
                    response,
                    operation=inv.request["operation"],
                    base_revision=str(response_base.id) if response_base else None,
                    files=response_base.files if response_base else None,
                    previous_checks=response_base.checks if response_base else None,
                )
                run.metrics = {
                    **run.metrics,
                    "packaging_seconds": run.metrics.get("packaging_seconds", 0)
                    + time.monotonic()
                    - packaging_started,
                }
                Run.objects.filter(pk=run.id, fence=run.fence).update(metrics=run.metrics)
                if artifact.get("status") == "unchanged":
                    explanation = artifact["message"]
                    with transaction.atomic():
                        if finish_run(
                            run.id,
                            run.fence,
                            "needs_attention",
                            f"Изменения не внесены. {explanation}",
                            error={"code": "unchanged", "message": explanation},
                        ):
                            inv.state = "settled"
                            inv.save(update_fields=["state"])
                    return
                with transaction.atomic():
                    pending = store_candidate(run, artifact, response_base)
                    inv.revision = pending
                    inv.state = "settled"
                    inv.save(update_fields=["revision", "state"])
                if pending is None:
                    return
                base = pending
            except ContractError as exc:
                inv.state = "settled"
                inv.error = error_data(exc)
                inv.save(update_fields=["state", "error"])
                findings = [error_data(exc)]
                pending = None
                event(
                    run,
                    "contract_error",
                    "Ответ сохранён; исправляем проблему формата, изменений или проверок.",
                    {"code": findings[0]["code"]},
                )
        if pending is not None:
            identity = check_identity(pending)
            report = (
                pending.reports.filter(identity=identity)
                .exclude(status="infrastructure_error")
                .order_by("-id")
                .first()
            )
            if report is None:
                Run.objects.filter(pk=run.id, fence=run.fence).update(
                    status="checking",
                    stage="checking",
                    message="Проверяем загрузку, управление и игровой результат.",
                )
                cached = CheckReport.objects.filter(identity=identity, status="passed").first()
                if cached:
                    result = {
                        "status": cached.status,
                        "findings": cached.findings,
                        "facts": cached.facts,
                        "elapsed_seconds": 0,
                        "environment": cached.environment,
                    }
                else:
                    try:
                        result = validate(pending.html, pending.checks, artifact_hash=pending.artifact_hash)
                    except Exception as exc:
                        record_exception(run, exc, "validation")
                        result = {
                            "status": "infrastructure_error",
                            "findings": [
                                {"code": "validator_unavailable", "message": "Среда проверки недоступна."}
                            ],
                        }
                report = CheckReport.objects.create(
                    validation_run=run,
                    revision=pending,
                    status=result["status"],
                    findings=result.get("findings", []),
                    facts=result.get("facts", []),
                    elapsed_seconds=result.get("elapsed_seconds", 0),
                    environment=result.get("environment", {}),
                    screenshot_base64=result.get("screenshot_base64") or "",
                    screenshot_mime=result.get("screenshot_mime", "image/png"),
                    identity=identity,
                )
            if lease.cancelled():
                return
            if report.status == "passed":
                finish_run(
                    run.id,
                    run.fence,
                    "succeeded",
                    "Игра готова. Управление и основные игровые условия проверены.",
                    revision=pending,
                )
                return
            if report.status == "unverified" and run.attempts >= 2:
                finish_run(
                    run.id,
                    run.fence,
                    "unverified",
                    "Игра сохранена. Проверьте отмеченные условия в preview и подтвердите результат.",
                    error={
                        "code": "manual_verification",
                        "message": "Автоматически подтверждены не все условия.",
                        "details": report.findings,
                    },
                )
                return
            if report.status == "infrastructure_error":
                finish_run(
                    run.id,
                    run.fence,
                    "failed",
                    "Игра сохранена, но среда проверки недоступна. Продолжение повторит проверку без новой генерации.",
                    error={
                        "code": "validator_unavailable",
                        "message": "Ошибка среды проверки.",
                        "details": report.findings,
                    },
                )
                return
            findings = report.findings
            base = pending
            pending = None
        run.refresh_from_db()
        if run.attempts >= 2:
            finish_run(
                run.id,
                run.fence,
                "needs_attention",
                "После одной автоправки остались проблемы. Ответ и черновик сохранены; доступно продолжение.",
                error={
                    "code": "repair_exhausted",
                    "message": "Остались проблемы применения или проверки.",
                    "details": findings,
                },
            )
            return
        req = request_for(run, base, findings)
        try:
            with transaction.atomic():
                inv = reserve_invocation(run, req)
                run.attempts = inv.attempt
                Run.objects.filter(pk=run.id, fence=run.fence).update(
                    attempts=inv.attempt, status="generating", stage="repairing" if findings else "generating"
                )
        except DomainError as exc:
            finish_run(run.id, run.fence, "needs_attention", exc.message, error=error_data(exc))
            return
        if lease.cancelled():
            settle_invocation(inv.id, error={"code": "cancelled", "message": "Отменено до отправки."})
            return
        inv.state = "sent"
        inv.sent_at = timezone.now()
        inv.save(update_fields=["state", "sent_at"])
        event(
            run,
            "repairing" if findings else "generating",
            "Точечно исправляем найденные проблемы."
            if findings
            else "Модель создаёт код и короткие проверки игры.",
        )

        def progress(data):
            if lease.cancelled() or not isinstance(data, dict):
                return
            if (data.get("kind") or data.get("type")) == "first_output":
                run.refresh_from_db(fields=["metrics"])
                run.metrics = {**run.metrics, "first_output_seconds": time.monotonic() - model_started}
                Run.objects.filter(pk=run.id, fence=run.fence).update(metrics=run.metrics)
            event(
                run,
                str(data.get("kind") or data.get("type") or "model")[:40],
                str(data.get("message", "Модель готовит ответ."))[:500],
                {k: v for k, v in data.items() if k in ("input_tokens", "output_tokens", "elapsed_seconds")},
            )

        model_started = time.monotonic()
        try:
            result = generate(req, on_event=progress, is_cancelled=lease.cancelled)
            provider_metadata = dict(result.get("provider_metadata") or {})
            provider_metadata["execution_id"] = result.get("invocation_id", "")
            settle_invocation(
                inv.id,
                response=result["response"],
                usage=result.get("usage"),
                elapsed=result.get("elapsed_seconds", 0),
                provider_id=provider_metadata.get("turn_id") or provider_metadata.get("request_id") or "",
                provider_metadata=provider_metadata,
            )
        except Exception as exc:
            data = error_data(exc)
            raw = getattr(exc, "raw_response", None)
            if raw is not None:
                data["raw_response"] = raw
            provider_metadata = getattr(exc, "provider_metadata", None) or {}
            inv = settle_invocation(
                inv.id,
                usage=getattr(exc, "usage", None),
                error=data,
                unknown=getattr(exc, "outcome_unknown", True),
                elapsed=time.monotonic() - model_started,
                provider_id=provider_metadata.get("turn_id") or provider_metadata.get("request_id") or "",
                provider_metadata=provider_metadata,
            )
            if lease.cancelled():
                return
            if inv.state == "unknown":
                finish_run(
                    run.id,
                    run.fence,
                    "unknown",
                    "Связь с моделью оборвалась. Игра сохранена; новый запрос требует отдельного подтверждения расхода.",
                    error=error_data(exc),
                )
                return
            if (isinstance(exc, ContractError) or data["code"] == "invalid_json") and run.attempts < 2:
                findings = [error_data(exc)]
                continue
            finish_run(run.id, run.fence, "failed", data["message"], error=error_data(exc))
            return
        # Next loop consumes the durable response before doing any further work.
