"""A bounded code-then-scenarios experiment; shares durable invocations and budgets."""
from generation.check_repair import permission as scenario_permission
from generation.requirements import digest

from .check_repair import attempted


def eligible(run, base):
    if not (base and run.generation_strategy == 'lite_code_then_checks'
            and base.generation_profile == 'compact' and not base.accepted and not base.checks):
        return False
    from .tasks import check_identity

    report = base.reports.order_by('-id').first()
    return bool(report and report.identity == check_identity(base)
                and report.assessment.get('gates_passed') is True
                and report.assessment.get('action') == 'review')


def permission(run, base):
    from .services import DomainError

    if not eligible(run, base):
        raise DomainError('checks_create_unavailable', 'Сначала нужны обязательные проверки точной версии кода.')
    report = base.reports.order_by('-id').first()
    return {**scenario_permission(base.artifact_hash, base.checks, base.design, run.requirement_manifest),
            'base_revision': str(base.id), 'manifest_hash': digest(run.requirement_manifest),
            'report_id': report.id, 'report_identity': report.identity}


def can_create(run, base):
    return run.allow_model_calls and eligible(run, base) and not attempted(run, base)
