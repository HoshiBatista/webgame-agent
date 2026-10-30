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

from generation.service import DURABLE_PROVIDERS, PROVIDERS

from .continuations import returned_response
from .feedback_tasks import dispatch_feedback_jobs, process_feedback  # noqa: F401 -- register Celery task
from .models import Budget, Chat, Invocation, Outbox, Revision, Run
from .services import (
    DomainError,
    event,
    fingerprint,
    finish_run,
    reserve_invocation,
    settle_invocation,
)
from .validation_tasks import dispatch_validations, process_validation  # noqa: F401 -- register Celery task


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
    dispatch_feedback_jobs()
    dispatch_validations()


@shared_task(acks_late=False)
def recover_expired():
    # Requests abandoned during cancellation still retain a liability, never an active reservation forever.
    abandoned = Invocation.objects.filter(
        state__in=["reserved", "sent"], run__status="cancelled"
    ).filter(Q(run__lease_until__lt=timezone.now()) | Q(run__lease_until__isnull=True)).exclude(run__provider__in=DURABLE_PROVIDERS)
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
            if unresolved.exists() and run.provider not in DURABLE_PROVIDERS:
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
                # Unsent reservations, returned responses and candidates are durable.
                # A direct provider is unsafe to retry only after the send marker.
                run.status = "queued"
                run.message = "Восстанавливаем сохранённый шаг после перезапуска."
                Outbox.objects.update_or_create(run=run, defaults={"dispatched_at": None})
                event(run, "recovered", run.message)
            run.fence = None
            run.lease_until = None
            run.save()


@shared_task(acks_late=False)
def reconcile_relay_cancellations():
    """Durable cancellation intent survives lost connections and stopped application workers."""
    from generation.errors import GenerationError, GenerationPending

    rows = Invocation.objects.filter(
        run__provider__in=DURABLE_PROVIDERS, run__status="cancelled", state__in=["reserved", "sent"]
    ).filter(
        (Q(run__provider="relay") & (
            Q(provider_metadata__relay_cancel_wait__retry_at__isnull=True)
            | Q(provider_metadata__relay_cancel_wait__retry_at__lte=time.time())
            | Q(provider_metadata__relay_cancel_wait__operator_required=False)))
        | (Q(run__provider="codex_api") & (
            Q(provider_metadata__codex_api_cancel_wait__retry_at__isnull=True)
            | Q(provider_metadata__codex_api_cancel_wait__retry_at__lte=time.time())
            | Q(provider_metadata__codex_api_cancel_wait__operator_required=False)))
    ).select_related("run").order_by("created_at")[:20]
    for inv in rows:
        wait = (inv.provider_metadata or {}).get(inv.run.provider + "_cancel_wait", {})
        if wait.get("operator_required") and wait.get("retry_at", 0) > time.time():
            continue
        try:
            provider = PROVIDERS[inv.run.provider]
            result = provider.unpack(provider.fetch(inv.request, cancel=True), str(inv.id))
            settle_invocation(inv.id, response=result["response"], raw_response=result.get("raw_response"),
                              usage=result.get("usage"),
                              provider_metadata=result.get("provider_metadata"))
        except GenerationPending as exc:
            record_relay_pending(inv, exc, cancel=True)
            continue
        except GenerationError as exc:
            data = error_data(exc)
            if exc.raw_response is not None:
                data["raw_response"] = exc.raw_response
            settle_invocation(inv.id, error=data, usage=exc.usage, unknown=exc.outcome_unknown,
                              provider_metadata=exc.provider_metadata)


@transaction.atomic
def record_relay_pending(inv, pending, *, cancel=False):
    inv = Invocation.objects.select_for_update().get(pk=inv.pk)
    if inv.state not in {"reserved", "sent"}:
        return
    prefix = inv.run.provider
    key = prefix + ("_cancel_wait" if cancel else "_wait")
    previous = (inv.provider_metadata or {}).get(key, {})
    details = {"code": pending.code, "operator_required": pending.operator_required,
               "retry_after": pending.retry_after, **pending.metadata,
               "checked_at": timezone.now().isoformat(), "retry_at": time.time() + pending.retry_after,
               "checks": previous.get("checks", 0) + 1}
    inv.provider_metadata = {**(inv.provider_metadata or {}), prefix + "_job_id": str(inv.id),
                             key: details}
    inv.save(update_fields=["provider_metadata"])
    if pending.operator_required and previous.get("code") != pending.code:
        logging.getLogger(__name__).warning("relay_operator_required job=%s code=%s http_status=%s",
                                           inv.id, pending.code, pending.metadata.get("http_status"))


