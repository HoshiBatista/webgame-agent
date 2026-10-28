"""Select one source-preserving scenario repair within the ordinary Run budget."""

from django.db.models import Q

from generation.check_repair import needs_check_repair
from generation.errors import ContractError
from generation.schema import CONTRACT_VERSION, validate_checks

from .continuations import lineage_ids
from .models import Invocation


def contract_version(run):
    return run.pipeline_version


def needs_repair(run, base, findings):
    eligible = bool(
        base
        and not base.accepted
        and run.completion_policy >= 2
        and contract_version(run) == CONTRACT_VERSION
        and needs_check_repair(base.checks, findings)
    )
    if not eligible:
        return False
    report = base.reports.order_by("-id").first()
    surface_gap = repairable_surface_gap(base, report)
    if not (report and (
        report.assessment.get("gates_passed") is True or surface_gap
    )):
        return False
    try:
        validate_checks(base.checks)
    except ContractError:
        # An admitted complete source may still lack a complete scenario suite.
        return True
    report = base.reports.order_by("-id").first()
    # Do not infer an oracle problem from an incomplete infrastructure receipt.
    return bool(report and (report.assessment.get("gates_passed") is True or surface_gap))


def repairable_surface_gap(base, report):
    """A verified load with no observed scene permits scenario repair, never acceptance."""
    from validation.contracts import implementation_hash
    from validation.evidence import gates, valid

    from .tasks import check_identity

    if not report or report.status != "unverified" or not any(
        f.get("code") == "surface_not_observed" for f in report.findings
    ) or report.identity != check_identity(base, report.environment) or report.assessment.get("validator_hash") != implementation_hash():
        return False
    evidence = report.assessment.get("artifact_evidence")
    if not valid(evidence, base.artifact_hash, report.environment):
        return False
    observed = gates(evidence)
    return observed["syntax"] and observed["runtime"]


def attempted(run, base):
    return Invocation.objects.filter(
        run_id__in=list(lineage_ids(run)),
    ).filter(
        Q(request__operation="check_repair", request__check_repair__artifact_hash=base.artifact_hash)
        | Q(request__operation="checks_create", request__checks_create__artifact_hash=base.artifact_hash),
    ).exists()


def can_repair(run, base, findings):
    return run.allow_model_calls and needs_repair(run, base, findings) and not attempted(run, base)


def code_repair_basis(run, base):
    """Permission is derived from the latest trusted report, not model findings."""
    from generation.check_repair import checks_hash
    from validation.contracts import implementation_hash
    from validation.evidence import proven_defects, valid

    from .tasks import check_identity

    if base.accepted or contract_version(run) != CONTRACT_VERSION:
        return None
    report = base.reports.order_by("-id").first()
    if not report or report.identity != check_identity(base, report.environment) or (
        report.assessment.get("validator_hash") != implementation_hash()
    ):
        return None
    evidence = report.assessment.get("artifact_evidence")
    if not valid(evidence, base.artifact_hash, report.environment):
        return None
    defects = proven_defects(evidence) & {f.get("code") for f in report.findings}
    if not defects:
        return None
    return {"base_revision": str(base.id), "artifact_hash": base.artifact_hash,
            "checks_hash": checks_hash(base.checks), "report_id": report.id,
            "report_identity": report.identity, "defects": sorted(defects)}
