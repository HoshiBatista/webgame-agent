"""Coordinator verification of image receipts and explicit human acceptance."""

from prompt2play.contracts.models import digest
from prompt2play.generation.rendered_quality import validate_rendered


def rendered_ready(candidate, payload):
    if candidate.job.checkpoint.get("pipeline_version") != "adaptive-v1":
        return True
    from . import workflow
    from prompt2play.generation.coverage import validate_coverage

    reviews = payload.get("provenance", {}).get("visual_quality", {}).get("rendered_reviews", [])
    if not reviews:
        return False
    review = reviews[-1]
    if (
        review.get("status") != "rendered_ready"
        or review.get("source_sha256") != digest(payload["files"])
        or review.get("build_plan_sha256") != digest(payload["plan"])
    ):
        return False
    try:
        coverage = payload["provenance"]["requirement_reviews"][-1]
        requirements = payload["provenance"]["adaptive"]["requirements"]
        receipt = candidate.job.invocations.get(
            invocation_key=coverage["receipt"], operation="coverage_review", state="completed"
        )
        if (
            coverage["source_sha256"] != digest(payload["files"])
            or coverage["build_plan_sha256"] != digest(payload["plan"])
            or workflow.store().read_json(receipt.response_key)["data"] != coverage["review"]
            or validate_coverage(coverage["review"], requirements, payload["files"]) != "covered"
        ):
            return False
        frames = review["frames"]
        if not any(f["name"].endswith("-1280.png") for f in frames) or not any(
            f["name"].endswith("-390.png") for f in frames
        ):
            return False
        diagnostic = workflow.store().read_json(review["diagnostic_key"])
        if (
            diagnostic["files"] != payload["files"]
            or diagnostic["html"] != payload["html"]
            or diagnostic["spec"] != payload["spec"]
        ):
            return False
        evidence = {f["path"]: f for f in diagnostic["report"]["evidence_files"]}
        if any(
            f["sha256"] != evidence[f["name"]]["sha256"]
            or f["bytes"] != evidence[f["name"]]["bytes"]
            for f in frames
        ):
            return False
        receipt = candidate.job.invocations.get(
            invocation_key=review["receipt"], operation="rendered_review", state="completed"
        )
        data = workflow.store().read_json(receipt.response_key)["data"]
        if data != review["review"] or digest(data) != review["review_sha256"]:
            return False
        return validate_rendered(data, {f["name"] for f in frames}) == "rendered_ready"
    except (
        IndexError,
        KeyError,
        ValueError,
        TypeError,
        candidate.job.invocations.model.DoesNotExist,
    ):
        return False


def human_ready(candidate):
    receipt = candidate.job.review.get("visual_approval", {})
    return receipt.get("artifact_key") == candidate.artifact_key and bool(receipt.get("user_id"))