@transaction.atomic
def defer_relay(run, message, pending=None):
    current = Run.objects.select_for_update().get(pk=run.id)
    if current.fence != run.fence or current.cancel_requested or current.status == "cancelled":
        return
    changed = current.message != message
    stage = "waiting_admin" if pending and pending.operator_required else "waiting_model"
    current.status, current.stage, current.message = "queued", stage, message
    current.error = ({"code": pending.code, "message": message, "operator_required": True}
                     if pending and pending.operator_required else {})
    current.fence, current.lease_until = None, None
    current.save()
    # Keep the durable outbox; configuration errors wait five minutes, not five seconds.
    Outbox.objects.update_or_create(
        run=current, defaults={"dispatched_at": timezone.now() + timedelta(
            seconds=(pending.retry_after if pending else 5) - 15)}
    )
    if changed:
        event(current, stage, message, current.error)


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
    from .capacity import capacity_full

    resuming_relay = run.provider in DURABLE_PROVIDERS and run.invocations.filter(
        state__in=["reserved", "sent"]
    ).exists()
    # Receiving an admitted job must not deadlock when capacity is reduced.
    # Any subsequent NEW invocation passes admission again in reserve_invocation.
    if not resuming_relay and capacity_full(run):
        if run.stage != 'waiting_capacity':
            run.stage = 'waiting_capacity'
            run.message = 'Все места для генерации заняты. Запрос сохранён и начнётся, когда освободится место.'
            run.save(update_fields=['stage', 'message', 'updated_at'])
            event(run, 'waiting_capacity', run.message)
        return False
    run.fence = uuid.uuid4()
    run.lease_until = timezone.now() + timedelta(seconds=settings.GAMEFORGE_LEASE_SECONDS)
    run.status = "generating"
    if not resuming_relay:
        run.stage = "generating"
        run.message = (
            "Создаём компактную игру, затем проверим её по шагам."
            if run.operation == "create"
            else "Готовим точечные изменения сохранённой игры."
        )
        run.metrics = {**run.metrics, "queue_seconds": (timezone.now() - run.created_at).total_seconds()}
    if not run.allow_model_calls:
        run.status = run.stage = "checking"
        run.message = "Проверяем сохранённый ответ без нового вызова модели."
    run.save()
    if not resuming_relay:
        event(run, run.stage, run.message)
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
    chat = Chat.objects.select_for_update().get(pk=run.chat_id)
    current = Run.objects.select_for_update().get(pk=run.id)
    if current.fence != run.fence or current.cancel_requested:
        return None
    number = (Revision.objects.filter(chat_id=run.chat_id).aggregate(n=Max("number"))["n"] or 0) + 1
    from generation.helpers import used

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
        checks_review_required=bool(materialized.get("checks_review_required") or base and base.checks_review_required),
        generation_profile=materialized.get("generation_profile", run.generation_profile),
        compact_manifest=materialized.get("compact_manifest", {}),
        runtime_version=materialized.get("runtime_version", 0),
        helper_manifest=used(materialized["files"]),
        pipeline_version=run.pipeline_version,
        requirement_manifest=run.requirement_manifest,
    )
    if not chat.title_is_custom and chat.current_revision_id is None:
        from .titles import short_game_title

        chat.title = short_game_title(revision.title)
        chat.save(update_fields=["title", "updated_at"])
    current.candidate_revision = revision
    current.status = "checking"
    current.stage = "checking"
    current.message = "Проверяем синтаксис, затем управление и игровые условия."
    current.save()
    event(current, "checking", current.message)
    return revision


def request_for(run, base, findings, last_attempt_error=None):
    import hashlib

    from generation.errors import ContractError
    from generation.feedback import focus_findings
    from generation.presentation import VERSION as PRESENTATION_VERSION
    from generation.prompts import repair_evidence, system_prompt
    from generation.schema import CONTRACT_VERSION, response_schema, validate_checks

    from .check_repair import attempted, needs_repair

    version = run.pipeline_version
    if version != CONTRACT_VERSION:
        raise DomainError("unsupported_game", "Старый игровой формат больше не поддерживается. Создайте новую игру.", 409)
    from generation.requirements import policy_snapshot

    if run.policy_snapshot != policy_snapshot():
        raise DomainError("generation_policy_changed", "Правила генерации обновились. Сохранённый ответ доступен; для новых вызовов нужен новый запрос.", 409)
    focused_error = focus_findings([last_attempt_error]) if last_attempt_error else []
    request = {
        # A rejected response has not established new game requirements yet.
        # Only a materialized candidate becomes the fixed base of a repair.
        "operation": "create" if base is None else "edit" if (
            base.id == run.source_revision_id and not run.candidate_revision_id
        ) else "repair",
        "prompt": run.prompt,
        "game_request": run.game_request,
        "generation_profile": run.generation_profile,
        "source_format": run.source_format,
        "compact_manifest": base.compact_manifest if base else {},
        "audience": run.audience,
        "preferences": run.preferences_snapshot,
        "helper_catalog": run.helper_catalog,
        "requirement_manifest": run.requirement_manifest,
        "base_revision": str(base.id) if base else None,
        "artifact_hash": base.artifact_hash if base else None,
        "files": base.files if base else {},
        "design": base.design if base else {},
        "checks": base.checks if base else [],
        "findings": focus_findings(findings or ([last_attempt_error] if last_attempt_error else [])),
        "unresolved_findings": findings,
        "last_attempt_error": focused_error[0] if focused_error else None,
        "provider": run.provider,
        "model": run.model,
        "generation_strategy": run.generation_strategy,
        "presentation_policy": PRESENTATION_VERSION if run.generation_strategy == "pro" else 0,
        "game_plan": run.game_plan,
        "generation_contract": {"pipeline_version": version},
    }
    from generation.lite import VERSION as LITE_POLICY_VERSION
    from generation.lite import eligible as lite_eligible

    if lite_eligible(request):
        request['lite_policy'] = LITE_POLICY_VERSION
        from generation.experience import PATH, RECIPE
        from generation.music import MARKER

        from .lite_music import due as music_due

        if music_due(run, base):
            request['operation'] = 'music'
        elif run.requirement_manifest.get(MARKER) and (base is None or RECIPE not in base.files):
            request['helper_catalog'] = {p: item for p, item in run.helper_catalog.items() if p != PATH}
    if run.planning_required and not run.game_plan and base is None:
        from generation.planning import PROVENANCE_VERSION

        request["operation"] = "plan"
        request['plan_provenance'] = PROVENANCE_VERSION
    if request["operation"] == "edit":
        from .patch_repair import pending_permission

        policy = pending_permission(run, base)
        if policy:
            request["patch_repair"] = policy
    from .checks_create import eligible as create_eligible
    from .checks_create import permission as create_permission

    if request["operation"] == "repair" and create_eligible(run, base):
        if attempted(run, base):
            raise DomainError("check_review_required", "Сценарии для этих исходников уже запрашивались. Повтор автоматически не отправляем.")
        request["operation"] = "checks_create"
        request["checks_create"] = create_permission(run, base)
    if request["operation"] == "repair" and needs_repair(run, base, findings):
        from generation.check_repair import permission

        from .check_repair import protected_ids

        if attempted(run, base):
            raise DomainError("check_review_required", "Проверки уже пересматривались для этих исходников. Код сохранён; нужен разбор результата.")
        try:
            from validation.suites import MAX_SAVED_CHECKS

            options = {'max_requirements': MAX_SAVED_CHECKS} if request.get('lite_policy') else {}
            request["check_repair"] = permission(base.artifact_hash, base.checks, base.design, run.requirement_manifest,
                                                  protected_ids=protected_ids(base), **options)
        except ContractError as exc:
            raise DomainError(exc.code, exc.message) from exc
        request["operation"] = "check_repair"
    if request["operation"] == "repair":
        from .check_repair import code_repair_basis

        try:
            validate_checks(base.checks)
        except ContractError as exc:
            basis = code_repair_basis(run, base)
            if basis is None:
                raise DomainError(
                    "invalid_baseline_checks",
                    "Сохранённые проверки требуют проверки приложения. Автоматическое исправление остановлено.",
                ) from exc
            request["code_repair_basis"] = basis
        if version >= 5 and not base.accepted:
            from generation.source_policy import module_policy

            policy = module_policy(
                base.files, findings,
                allowed_paths={"game.js"} if run.generation_profile == "compact" else None,
            )
            # A cosmetic edit must not authorize replacement of untouched working code.
            edit_source = run.source_revision or run.base_revision
            if edit_source:
                policy["files"] = {p: h for p, h in policy["files"].items()
                                   if base.files[p] != edit_source.files.get(p)}
            request["module_repair"] = policy
    if base is not None and findings:
        report = base.reports.order_by("-id").first()
        if report and report.findings == findings and report.status in {"failed", "unverified"}:
            request["validation_evidence"] = repair_evidence({"status": report.status, "facts": report.facts})
            if run.generation_strategy == "pro" and report.identity == check_identity(base, report.environment):
                request["validation_evidence"]["report_id"] = report.id
                request["validation_evidence"]["artifact_hash"] = base.artifact_hash
                request["validation_evidence"]["gates_passed"] = report.assessment.get("gates_passed")
                # Only a screenshot of this exact candidate is sent; no page/host access.
                if report.screenshot_mime in {"image/png", "image/jpeg"} and report.screenshot_base64:
                    request["preview_image"] = {
                        "mime": report.screenshot_mime, "data": report.screenshot_base64,
                        "artifact_hash": base.artifact_hash, "report_id": report.id,
                    }
                    from generation.feedback_image import image_input

                    if image_input(request) is None:
                        del request["preview_image"]
    if run.visual_state.get("phase") in {"review_due", "patch_due"}:
        from .visual import request_details

        try:
            request.update(request_details(run, base))
        except (ContractError, ValueError) as exc:
            raise DomainError("stale_visual_evidence", "Кадры больше не соответствуют проверенной версии.") from exc
        from generation.feedback_image import image_input

        if image_input(request) is None:
            raise DomainError("invalid_visual_image", "Нет допустимого изображения для оценки оформления.")
    if base is None and request['operation'] == 'create':
        from .response_completion import pending_permission

        completion = pending_permission(run, request)
        if completion:
            request['response_completion'] = completion
    request["reasoning_effort"] = (
        "high" if run.generation_strategy == "pro" and request["operation"] in {"plan", "create", "repair"}
        else "medium" if run.generation_strategy == "pro" else "low"
    )
    request["generation_contract"] = {
        "system_prompt_sha256": hashlib.sha256(system_prompt(request).encode()).hexdigest(),
        "response_schema_sha256": fingerprint(response_schema(request)),
        "pipeline_version": version,
        "max_repair_attempts": run.max_repair_attempts,
        "reported_findings": len(findings) or int(bool(last_attempt_error)),
        "focused_findings": len(request["findings"]),
    }

    if run.provider in {"vllm", "relay"}:
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


def check_identity(revision, environment=None):
    from generation.source_map import VERSION
    from validation import service
    from validation.checks import VERSION as CHECK_VERSION
    from validation.checks import review_checks
    from validation.contracts import implementation_hash

    environment = environment if environment is not None else service.environment_identity()
    checks, _ = review_checks(revision.checks)
    return fingerprint(
        {"artifact": revision.artifact_hash, "checks": checks, "validator": environment,
         "validator_code": implementation_hash(),
         "source_map": VERSION, "check_policy": CHECK_VERSION,
         "compact_manifest": revision.compact_manifest,
         "requirement_manifest": revision.requirement_manifest,
         "helpers": revision.helper_manifest,
         "checks_review_required": revision.checks_review_required}
    )


def repair_state(run, base):
    """Reports own game defects; a rejected invocation owns only its reply error."""
    report = base.reports.order_by("-id").first() if base else None
    findings = report.findings if report else []
    previous = run.invocations.order_by("-attempt").first()
    if previous is None and run.continued_from:
        previous = run.continued_from.invocations.order_by("-attempt").first()
    last_error = None
    if previous and not previous.revision_id and previous.error:
        base_id = str(base.id) if base else None
        if previous.request.get("base_revision") == base_id:
            last_error = {key: previous.error[key] for key in ("code", "message") if key in previous.error}
            if not report:
                findings = previous.request.get("unresolved_findings") or previous.request.get("findings") or []
    if base is None and not last_error:
        restart = run.events.filter(kind="source_restart").order_by("-id").first()
        if restart:
            last_error = restart.details["error"]
    return findings, last_error


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
            if run.provider in DURABLE_PROVIDERS and run.invocations.filter(state__in=["reserved", "sent"]).exists():
                defer_relay(run, "Восстанавливаем получение сохранённого ответа после ошибки обработчика.")
                return
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


@transaction.atomic
def mark_invocation_sent(run, inv):
    """Fence the durable send marker before any direct transport can be retried."""
    current = Run.objects.select_for_update(of=("self",)).select_related("chat").get(pk=run.id)
    if (current.fence != run.fence or current.cancel_requested or current.chat.deleted_at
            or current.status not in Run.ACTIVE):
        return False
    stored = Invocation.objects.select_for_update().get(pk=inv.id, run=current)
    if stored.state not in ({"reserved", "sent"} if run.provider in DURABLE_PROVIDERS else {"reserved"}):
        return False
    if stored.sent_at and run.provider not in DURABLE_PROVIDERS:
        return False
    if not stored.sent_at and current.model_call_deadline and timezone.now() >= current.model_call_deadline:
        return False
    stored.state, stored.sent_at = "sent", stored.sent_at or timezone.now()
    stored.save(update_fields=["state", "sent_at"])
    inv.state, inv.sent_at, inv.provider_metadata = stored.state, stored.sent_at, stored.provider_metadata
    return True


def _execute(run, lease, generate, materialize, validate):
    from generation.errors import ContractError, GenerationPending

    from .acceptance import best_failed_candidate, complete_requirements, repeated_failure

    base = run.candidate_revision or run.source_revision or run.base_revision
    findings, last_attempt_error = repair_state(run, base)
    # A continued infrastructure failure only needs validation, not another model call.
    pending = (
        run.candidate_revision
        if run.candidate_revision
        and (
            run.candidate_revision.run_id == run.id
            or not run.allow_model_calls
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
        if previous_report and previous_report.identity != check_identity(run.candidate_revision, previous_report.environment):
            # A validator fix invalidates evidence, not game code; recheck before another paid edit.
            pending = run.candidate_revision
        if run.completion_policy >= 2 and (
            previous_report is None or previous_report.assessment.get("action") != "repair"
        ):
            pending = run.candidate_revision
    if run.continued_from and not pending:
        previous = run.continued_from
        report = base.reports.order_by("-id").first() if base else None
        if report:
            findings = report.findings
        elif not last_attempt_error:
            last_attempt_error = previous.error or {"message": "Продолжить сохранённый запрос."}
    while not lease.cancelled():
        run.refresh_from_db()
        # Retrieval has priority over decisions based on the old candidate/report.
        # A re-entered worker must not treat an admitted check repair as exhausted.
        resumed = run.invocations.filter(state__in=["reserved", "sent"]).order_by("attempt").first()
        if resumed and resumed.sent_at and run.provider not in DURABLE_PROVIDERS:
            # Direct transports cannot reconcile a submitted inference by UUID.
            settle_invocation(resumed.id, unknown=True, error={
                "code": "receipt_storage_failed", "message": "Результат отправленного вызова неизвестен.",
            })
            finish_run(run.id, run.fence, "unknown", "Нужна сверка исхода отправленного вызова.",
                       error={"code": "receipt_storage_failed", "message": "Повтор требует подтверждения."})
            return
        inv = returned_response(run, base)
        if inv is None:
            stale = run.invocations.filter(state="returned", revision__isnull=True).first()
            if stale is not None:
                # Accounted receipt, but its original base is no longer applicable.
                stale.state = "settled"
                stale.error = {"code": "stale_revision", "message": "База сохранённого ответа изменилась."}
                stale.save(update_fields=["state", "error"])
        if inv is not None:
            # Exact request base is durable: recovery cannot apply a saved patch to a later draft.
            base_id = inv.request.get("base_revision")
            response_base = Revision.objects.filter(pk=base_id).first() if base_id else None
            response = inv.response
            if inv.request['operation'] == 'music':
                from generation.music import materialize as materialize_music

                with transaction.atomic():
                    try:
                        artifact = materialize_music(response, inv.request, response_base)
                        pending = store_candidate(run, artifact, response_base)
                        inv.revision = pending
                    except ContractError as exc:
                        inv.error = error_data(exc)
                        pending = response_base
                        event(run, 'music_failed', 'Не удалось добавить музыку. Созданная игра сохранена.')
                    inv.state = 'settled'
                    inv.save(update_fields=['state', 'revision', 'error'])
                if pending is None:
                    return
                base = pending
                last_attempt_error = None
                continue
            if inv.request["operation"] == "plan":
                from generation.planning import validate_plan
                from generation.schema import response_schema, validate_response

                try:
                    validate_response(response, operation="plan", schema=response_schema(inv.request))
                    validate_plan(response, inv.request)
                except ContractError as exc:
                    inv.state, inv.error = "settled", error_data(exc)
                    inv.save(update_fields=["state", "error"])
                    finish_run(run.id, run.fence, "needs_attention", exc.message, error=error_data(exc))
                    return
            if inv.request["operation"] == "visual_review":
                from .visual import accept_review, skip

                with transaction.atomic():
                    try:
                        accept_review(run, response_base, response, inv.request)
                    except (ContractError, ValueError) as exc:
                        skip(run, "invalid_visual_review")
                        inv.error = error_data(exc)
                    inv.state = "settled"
                    inv.save(update_fields=["state", "error"])
                base = pending = response_base
                continue
            if response.get("status") == "scope_refusal" and inv.request["operation"] != "visual_patch":
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
            if inv.request["operation"] == "plan":
                from generation.requirements import manifest

                with transaction.atomic():
                    current = Run.objects.select_for_update().get(pk=run.id)
                    if current.fence != run.fence or current.cancel_requested or current.status not in Run.ACTIVE:
                        return
                    current.game_plan = response["plan"]
                    current.requirement_manifest = manifest(current.game_request, response["plan"])
                    current.stage = "generating"
                    current.save(update_fields=["game_plan", "requirement_manifest", "stage", "updated_at"])
                    inv.state = "settled"
                    inv.save(update_fields=["state"])
                    event(current, "planned", "Замысел игры сохранён. Переходим к реализации.")
                last_attempt_error = None
                continue
            try:
                if inv.request.get("code_repair_basis"):
                    from .check_repair import code_repair_basis

                    if response_base is None or code_repair_basis(run, response_base) != inv.request["code_repair_basis"]:
                        raise ContractError("stale_code_repair_basis", "Свидетельство для ремонта кода изменилось; нужна повторная проверка.")
                if inv.request.get("checks_create"):
                    from .checks_create import permission as create_permission

                    try:
                        current_permission = create_permission(run, response_base)
                    except DomainError as exc:
                        raise ContractError("stale_checks_create", exc.message) from exc
                    if current_permission != inv.request["checks_create"]:
                        raise ContractError("stale_checks_create", "Свидетельство для составления сценариев изменилось.")
                if inv.request["operation"] == "visual_patch":
                    from .visual import request_details

                    try:
                        current_visual = request_details(run, response_base)
                    except (ContractError, ValueError) as exc:
                        raise ContractError("stale_visual_evidence", "Пакет кадров устарел.") from exc
                    if current_visual.get("visual_patch") != inv.request["visual_patch"]:
                        raise ContractError("stale_visual_evidence", "Разрешение визуальной правки изменилось.")
                packaging_started = time.monotonic()
                artifact = materialize(
                    response,
                    operation=inv.request["operation"],
                    base_revision=str(response_base.id) if response_base else None,
                    files=response_base.files if response_base else None,
                    previous_checks=response_base.checks if response_base else None,
                    generation_contract={**inv.request.get("generation_contract", {}),
                                         "pipeline_version": inv.request.get("generation_contract", {}).get("pipeline_version", 2)},
                    module_repair=inv.request.get("module_repair") if response_base and not response_base.accepted else None,
                    check_repair=inv.request.get("check_repair"),
                    patch_repair=inv.request.get("patch_repair"),
                    checks_create=inv.request.get("checks_create"),
                    generation_strategy=inv.request.get("generation_strategy", "lite"),
                    requirement_manifest=inv.request.get("requirement_manifest"),
                    helper_catalog=inv.request.get("helper_catalog"),
                    visual_patch=inv.request.get("visual_patch"),
                    code_repair_basis=inv.request.get("code_repair_basis"),
                    generation_profile=inv.request.get("generation_profile", "full"),
                    compact_manifest=inv.request.get("compact_manifest"),
                    source_format=inv.request.get("source_format", "string"),
                )
                if inv.request.get("generation_profile") == "compact" and response_base:
                    artifact.update(title=response_base.title, design={**response_base.design,
                        **({'assets': artifact['design']['assets']} if artifact.get('design', {}).get('assets') else {})})
                if (inv.request["operation"] in {"check_repair", "checks_create", "visual_patch"} or inv.request.get("code_repair_basis")) and artifact.get("status") != "unchanged":
                    if response_base is None:
                        raise ContractError("missing_base", "Для ремонта нужна сохранённая версия игры.")
                    artifact.update(title=response_base.title, design=response_base.design)
                run.metrics = {
                    **run.metrics,
                    "packaging_seconds": run.metrics.get("packaging_seconds", 0)
                    + time.monotonic()
                    - packaging_started,
                }
                Run.objects.filter(pk=run.id, fence=run.fence).update(metrics=run.metrics)
                if artifact.get("status") == "unchanged" and inv.request["operation"] == "visual_patch":
                    from .visual import skip

                    skip(run, "visual_patch_declined")
                    inv.state = "settled"
                    inv.save(update_fields=["state"])
                    pending = base = response_base
                    continue
                if artifact.get("status") == "unchanged":
                    explanation = artifact["message"]
                    previous_report = response_base.reports.order_by("-id").first() if response_base else None
                    manual = bool(inv.request["operation"] in {"check_repair", "checks_create"} and response_base and previous_report
                                  and previous_report.status == "unverified"
                                  and previous_report.assessment.get("action") == "review"
                                  and complete_requirements(response_base.checks)
                                  and previous_report.assessment.get("gates_passed") is True
                                  and not previous_report.assessment.get("requirement_coverage", {}).get("uncovered"))
                    with transaction.atomic():
                        inv.state = "settled"
                        inv.save(update_fields=["state"])
                        if finish_run(
                            run.id,
                            run.fence,
                            "unverified" if manual else "needs_attention",
                            f"Исходники сохранены; проверьте игровые условия вручную. {explanation}" if manual else
                            f"Изменения не внесены. {explanation}",
                            error={"code": "manual_verification" if manual else "unchanged", "message": explanation},
                        ):
                            inv.state = "settled"
                            inv.save(update_fields=["state"])
                    return
                with transaction.atomic():
                    pending = store_candidate(run, artifact, response_base)
                    inv.revision = pending
                    if pending and inv.request["operation"] == "visual_patch":
                        from .visual import save_state

                        save_state(run, phase="patched", patched_revision=str(pending.id))
                    inv.state = "settled"
                    inv.save(update_fields=["revision", "state"])
                if pending is None:
                    return
                base = pending
                last_attempt_error = None
            except ContractError as exc:
                inv.state = "settled"
                inv.error = error_data(exc)
                inv.save(update_fields=["state", "error"])
                if inv.request.get('response_completion'):
                    finish_run(run.id, run.fence, 'needs_attention', exc.message,
                               error={'code': 'invalid_response_completion', 'message': exc.message,
                                      'cause': exc.code})
                    return
                if inv.request["operation"] == "visual_patch":
                    from .visual import skip

                    skip(run, "invalid_visual_patch")
                    pending = base = response_base
                    continue
                last_attempt_error = error_data(exc)
                pending = None
                event(
                    run,
                    "incomplete_sources" if exc.code == "incomplete_sources" else "contract_error",
                    "Ответ сохранён, но исходники неполны; продолжаем создание в общем лимите."
                    if exc.code == "incomplete_sources" and base is None else
                    "Ответ сохранён; исправляем проблему формата, изменений или проверок.",
                    {"code": last_attempt_error["code"]},
                )
                if inv.request["operation"] in {"check_repair", "checks_create"} or exc.code in {"test_only_change", "invalid_baseline_checks", "stale_code_repair_basis"}:
                    finish_run(run.id, run.fence, "needs_attention", exc.message,
                               error={**last_attempt_error, "details": findings})
                    return
        if pending is not None and resumed is None:
            from .lite_music import due as music_due

            if music_due(run, pending):
                base, pending = pending, None
                continue
            from generation.schema import CONTRACT_VERSION

            if pending.pipeline_version != CONTRACT_VERSION:
                finish_run(run.id, run.fence, "needs_attention", "Старый игровой формат больше не поддерживается.",
                           error={"code":"unsupported_game", "message":"Создайте новую игру."})
                return
            from .validation_tasks import automatic_validation

            Run.objects.filter(pk=run.id, fence=run.fence, status__in=Run.ACTIVE).update(
                status='checking', stage='checking', message='Проверяем сохранённую версию игры.')
            report = automatic_validation(run, pending, validate=validate, cancelled=lease.cancelled)
            if report is None:
                if not lease.cancelled():
                    finish_run(run.id, run.fence, "failed", "Проверка прервалась. Игра сохранена; можно проверить её заново.",
                               error={"code": "validator_unavailable", "message": "Среда проверки недоступна."})
                return
            checks = report.checks
            if lease.cancelled():
                return
            visual_patch_valid = report.status == "passed"
            if run.visual_state.get("phase") == "patched" and visual_patch_valid:
                from generation.visual import contact_sheet

                try:
                    contact_sheet(report.visual_evidence, artifact_hash=pending.artifact_hash, environment=report.environment)
                except Exception:
                    visual_patch_valid = False
            if run.visual_state.get("phase") == "patched" and not visual_patch_valid:
                from .visual import fallback, save_state

                original = fallback(run)
                if original is not None:
                    save_state(run, phase="reverted", reason="visual_patch_regression")
                    Run.objects.filter(pk=run.id, fence=run.fence).update(candidate_revision=original)
                    base = pending = original
                    continue
            if report.status == "passed":
                from .visual import next_step

                if next_step(run, pending, report):
                    findings, base, pending = [], pending, None
                    continue
                finish_run(
                    run.id,
                    run.fence,
                    "succeeded",
                    "Игра готова. Управление и основные игровые условия проверены.",
                    revision=pending,
                )
                return
            decision = report.assessment.get("action")
            from .check_repair import can_repair
            from .checks_create import can_create

            if can_create(run, pending) or can_repair(run, pending, report.findings):
                findings, base, pending = report.findings, pending, None
                continue
            if run.completion_policy >= 2 and decision == "recheck":
                finish_run(
                    run.id, run.fence, "failed",
                    "Игра сохранена. Среда не смогла завершить проверку; повторите проверку без генерации.",
                    error={"code": "validator_unavailable", "message": "Проверка не завершена.",
                           "details": report.findings},
                )
                return
            if report.status == "unverified" and decision != "repair" and (
                run.completion_policy >= 2 or run.attempts >= run.max_model_calls or not run.allow_model_calls
            ):
                manual = run.completion_policy < 2 or (
                    report.assessment.get("gates_passed") is True and complete_requirements(checks)
                    and not report.assessment.get("requirement_coverage", {}).get("uncovered")
                )
                finish_run(
                    run.id,
                    run.fence,
                    "unverified" if manual else "needs_attention",
                    ("Проверки исправлены, код игры сохранён. Проверьте игровые условия и подтвердите результат."
                     if pending.checks_review_required else
                     "Игра сохранена. Проверьте отмеченные условия в preview и подтвердите результат.")
                    if manual else "Игра сохранена. Не удалось подтвердить обязательные проверки; повторите проверку.",
                    error={
                        "code": "manual_verification" if manual else "check_review_required",
                        "message": "Автоматически подтверждены не все условия.",
                        "details": report.findings,
                    },
                )
                return
            if run.completion_policy >= 2 and report.status == "failed":
                best = best_failed_candidate(run, report)
                if best.id != pending.id:
                    Run.objects.filter(pk=run.id, fence=run.fence, cancel_requested=False).update(candidate_revision=best)
                    finish_run(
                        run.id, run.fence, "needs_attention",
                        "Исправление ухудшило проверенное поведение. Сохранён предыдущий кандидат.",
                        error={"code": "repair_regression", "message": "Исправление добавило регрессию.",
                               "details": report.findings},
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
            if run.completion_policy >= 2 and repeated_failure(run, report):
                best = best_failed_candidate(run, report)
                Run.objects.filter(pk=run.id, fence=run.fence, cancel_requested=False).update(candidate_revision=best)
                finish_run(
                    run.id, run.fence, "needs_attention",
                    "Исправление повторило ту же проблему. Сохранён кандидат; дальнейший одинаковый ремонт остановлен.",
                    error={"code": "no_progress", "message": "Повторное исправление не дало прогресса.",
                           "details": report.findings},
                )
                return
            findings = report.findings
            base = pending
            pending = None
        run.refresh_from_db()
        if not run.allow_model_calls and resumed is None:
            finish_run(
                run.id, run.fence, "needs_attention",
                "Ответ восстановлен без новой генерации. В игре или проверках остались проблемы; черновик сохранён.",
                error={"code": "saved_response_validation", "message": "Требуется проверка восстановленной игры.",
                       "details": findings},
            )
            return
        resumed = run.invocations.filter(state__in=["reserved", "sent"]).order_by("attempt").first()
        if run.attempts >= run.max_model_calls and resumed is None:
            incomplete = base is None and (last_attempt_error or {}).get("code") == "incomplete_sources"
            output_limited = base is None and (last_attempt_error or {}).get('code') == 'response_output_limit'
            plan_only = base is None and bool(run.game_plan)
            finish_run(
                run.id,
                run.fence,
                "needs_attention",
                "Лимит вызовов исчерпан. Замысел сохранён, создание игры ещё не завершено."
                if plan_only else
                "Лимит вызовов исчерпан: модель не передала полную реализацию игры. Ответы сохранены; можно продолжить создание."
                if incomplete else "Лимит исправлений исчерпан. Ответы и черновик сохранены; доступно продолжение.",
                error={
                    "code": "response_output_limit" if output_limited else "incomplete_sources" if incomplete else "plan_without_game" if plan_only else "repair_exhausted",
                    "message": "Не получена полная реализация игры." if incomplete else "Остались проблемы применения или проверки.",
                    "details": findings or ([last_attempt_error] if last_attempt_error else []),
                    "max_repair_attempts": run.max_repair_attempts,
                    "last_attempt_error": last_attempt_error,
                },
            )
            return
        try:
            if resumed:
                inv = resumed
            else:
                req = request_for(run, base, findings, last_attempt_error)
                with transaction.atomic():
                    inv = reserve_invocation(run, req)
                    run.attempts = inv.attempt
                    Run.objects.filter(pk=run.id, fence=run.fence).update(
                        attempts=inv.attempt, status="generating",
                        stage="music" if req["operation"] == "music" else "planning" if req["operation"] == "plan" else
                        "repairing_checks" if req["operation"] in {"check_repair", "checks_create"} else "repairing" if findings else "generating"
                    )
            req = inv.request
        except DomainError as exc:
            if exc.code == "provider_busy":
                defer_relay(run, exc.message)
                return
            if run.visual_state.get("phase") in {"review_due", "patch_due"}:
                from .visual import fallback, skip

                skip(run, exc.code)
                pending = base = fallback(run) or base
                continue
            finish_run(run.id, run.fence, "needs_attention", exc.message, error=error_data(exc))
            return
        if lease.cancelled():
            if not inv.sent_at:
                settle_invocation(inv.id, unsent_fence=run.fence,
                                  error={"code": "cancelled", "message": "Отменено до отправки."})
            return
        from generation.requirements import policy_snapshot

        if not inv.sent_at and run.policy_snapshot != policy_snapshot():
            stopped = settle_invocation(inv.id, unsent_fence=run.fence,
                error={"code":"generation_policy_changed", "message":"Не отправлено: правила генерации обновились."})
            if stopped.state != "failed" or stopped.sent_at is not None:
                continue
            finish_run(run.id, run.fence, "needs_attention", "Правила генерации обновились; нужен новый запрос.",
                       error={"code":"generation_policy_changed", "message":"Новый вызов не отправлен."})
            return
        if not inv.sent_at and run.model_call_deadline and timezone.now() >= run.model_call_deadline:
            stopped = settle_invocation(inv.id, unsent_fence=run.fence,
                                        error={"code": "model_deadline", "message": "Не отправлено: время вызовов истекло."})
            if stopped.state != "failed" or stopped.sent_at is not None:
                continue
            if req["operation"] in {"visual_review", "visual_patch"}:
                from .visual import fallback, skip

                skip(run, "model_deadline")
                pending = base = fallback(run) or base
                continue
            finish_run(run.id, run.fence, "needs_attention", "Время новых модельных вызовов истекло. Кандидат сохранён.",
                       error={"code": "model_deadline", "message": "Лимит времени вызовов исчерпан."})
            return
        if not mark_invocation_sent(run, inv):
            continue
        if run.provider == "vllm":
            # Persist correlation before the network call, even if the worker later dies.
            req = {**req, "transport_trace_id": inv.id.hex}
            inv.provider_metadata = {**inv.provider_metadata, "trace_id": inv.id.hex}
            inv.save(update_fields=["provider_metadata"])
        if not resumed:
            message = (
                "Создаём музыку для игры."
                if req['operation'] == 'music' else
                "Завершаем недостающую часть игры. Уже полученные части сохранены."
                if req.get('response_completion') else
                "Придумываем игровой замысел: механику, развитие и цель."
                if req["operation"] == "plan" else
                "Уточняем сценарии проверки сохранённой игры. Исходники остаются прежними."
                if req["operation"] in {"check_repair", "checks_create"} else
                "Исправляем сохранённую игру по результатам проверки."
                if req["operation"] == "repair" else
                "Дорабатываем сохранённую игру по результатам проверки."
                if findings else "Создаём игровую механику и короткие сценарии проверки."
            )
            Run.objects.filter(pk=run.id, fence=run.fence).update(message=message)
            event(
                run,
                "planning" if req["operation"] == "plan" else "repairing" if findings else "generating",
                message,
                {"attempt": inv.attempt, "max_model_calls": run.max_model_calls},
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
                raw_response=result.get("raw_response"),
                usage=result.get("usage"),
                elapsed=(timezone.now() - inv.sent_at).total_seconds() if run.provider in DURABLE_PROVIDERS
                else result.get("elapsed_seconds", 0),
                provider_id=provider_metadata.get("turn_id") or provider_metadata.get("request_id") or "",
                provider_metadata=provider_metadata,
            )
        except GenerationPending as exc:
            record_relay_pending(inv, exc)
            defer_relay(run, exc.message, exc)
            return
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
                elapsed=(timezone.now() - inv.sent_at).total_seconds() if run.provider in DURABLE_PROVIDERS
                else time.monotonic() - model_started,
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
                    "Результат вызова модели неизвестен. Доступные данные сохранены; повтор требует подтверждения.",
                    error=error_data(exc),
                )
                return
            if req['operation'] == 'music':
                event(run, 'music_failed', 'Не удалось добавить музыку. Созданная игра сохранена.')
                pending = base
                last_attempt_error = None
                continue
            if req["operation"] in {"visual_review", "visual_patch"}:
                from .visual import fallback, skip

                skip(run, "visual_call_failed")
                pending = base = fallback(run) or base
                continue
            if req.get('response_completion'):
                finish_run(run.id, run.fence, 'failed', data['message'], error=error_data(exc))
                return
            if base is None and data['code'] == 'response_output_limit':
                from .response_completion import pending_permission

                if pending_permission(run, req):
                    last_attempt_error = error_data(exc)
                    continue
            if isinstance(exc, ContractError) or data["code"] == "invalid_json":
                if req["operation"] in {"check_repair", "checks_create"}:
                    finish_run(run.id, run.fence, "needs_attention", "Не удалось восстановить проверки. Код игры сохранён.",
                               error=error_data(exc))
                    return
                last_attempt_error = error_data(exc)
                continue
            finish_run(run.id, run.fence, "failed", data["message"], error=error_data(exc))
            return
        # Next loop consumes the durable response before doing any further work.


@shared_task(acks_late=False)
def refresh_codex_api_catalog():
    if settings.GAMEFORGE_PRO_PROVIDER != "codex_api":
        return
    from generation.providers.codex_api import refresh_catalog

    try:
        refresh_catalog()
    except Exception as exc:
        # No raw HTTP/provider errors: stale snapshots stop admitting new Pro runs.
        logging.getLogger(__name__).warning("codex_api_catalog_failed type=%s", type(exc).__name__)
