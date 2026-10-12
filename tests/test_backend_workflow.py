"""Authored validation fixtures establish coordinator policy, not browser results."""

import base64
import contextlib
import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from django.conf import settings
from django.db import close_old_connections, connection
from django.db.models.query import QuerySet
from django.test import Client, override_settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError

from prompt2play.adapters.artifacts.store import ArtifactStore
from prompt2play.adapters.django.forge import services as donor_services
from prompt2play.adapters.django.forge import workflow as django_workflow
from prompt2play.adapters.django.forge.authentication import secret_hash as donor_hash
from prompt2play.adapters.django.forge.errors import Conflict
from prompt2play.adapters.django.forge.models import (
    Candidate,
    Job,
    ModelInvocation,
    Project,
    Runner,
    User,
    Version,
)
from prompt2play.adapters.django.forge.preview import preview_url as donor_preview_url
from prompt2play.adapters.django.forge.representations import job_data as donor_job_data
from prompt2play.adapters.django.forge.serializers import JobCreateSerializer

services: Any = donor_services
workflow: Any = django_workflow
secret_hash = cast(Callable[[str], str], donor_hash)
preview_url: Any = donor_preview_url
job_data: Any = donor_job_data
Team = tuple[Any, Any, Any, Any]

pytestmark = pytest.mark.django_db
CAPABILITIES = {"providers": ["codex", "openai"], "continuable_planning_v1": True}


@pytest.fixture
def team(settings: Any, tmp_path: Path) -> Team:
    settings.ARTIFACT_ROOT = tmp_path / "artifacts"
    user = User.objects.create_user("fixture", password="irrelevant-test-password", is_staff=True)
    project = Project.objects.create(title="Fixture", prompt="Fixture request", created_by=user)
    generator = Runner.objects.create(
        name="generator", token_hash=secret_hash("generator-token"), role="generator"
    )
    validator = Runner.objects.create(
        name="validator", token_hash=secret_hash("validator-token"), role="validator"
    )
    return user, project, generator, validator


def job_for(team: Team, kind: str = "generate", **values: Any) -> tuple[Any, str]:
    user, project, generator, _ = team
    job = services.create_job(
        project,
        user,
        {"kind": kind, "prompt": "Fixture request", "provider": "codex", "model": "", **values},
    )
    claimed, lease = services.claim_job(generator, CAPABILITIES)
    assert claimed.pk == job.pk
    return claimed, lease


def submit(job: Any, lease: str, generator: Any, **values: Any) -> Any:
    return workflow.submit_candidate(
        job.pk,
        generator,
        {
            "lease_token": lease,
            "stage_fence": job.stage_fence,
            "idempotency_key": "candidate-1",
            "html": "<html>Authored fixture</html>",
            "files": {"game.js": "// authored fixture"},
            "spec": {"title": "fixture"},
            "plan": {},
            "provenance": {},
            **values,
        },
    )


def fixture_report(candidate: Any, status: str = "passed") -> tuple[dict[str, Any], dict[str, str]]:
    names = [
        f"{name}:{width}"
        for width in (1280, 390)
        for name in (
            "startup",
            "surface",
            "input",
            "completion",
            "restart",
            "javascript_errors",
            "external_requests",
            "evidence",
            "independent_acceptance",
        )
    ] + ["mobile_layout:390"]
    evidence = {
        f"fixture-{width}.txt": f"Authored {width} fixture, not browser evidence".encode()
        for width in (1280, 390)
    }
    report = {
        "schema_version": 2,
        "artifact": candidate.artifact,
        "status": status,
        "checks": [
            {
                "name": name,
                "status": "passed",
                "check_kind": "browser",
                "artifact_sha256": candidate.artifact["html_sha256"],
            }
            for name in names
        ],
        "errors": [],
        "warnings": [],
        "scope": {"isolated": True, "real_input": True, "webview": False},
        "suite_sha256": "f" * 64,
        "validator_image_sha256": "sha256:" + "e" * 64,
        "evidence_files": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in evidence.items()
        ],
    }
    return report, {name: base64.b64encode(data).decode() for name, data in evidence.items()}


def validate(
    team: Team,
    candidate: Any,
    status: str = "passed",
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    validator = team[3]
    job, lease = services.claim_job(validator, CAPABILITIES)
    assert job.active_candidate_id == candidate.pk
    report, evidence = fixture_report(candidate, status)
    if mutate:
        mutate(report)
    return workflow.validate_candidate(
        job.pk,
        validator,
        {
            "lease_token": lease,
            "stage_fence": job.stage_fence,
            "candidate_id": candidate.pk,
            "report": report,
            "evidence_files": evidence,
        },
    )


def test_generator_cannot_claim_validation_or_promote(team: Team) -> None:
    job, lease = job_for(team)
    candidate = submit(job, lease, team[2])
    assert services.claim_job(team[2], CAPABILITIES)[0] is None
    with pytest.raises(PermissionDenied):
        workflow.validate_candidate(job.pk, team[2], {})
    with pytest.raises(Conflict, match="браузерной"):
        services.complete_job(job.pk, team[2], {})
    assert candidate.committed
    assert not Version.objects.exists()


def test_success_uses_cas_and_download_exact_validated_bytes(team: Team) -> None:
    job, lease = job_for(team)
    candidate = submit(job, lease, team[2])
    version = validate(team, candidate)
    team[1].refresh_from_db()
    assert team[1].latest_version_id == version.pk
    assert version.eligible
    assert version.html == "" and version.files == {}
    client = Client()
    client.force_login(team[0])
    response = client.get(f"/api/versions/{version.pk}/download/")
    assert response.status_code == 200
    assert response.content == b"<html>Authored fixture</html>"
    detail = client.get(f"/api/versions/{version.pk}/").json()
    assert detail["eligible"] and detail["preview_url"].startswith(settings.PREVIEW_ORIGIN)
    assert detail["html"] == response.content.decode()


def test_skipped_check_is_unverified_and_preserves_previous_playable(team: Team) -> None:
    job, lease = job_for(team)
    first = validate(team, submit(job, lease, team[2]))
    job, lease = job_for(team, kind="revise")

    def skip(report: dict[str, Any]) -> None:
        report["checks"][0]["status"] = "skipped"

    failed = validate(team, submit(job, lease, team[2]), mutate=skip)
    team[1].refresh_from_db()
    job.refresh_from_db()
    assert team[1].latest_version_id == first.pk
    assert not failed.eligible and failed.validation["status"] == "unverified"
    assert job.status == "failed"
    client = Client()
    client.force_login(team[0])
    assert client.get(f"/api/versions/{failed.pk}/download/").status_code == 409
    assert client.get(f"/api/versions/{failed.pk}/source/").status_code == 200
    assert client.get(f"/api/versions/{failed.pk}/").json()["preview_url"] is None


def test_failed_candidate_retained_and_application_routes_repair(team: Team) -> None:
    job, lease = job_for(team, max_repairs=1)

    def fail(report: dict[str, Any]) -> None:
        report["checks"][0]["status"] = "failed"

    version = validate(team, submit(job, lease, team[2]), mutate=fail)
    assert not version.eligible
    repaired_job, repaired_lease = services.claim_job(team[2], CAPABILITIES)
    assert repaired_job.stage == "repair" and repaired_job.attempts == 1
    second = submit(repaired_job, repaired_lease, team[2], idempotency_key="candidate-2")
    second_version = validate(team, second, mutate=fail)
    job.refresh_from_db()
    assert job.status == "failed"
    assert Candidate.objects.count() == 2 and Version.objects.count() == 2
    assert second_version.validation["status"] == "failed"


def test_duplicate_submit_readonly_and_conflicting_bytes_rejected(team: Team) -> None:
    job, lease = job_for(team)
    first = submit(job, lease, team[2])
    assert submit(job, lease, team[2]).pk == first.pk
    with pytest.raises(Conflict):
        submit(job, lease, team[2], html="<p>different</p>")
    assert Candidate.objects.count() == 1


def test_expired_claim_and_cancellation_fence_stale_calls(team: Team) -> None:
    job, lease = job_for(team)
    Job.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    reclaimed, new_lease = services.claim_job(team[2], CAPABILITIES)
    assert reclaimed.stage_fence > job.stage_fence
    with pytest.raises(Conflict):
        submit(job, lease, team[2])
    services.cancel_job(job.pk)
    with pytest.raises(Conflict):
        submit(reclaimed, new_lease, team[2])
    assert not Candidate.objects.exists()


def test_revoked_runner_fence_rejects_and_rolls_back_job_write(team: Team) -> None:
    job, lease = job_for(team)
    previous_expiry = job.lease_expires_at
    previous_updated = job.updated_at
    Runner.objects.filter(pk=team[2].pk).update(revoked=True)
    with pytest.raises(AuthenticationFailed):
        services.heartbeat(job.pk, team[2], lease)
    job.refresh_from_db()
    assert job.lease_expires_at == previous_expiry and job.updated_at == previous_updated
    with pytest.raises(AuthenticationFailed):
        submit(job, lease, team[2])
    assert not Candidate.objects.exists()


def test_crash_after_intent_recovers_without_model_replay(team: Team) -> None:
    job, lease = job_for(team)
    with (
        patch.object(ArtifactStore, "commit", side_effect=OSError("authored crash")),
        pytest.raises(OSError),
    ):
        submit(job, lease, team[2])
    candidate = Candidate.objects.get()
    assert not candidate.committed
    with pytest.raises(Conflict, match="pending"):
        submit(job, lease, team[2], idempotency_key="forbidden-second-candidate")
    with pytest.raises(Conflict, match="current stage"):
        workflow.reserve_invocation(
            job.pk,
            team[2],
            {
                "lease_token": lease,
                "stage_fence": job.stage_fence,
                "invocation_key": "forbidden-paid-call",
                "operation": "draft",
                "prompt_sha256": "a" * 64,
                "reserved_tokens": 60,
            },
        )
    result = workflow.recover_pending()
    assert result == {"recovered": [str(candidate.pk)], "errors": []}
    assert workflow.recover_pending() == {"recovered": [], "errors": []}
    job.refresh_from_db()
    assert job.stage == "validate" and job.status == "queued"
    assert not ModelInvocation.objects.exists()


def test_validation_delivery_is_idempotent_and_does_not_mutate_submission(team: Team) -> None:
    job, lease = job_for(team)
    candidate = submit(job, lease, team[2])
    claimed, validator_lease = services.claim_job(team[3], CAPABILITIES)
    report, evidence = fixture_report(candidate)
    request = {
        "lease_token": validator_lease,
        "stage_fence": claimed.stage_fence,
        "candidate_id": candidate.pk,
        "report": report,
        "evidence_files": evidence,
    }
    first = workflow.validate_candidate(job.pk, team[3], request)
    assert "submission_sha256" not in report
    assert all("object_key" not in item for item in report["evidence_files"])
    repeated = workflow.validate_candidate(job.pk, team[3], request)
    assert repeated.pk == first.pk and Version.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_postgresql_concurrent_validation_delivery_has_one_result(team: Team) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Write race requires the PostgreSQL release database.")
    from threading import Barrier

    job, lease = job_for(team)
    candidate = submit(job, lease, team[2])
    claimed, validator_lease = services.claim_job(team[3], CAPABILITIES)
    report, evidence = fixture_report(candidate)
    barrier = Barrier(2)
    original_fence = services.fence

    def racing_fence(*args: Any, **kwargs: Any) -> Any:
        # Both requests see no result before either acquires the job write lock.
        barrier.wait(timeout=10)
        fenced = original_fence(*args, **kwargs)
        assert fenced.stage == "validate", fenced.stage
        assert fenced.active_candidate_id == candidate.pk, fenced.active_candidate_id
        return fenced

    def delivery() -> Any:
        close_old_connections()
        try:
            return workflow.validate_candidate(
                job.pk,
                team[3],
                {
                    "lease_token": validator_lease,
                    "stage_fence": claimed.stage_fence,
                    "candidate_id": candidate.pk,
                    "report": report,
                    "evidence_files": evidence,
                },
            ).pk
        finally:
            close_old_connections()

    with (
        patch.object(services, "fence", racing_fence),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        results = [
            future.result() for future in [executor.submit(delivery), executor.submit(delivery)]
        ]
    assert results[0] == results[1]
    assert Version.objects.count() == 1


def test_cancelled_pending_intent_recovery_never_restarts_job(team: Team) -> None:
    job, lease = job_for(team)
    with (
        patch.object(ArtifactStore, "commit", side_effect=OSError("authored crash")),
        pytest.raises(OSError),
    ):
        submit(job, lease, team[2])
    services.cancel_job(job.pk)
    workflow.recover_pending()
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert Candidate.objects.get().committed


def test_evidence_bytes_and_artifact_binding_checked(team: Team) -> None:
    job, lease = job_for(team)
    candidate = submit(job, lease, team[2])
    validator_job, validator_lease = services.claim_job(team[3], CAPABILITIES)
    report, evidence = fixture_report(candidate)
    report["artifact"]["html_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        workflow.validate_candidate(
            job.pk,
            team[3],
            {
                "lease_token": validator_lease,
                "stage_fence": validator_job.stage_fence,
                "candidate_id": candidate.pk,
                "report": report,
                "evidence_files": evidence,
            },
        )
    assert not Version.objects.exists()
    report, evidence = fixture_report(candidate)
    evidence["fixture-390.txt"] = base64.b64encode(b"tampered").decode()
    with pytest.raises(ValidationError):
        workflow.validate_candidate(
            job.pk,
            team[3],
            {
                "lease_token": validator_lease,
                "stage_fence": validator_job.stage_fence,
                "candidate_id": candidate.pk,
                "report": report,
                "evidence_files": evidence,
            },
        )
    assert not Version.objects.exists()


def test_invocation_reservation_budget_unknown_and_reuse(team: Team) -> None:
    job, lease = job_for(team, budget_tokens=100)
    request = {
        "lease_token": lease,
        "stage_fence": job.stage_fence,
        "invocation_key": "one",
        "operation": "plan",
        "prompt_sha256": "a" * 64,
        "reserved_tokens": 60,
    }
    invocation = workflow.reserve_invocation(job.pk, team[2], request)
    assert workflow.reserve_invocation(job.pk, team[2], request).pk == invocation.pk
    with pytest.raises(Conflict):
        workflow.reserve_invocation(job.pk, team[2], {**request, "invocation_key": "two"})
    workflow.settle_invocation(
        job.pk,
        team[2],
        {
            **request,
            "invocation_id": invocation.pk,
            "state": "completed",
            "response": {"data": {"fixture": True}, "usage": {"total_tokens": 2}},
        },
    )
    assert workflow.invocation_data(ModelInvocation.objects.get(pk=invocation.pk))["response"][
        "data"
    ]["fixture"]
    assert not invocation.response_key  # original instance unchanged
    Job.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    reclaimed, new_lease = services.claim_job(team[2], CAPABILITIES)
    response = workflow.reserve_invocation(
        job.pk, team[2], {**request, "lease_token": new_lease, "stage_fence": reclaimed.stage_fence}
    )
    assert response.state == "completed"


def test_unsettled_invocation_not_replayed_after_reclaim(team: Team) -> None:
    job, lease = job_for(team)
    request = {
        "lease_token": lease,
        "stage_fence": job.stage_fence,
        "invocation_key": "uncertain",
        "operation": "plan",
        "prompt_sha256": "a" * 64,
        "reserved_tokens": 60,
    }
    invocation = workflow.reserve_invocation(job.pk, team[2], request)
    Job.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    reclaimed, new_lease = services.claim_job(team[2], CAPABILITIES)
    old = workflow.reserve_invocation(
        job.pk, team[2], {**request, "lease_token": new_lease, "stage_fence": reclaimed.stage_fence}
    )
    assert old.stage_fence < reclaimed.stage_fence and old.state == "reserved"
    with pytest.raises(Conflict):
        workflow.settle_invocation(
            job.pk,
            team[2],
            {
                "lease_token": new_lease,
                "stage_fence": reclaimed.stage_fence,
                "invocation_id": invocation.pk,
                "state": "completed",
                "response": {},
            },
        )


def test_preview_scoped_separate_listener_and_no_cookies(team: Team) -> None:
    job, lease = job_for(team)
    version = validate(team, submit(job, lease, team[2]))
    url = preview_url(version)
    path = url.split(settings.PREVIEW_ORIGIN, 1)[1]
    client = Client()
    assert client.get(path).status_code == 404
    with override_settings(
        ROOT_URLCONF="prompt2play.adapters.django.config.preview_urls",
        MIDDLEWARE=["prompt2play.adapters.django.forge.preview.IsolationMiddleware"],
    ):
        client = Client()
        result = client.get(path, HTTP_HOST="127.0.0.1:8001", HTTP_COOKIE="sessionid=private")
        assert result.status_code == 200
        assert result.content == b"<html>Authored fixture</html>"
        assert not result.cookies
        assert "connect-src" in result["Content-Security-Policy"]
        assert (
            client.get(
                f"/preview/{version.pk}/?token=wrong", HTTP_HOST="127.0.0.1:8001"
            ).status_code
            == 403
        )
        assert client.get(path, HTTP_HOST="127.0.0.1:8000").status_code == 403
        assert client.get("/api/projects/", HTTP_HOST="127.0.0.1:8001").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_postgresql_only_one_concurrent_claim(team: Team) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Row claim race requires the PostgreSQL release database.")
    user, project, generator, _ = team
    job = services.create_job(
        project, user, {"kind": "generate", "prompt": "Fixture", "provider": "codex", "model": ""}
    )
    second = Runner.objects.create(name="second", token_hash=secret_hash("second-token"))

    def claim(runner: Any) -> Any:
        close_old_connections()
        try:
            claimed, _ = services.claim_job(runner, CAPABILITIES)
            return claimed.pk if claimed else None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(claim, [generator, second]))
    assert claimed.count(job.pk) == 1 and claimed.count(None) == 1


@pytest.mark.django_db(transaction=True)
def test_postgresql_only_one_concurrent_validator_claim(team: Team) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Row claim race requires the PostgreSQL release database.")
    from threading import Barrier

    job, lease = job_for(team)
    submit(job, lease, team[2])
    second = Runner.objects.create(
        name="second validator", token_hash=secret_hash("second-validator-token"), role="validator"
    )
    barrier = Barrier(2)
    original_update: Any = QuerySet.update

    def simultaneous_claim(query: Any, **values: Any) -> int:
        if query.model is Job and values.get("status") == "running" and "lease_hash" in values:
            # Both statements begin with the same queued job selected earlier.
            barrier.wait(timeout=10)
        return cast(int, original_update(query, **values))

    def claim(runner: Any) -> Any:
        close_old_connections()
        try:
            claimed, _ = services.claim_job(runner, CAPABILITIES)
            return claimed.pk if claimed else None
        finally:
            close_old_connections()

    with (
        patch.object(QuerySet, "update", simultaneous_claim),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        claimed = list(executor.map(claim, [team[3], second]))
    assert claimed.count(job.pk) == 1 and claimed.count(None) == 1


@pytest.mark.django_db(transaction=True)
def test_postgresql_cancel_submit_race_never_reopens_cancelled_job(team: Team) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Write race requires the PostgreSQL release database.")
    job, lease = job_for(team)
    from threading import Barrier

    barrier = Barrier(2)

    def cancel() -> None:
        close_old_connections()
        try:
            barrier.wait()
            services.cancel_job(job.pk)
        finally:
            close_old_connections()

    def commit() -> Any:
        close_old_connections()
        try:
            barrier.wait()
            with contextlib.suppress(Conflict):
                submit(job, lease, team[2])
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(cancel), executor.submit(commit)]
        for future in futures:
            future.result()
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert team[1].latest_version_id is None
    assert services.claim_job(team[3], CAPABILITIES)[0] is None


@pytest.mark.django_db(transaction=True)
def test_postgresql_duplicate_submit_race_has_one_candidate(team: Team) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Write race requires the PostgreSQL release database.")
    job, lease = job_for(team)
    from threading import Barrier

    barrier = Barrier(2)

    def commit() -> Any:
        close_old_connections()
        try:
            barrier.wait()
            return submit(job, lease, team[2]).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(commit), executor.submit(commit)]
        identities = [future.result() for future in futures]
    assert len(set(identities)) == 1 and Candidate.objects.count() == 1


def test_api_role_and_staged_protocol(team: Team) -> None:
    user, _project, _generator, _validator = team
    client = Client()
    assert client.get("/api/projects/").status_code == 401
    client.force_login(user)
    created = client.post(
        "/api/runners/",
        {"name": "trusted validator", "role": "validator"},
        content_type="application/json",
    )
    assert created.status_code == 201 and created.json()["runner"]["role"] == "validator"
    job, _ = job_for(team)
    # Existing lease must be reclaimed through authenticated worker request.
    Job.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    client.logout()
    client.defaults["HTTP_AUTHORIZATION"] = "Bearer generator-token"
    claimed = client.post(
        "/api/worker/claim/", {"capabilities": CAPABILITIES}, content_type="application/json"
    )
    assert claimed.status_code == 200
    data = claimed.json()
    candidate = client.post(
        f"/api/worker/jobs/{job.pk}/candidates/",
        {
            "lease_token": data["lease_token"],
            "stage_fence": data["job"]["stage_fence"],
            "idempotency_key": "http-fixture",
            "html": "<p>Fixture</p>",
            "files": {"game.js": "// fixture"},
            "spec": {"title": "Fixture"},
        },
        content_type="application/json",
    )
    assert candidate.status_code == 201 and candidate.json()["committed"]
    assert (
        client.post(
            f"/api/worker/jobs/{job.pk}/validate/",
            {
                "lease_token": data["lease_token"],
                "stage_fence": data["job"]["stage_fence"],
                "candidate_id": candidate.json()["id"],
                "report": {},
            },
            content_type="application/json",
        ).status_code
        == 403
    )
    client.defaults["HTTP_AUTHORIZATION"] = "Bearer validator-token"
    claimed = client.post(
        "/api/worker/claim/", {"capabilities": CAPABILITIES}, content_type="application/json"
    ).json()
    assert claimed["candidate"]["html"] == "<p>Fixture</p>"
    report, evidence = fixture_report(Candidate.objects.get(pk=candidate.json()["id"]))
    checked = client.post(
        f"/api/worker/jobs/{job.pk}/validate/",
        {
            "lease_token": claimed["lease_token"],
            "stage_fence": claimed["job"]["stage_fence"],
            "candidate_id": candidate.json()["id"],
            "report": report,
            "evidence_files": evidence,
        },
        content_type="application/json",
    )
    assert checked.status_code == 201 and checked.json()["eligible"]


def test_paid_inflight_accounting_after_cancellation_is_owned_and_idempotent(team: Team) -> None:
    job, lease = job_for(team)
    invocation = workflow.reserve_invocation(
        job.pk,
        team[2],
        {
            "lease_token": lease,
            "stage_fence": job.stage_fence,
            "invocation_key": "paid-inflight",
            "operation": "draft",
            "prompt_sha256": "a" * 64,
            "reserved_tokens": 100,
        },
    )
    services.cancel_job(job.pk)
    usage = {
        "input_tokens": 20,
        "cached_input_tokens": 0,
        "output_tokens": 30,
        "total_tokens": 50,
        "calls": 1,
    }
    recorded = workflow.account_invocation(
        job.pk, team[2], {"invocation_id": invocation.pk, "invocation_usage": usage}
    )
    assert recorded.actual_usage == usage and recorded.state == "ambiguous"
    assert not recorded.response_key
    assert (
        workflow.account_invocation(
            job.pk, team[2], {"invocation_id": invocation.pk, "invocation_usage": usage}
        ).pk
        == invocation.pk
    )
    job.refresh_from_db()
    assert job.status == "cancelled" and job.usage["total_tokens"] == 50
    assert not Candidate.objects.filter(job=job).exists()
    other = Runner.objects.create(name="unrelated", token_hash=secret_hash("unrelated-token"))
    with pytest.raises(PermissionDenied):
        workflow.account_invocation(
            job.pk, other, {"invocation_id": invocation.pk, "invocation_usage": usage}
        )
    with pytest.raises(Conflict):
        workflow.account_invocation(
            job.pk,
            team[2],
            {
                "invocation_id": invocation.pk,
                "invocation_usage": {**usage, "input_tokens": 21, "total_tokens": 51},
            },
        )


def test_repair_and_reclaim_preserve_original_run_deadline(team: Team) -> None:
    initial = timezone.now()
    with patch.object(timezone, "now", return_value=initial):
        job, lease = job_for(team, budget_seconds=100)
        expiry = job.execution_expires_at
        assert expiry == initial + timedelta(seconds=100)
        candidate = submit(job, lease, team[2])

        def fail(report: dict[str, Any]) -> None:
            report["checks"][0]["status"] = "failed"

        validate(team, candidate, mutate=fail)
    with patch.object(timezone, "now", return_value=initial + timedelta(seconds=20)):
        repaired, repaired_lease = services.claim_job(team[2], CAPABILITIES)
        assert repaired.execution_expires_at == expiry
        assert job_data(repaired)["remaining_seconds"] == 80
        heartbeat = services.heartbeat(job.pk, team[2], repaired_lease)
        assert heartbeat["remaining_seconds"] == 80
        assert heartbeat["execution_expires_at"] == expiry.isoformat()
    Job.objects.filter(pk=job.pk).update(lease_expires_at=initial + timedelta(seconds=21))
    with patch.object(timezone, "now", return_value=initial + timedelta(seconds=30)):
        reclaimed, _ = services.claim_job(team[2], CAPABILITIES)
        assert reclaimed.execution_expires_at == expiry
        assert job_data(reclaimed)["remaining_seconds"] == 70


def test_expired_run_stops_before_new_paid_call_even_with_live_lease(team: Team) -> None:
    initial = timezone.now()
    with patch.object(timezone, "now", return_value=initial):
        job, lease = job_for(team, budget_seconds=10)
    with patch.object(timezone, "now", return_value=initial + timedelta(seconds=11)):
        with pytest.raises(Conflict, match="deadline"):
            workflow.reserve_invocation(
                job.pk,
                team[2],
                {
                    "lease_token": lease,
                    "stage_fence": job.stage_fence,
                    "invocation_key": "expired-must-not-pay",
                    "operation": "draft",
                    "prompt_sha256": "a" * 64,
                    "reserved_tokens": 100,
                },
            )
        assert not ModelInvocation.objects.exists()
        assert services.claim_job(team[2], CAPABILITIES) == (None, None)
    job.refresh_from_db()
    assert job.status == "failed" and job.stage == "deadline"
    assert job.stage_fence > 1


def test_expired_pending_candidate_recovers_bytes_without_restarting(team: Team) -> None:
    initial = timezone.now()
    with patch.object(timezone, "now", return_value=initial):
        job, lease = job_for(team, budget_seconds=10)
        with (
            patch.object(ArtifactStore, "commit", side_effect=OSError("authored crash")),
            pytest.raises(OSError),
        ):
            submit(job, lease, team[2])
    with patch.object(timezone, "now", return_value=initial + timedelta(seconds=11)):
        result = workflow.recover_pending()
    assert len(result["recovered"]) == 1 and not result["errors"]
    job.refresh_from_db()
    assert job.status == "failed" and job.stage == "deadline"
    assert Candidate.objects.get().committed and not Version.objects.exists()


def test_job_api_rejects_extended_or_zero_wall_budget() -> None:
    for seconds in (0, 3601):
        serializer = cast(Any, JobCreateSerializer)(
            data={
                "kind": "generate",
                "prompt": "Fixture",
                "provider": "codex",
                "budget_seconds": seconds,
            }
        )
        assert not serializer.is_valid()
        assert "budget_seconds" in serializer.errors


def test_validation_crossing_deadline_cannot_publish(team: Team) -> None:
    current = [timezone.now()]
    original_store = workflow.store_evidence

    def slow_evidence(report: dict[str, Any], supplied: dict[str, str]) -> Any:
        stored = original_store(report, supplied)
        current[0] += timedelta(seconds=11)
        return stored

    with (
        patch.object(timezone, "now", side_effect=lambda: current[0]),
        patch.object(workflow, "store_evidence", side_effect=slow_evidence),
    ):
        job, lease = job_for(team, budget_seconds=10)
        candidate = submit(job, lease, team[2])
        with pytest.raises(Conflict, match="deadline"):
            validate(team, candidate)
        services.expire_jobs()
    team[1].refresh_from_db()
    job.refresh_from_db()
    assert team[1].latest_version_id is None and not Version.objects.exists()
    assert not hasattr(Candidate.objects.get(), "result")
    assert job.status == "failed" and job.stage == "deadline"


def test_public_activity_exposes_current_call_and_contact_without_source(team: Team) -> None:
    job, _ = job_for(team)
    first = ModelInvocation.objects.create(
        job=job,
        generator=team[2],
        invocation_key="completed-plan",
        operation="plan",
        prompt_sha256="a" * 64,
        stage_fence=job.stage_fence,
        reserved_tokens=100,
        state="completed",
        actual_usage={"calls": 1},
        settled_at=timezone.now(),
        response_key="private-response-not-for-polling",
    )
    second = ModelInvocation.objects.create(
        job=job,
        generator=team[2],
        invocation_key="pending-author",
        operation="author",
        prompt_sha256="b" * 64,
        stage_fence=job.stage_fence,
        reserved_tokens=100,
    )
    result = job_data(job)
    assert result["activity"]["worker_connected"] is True
    assert result["activity"]["worker_contact_at"]
    assert [call["id"] for call in result["activity"]["calls"]] == [str(first.pk), str(second.pk)]
    assert result["activity"]["calls"][-1]["operation"] == "author"
    assert result["activity"]["calls"][-1]["finished_at"] is None
    assert "private-response" not in str(result)
    assert "lease_hash" not in result
    job.refresh_from_db()
    assert job.stage == "plan"  # model activity must not mutate orchestration state
    job.status = "failed"
    result = job_data(job)
    assert result["activity"]["worker_contact_at"] is None
    assert result["activity"]["worker_connected"] is False


def test_studio_run_has_no_wall_deadline_even_after_reclaim(team: Team) -> None:
    serializer = cast(Any, JobCreateSerializer)(
        data={"kind": "generate", "prompt": "Fixture", "provider": "codex"}
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["budget_seconds"] is None
    job, _ = job_for(team)
    assert job.budget_seconds is None and job.execution_expires_at is None
    future = timezone.now() + timedelta(days=1)
    with patch.object(timezone, "now", return_value=future):
        assert services.expire_jobs() == 0
        assert job_data(job)["remaining_seconds"] is None
        reclaimed, _ = services.claim_job(team[2], CAPABILITIES)
        assert reclaimed.pk == job.pk
        assert reclaimed.execution_expires_at is None
    services.cancel_job(job.pk)
    assert Job.objects.get(pk=job.pk).status == "cancelled"


@pytest.mark.parametrize("action", ["approve", "revise", "cancel"])
def test_pro_build_waits_for_human_and_preserves_previous_version(team: Team, action: str) -> None:
    from prompt2play.adapters.django.forge.reviews import decide_review

    first, lease = job_for(team)
    previous = validate(team, submit(first, lease, team[2]))
    job, lease = job_for(team, kind="revise")
    candidate = submit(job, lease, team[2])
    Job.objects.filter(pk=job.pk).update(creation_mode="pro")
    version = validate(team, candidate)
    job.refresh_from_db()
    team[1].refresh_from_db()
    assert job.status == "waiting" and job.stage == "review_build"
    assert job.result_version_id == version.pk and team[1].latest_version_id == previous.pk
    assert workflow.version_eligible(version), "Only the validated proposal can be previewed"
    assert services.claim_job(team[2], {**CAPABILITIES, "interactive_plan_v1": True})[0] is None
    with pytest.raises(Conflict, match="активное"):
        services.create_job(
            team[1], team[0], {"kind": "generate", "prompt": "other", "provider": "codex"}
        )
    before = (job.usage, job.cost_nano, job.budget_usd, job.budget_tokens)
    if action == "cancel":
        services.cancel_job(job.pk)
    else:
        cast(Any, decide_review)(
            job.pk, stage_fence=job.stage_fence, action=action, feedback="Improve the map"
        )
    job.refresh_from_db()
    team[1].refresh_from_db()
    assert (job.usage, job.cost_nano, job.budget_usd, job.budget_tokens) == before
    assert team[1].latest_version_id == (version.pk if action == "approve" else previous.pk)
    if action == "revise":
        assert job.stage == "repair" and job.review["manual_revisions"] == 1
        assert (
            job.active_candidate_id == candidate.pk
            and job.review["feedback"][-1]["text"] == "Improve the map"
        )
    elif action == "approve":
        assert job.status == "completed"
    else:
        assert job.status == "cancelled"


def test_pro_server_rejects_paid_author_and_candidate_without_approval(team: Team) -> None:
    job, lease = job_for(team)
    Job.objects.filter(pk=job.pk).update(creation_mode="pro")
    with pytest.raises(Conflict, match="Подтвердите план"):
        workflow.reserve_invocation(
            job.pk,
            team[2],
            {
                "lease_token": lease,
                "stage_fence": job.stage_fence,
                "invocation_key": "unauthorized-author",
                "operation": "author",
                "prompt_sha256": "a" * 64,
                "reserved_tokens": 1000,
            },
        )
    with pytest.raises(Conflict, match="Подтвердите план"):
        submit(job, lease, team[2])
    assert not ModelInvocation.objects.filter(job=job).exists()
    assert not Candidate.objects.filter(job=job).exists()


@pytest.mark.django_db(transaction=True)
def test_postgresql_double_approval_releases_only_once(team: Team) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Concurrent approval requires PostgreSQL.")
    from threading import Barrier

    from prompt2play.adapters.django.forge.reviews import decide_review

    job, _ = job_for(team)
    Job.objects.filter(pk=job.pk).update(
        creation_mode="pro",
        status="waiting",
        stage="review_plan",
        review={"plan_key": "authored-fixture-key"},
    )
    barrier = Barrier(2)

    def approve(_: int) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            cast(Any, decide_review)(job.pk, stage_fence=job.stage_fence, action="approve")
            return "accepted"
        except Conflict:
            return "stale"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, [1, 2])) == ["accepted", "stale"]
    job.refresh_from_db()
    assert job.status == "queued" and job.stage_fence == 2


def test_budget_extension_resumes_same_job_keeps_ledger_and_fences_duplicate_click(
    team: Team,
) -> None:
    from decimal import Decimal

    job, _ = job_for(team, model="gpt-6.1-sol", budget_usd=Decimal("10.00"))
    Job.objects.filter(pk=job.pk).update(
        status="failed",
        error="BudgetExhausted: next request",
        cost_nano=6000000000,
        cost_upper_nano=8000000000,
    )
    ModelInvocation.objects.create(
        job=job,
        generator=team[2],
        invocation_key="old-unknown",
        operation="author",
        prompt_sha256="a" * 64,
        stage_fence=1,
        reserved_tokens=100,
        reserved_cost_nano=300000000,
        state="ambiguous",
    )
    ModelInvocation.objects.create(
        job=job,
        generator=team[2],
        invocation_key="last-completed",
        operation="author",
        prompt_sha256="b" * 64,
        stage_fence=1,
        reserved_tokens=100,
        state="completed",
        actual_usage={"total_tokens": 100},
    )
    client = Client()
    client.force_login(team[0])
    path = f"/api/jobs/{job.pk}/budget/"
    values = {"stage_fence": job.stage_fence, "budget_usd": "20.00"}
    response = client.post(path, values, content_type="application/json")
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["id"] == str(job.pk) and data["status"] == "queued" and data["resume_count"] == 1
    assert (
        data["cost"]["upper_usd"] == "8.000000000" and data["cost"]["reserved_usd"] == "0.300000000"
    )
    assert data["budget_usd"] == "20.00" and data["budget_tokens"] == job.budget_tokens
    assert client.post(path, values, content_type="application/json").status_code == 409
    job.refresh_from_db()
    assert job.invocations.count() == 2 and job.cost_nano == 6000000000
    assert Job.objects.filter(project=team[1]).count() == 1


@pytest.mark.parametrize(
    "state,error",
    [("cancelled", "BudgetExhausted: x"), ("completed", ""), ("failed", "ProviderError: unknown")],
)
def test_budget_extension_cannot_revive_unrelated_or_cancelled_jobs(
    team: Team, state: str, error: str
) -> None:
    job, _ = job_for(team)
    Job.objects.filter(pk=job.pk).update(status=state, error=error)
    client = Client()
    client.force_login(team[0])
    response = client.post(
        f"/api/jobs/{job.pk}/budget/",
        {"stage_fence": job.stage_fence, "budget_tokens": 800000},
        content_type="application/json",
    )
    assert response.status_code == 409
    job.refresh_from_db()
    assert job.status == state


def test_budget_extension_requires_larger_same_unit_and_no_active_successor(team: Team) -> None:
    from decimal import Decimal

    job, _ = job_for(team, model="gpt-6.1-sol", budget_usd=Decimal("10.00"))
    Job.objects.filter(pk=job.pk).update(status="failed", error="BudgetExhausted: next request")
    client = Client()
    client.force_login(team[0])
    path = f"/api/jobs/{job.pk}/budget/"
    for amount in ("10.00", "9.00"):
        assert (
            client.post(
                path,
                {"stage_fence": job.stage_fence, "budget_usd": amount},
                content_type="application/json",
            ).status_code
            == 409
        )
    assert (
        client.post(
            path,
            {"stage_fence": job.stage_fence, "budget_tokens": 800000},
            content_type="application/json",
        ).status_code
        == 409
    )
    assert (
        client.post(
            path,
            {"stage_fence": job.stage_fence, "budget_usd": "NaN"},
            content_type="application/json",
        ).status_code
        == 400
    )
    services.create_job(
        team[1], team[0], {"kind": "generate", "prompt": "successor", "provider": "codex"}
    )
    assert (
        client.post(
            path,
            {"stage_fence": job.stage_fence, "budget_usd": "20.00"},
            content_type="application/json",
        ).status_code
        == 409
    )


def test_budget_extension_preserves_unknown_last_call_and_requires_session(team: Team) -> None:
    job, _ = job_for(team)
    Job.objects.filter(pk=job.pk).update(
        status="failed", error="GenerationStopped: Run token budget exceeded"
    )
    path = f"/api/jobs/{job.pk}/budget/"
    values = {"stage_fence": job.stage_fence, "budget_tokens": 800000}
    assert Client().post(path, values, content_type="application/json").status_code in (401, 403)
    ModelInvocation.objects.create(
        job=job,
        invocation_key="unknown",
        operation="author",
        prompt_sha256="a" * 64,
        stage_fence=1,
        reserved_tokens=100,
        state="ambiguous",
    )
    client = Client()
    client.force_login(team[0])
    assert client.post(path, values, content_type="application/json").status_code == 200
    unknown = job.invocations.get(invocation_key="unknown")
    assert (
        unknown.state == "ambiguous"
        and unknown.actual_usage is None
        and unknown.reserved_tokens == 100
    )
    job.refresh_from_db()
    assert job.checkpoint["user_retry_keys"]["unknown"].endswith(":user-resume:1")


def test_worker_cannot_downgrade_user_requested_automatic_playthrough(team: Team) -> None:
    job, lease = job_for(team, playthrough_mode="auto")
    candidate = submit(job, lease, team[2])
    claimed, validation_lease = services.claim_job(team[3], CAPABILITIES)
    report, evidence = fixture_report(candidate)
    report["completion_required"] = False
    with pytest.raises(ValidationError, match="automatic playthrough"):
        workflow.validate_candidate(
            job.pk,
            team[3],
            {
                "lease_token": validation_lease,
                "stage_fence": claimed.stage_fence,
                "candidate_id": candidate.pk,
                "report": report,
                "evidence_files": evidence,
            },
        )
    assert not Version.objects.filter(candidate=candidate).exists()


def test_user_continuation_keeps_unknown_spend_and_fences_duplicate_clicks(team: Team) -> None:
    from prompt2play.adapters.django.forge.recovery import resume_job

    job, lease = job_for(team)
    generator = team[2]
    values = {
        "lease_token": lease,
        "stage_fence": job.stage_fence,
        "invocation_key": "plan:unknown",
        "operation": "plan",
        "prompt_sha256": "a" * 64,
        "reserved_tokens": 1234,
    }
    previous = workflow.reserve_invocation(job.pk, generator, values)
    ModelInvocation.objects.filter(pk=previous.pk).update(state="ambiguous")
    Job.objects.filter(pk=job.pk).update(
        status="failed", error="ProviderError: unknown", lease_hash="", lease_expires_at=None
    )
    job.refresh_from_db()
    old_fence = job.stage_fence
    client = Client()
    client.force_login(team[0])
    assert client.get(f"/api/jobs/{job.pk}/").json()["can_resume"] is True
    response = client.post(
        f"/api/jobs/{job.pk}/resume/", {"stage_fence": old_fence}, content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert (
        client.post(
            f"/api/jobs/{job.pk}/resume/",
            {"stage_fence": old_fence},
            content_type="application/json",
        ).status_code
        == 409
    )
    job, lease = services.claim_job(generator, CAPABILITIES)
    values.update(lease_token=lease, stage_fence=job.stage_fence)
    new = workflow.reserve_invocation(job.pk, generator, values)
    assert new.pk != previous.pk
    assert workflow.reserve_invocation(job.pk, generator, values).pk == new.pk
    previous.refresh_from_db()
    assert (
        previous.state == "ambiguous"
        and previous.actual_usage is None
        and previous.reserved_tokens == 1234
    )
    Job.objects.filter(pk=job.pk).update(
        status="failed", error="ProviderError: second failure", lease_hash="", lease_expires_at=None
    )
    resumed = cast(Any, resume_job)(job.pk, {"stage_fence": job.stage_fence})
    assert resumed.resume_count == 2
    job, lease = services.claim_job(generator, CAPABILITIES)
    values.update(lease_token=lease, stage_fence=job.stage_fence)
    third = workflow.reserve_invocation(job.pk, generator, values)
    assert third.pk not in (new.pk, previous.pk)
    assert job.invocations.count() == 3


def test_continuation_refuses_completed_cancelled_or_active_successor(team: Team) -> None:
    from prompt2play.adapters.django.forge.recovery import resume_job

    job, _ = job_for(team)
    for status in ("completed", "cancelled", "running"):
        Job.objects.filter(pk=job.pk).update(status=status)
        with pytest.raises(Conflict):
            cast(Any, resume_job)(job.pk, {"stage_fence": job.stage_fence})
    Job.objects.filter(pk=job.pk).update(status="failed", error="ProviderError: failed")
    Job.objects.create(project=team[1], status="queued", prompt="successor")
    with pytest.raises(Conflict, match="активное"):
        cast(Any, resume_job)(job.pk, {"stage_fence": job.stage_fence})


def test_failure_event_retains_safe_provider_details(team: Team) -> None:
    job, lease = job_for(team)
    client = Client()
    response = client.post(
        f"/api/worker/jobs/{job.pk}/fail/",
        {
            "lease_token": lease,
            "stage_fence": job.stage_fence,
            "error": "ProviderError: context window exceeded",
            "diagnostic": {
                "exceptions": [
                    {
                        "type": "ProviderError",
                        "provider_diagnostic": {
                            "exit_code": 7,
                            "category": "context_length",
                            "message": "Context window exceeded; prompt=private prompt",
                        },
                        "locals": {"secret": "hidden"},
                    }
                ]
            },
        },
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer generator-token",
    )
    assert response.status_code == 200, response.content
    job.refresh_from_db()
    assert job.status == "failed"
    diagnostic = job.events.last().data
    assert diagnostic["exceptions"][0]["provider_diagnostic"]["exit_code"] == 7
    assert "private prompt" not in str(diagnostic) and "locals" not in str(diagnostic)


def test_continuation_from_committed_failure_preserves_candidate(team: Team) -> None:
    from prompt2play.adapters.django.forge.recovery import resume_job

    job, lease = job_for(team)
    candidate = submit(job, lease, team[2])
    Job.objects.filter(pk=job.pk).update(
        status="failed", stage="commit", error="Storage acknowledgement interrupted"
    )
    job.refresh_from_db()
    updated = cast(Any, resume_job)(job.pk, {"stage_fence": job.stage_fence})
    assert updated.stage == "validate" and updated.status == "queued"
    assert updated.active_candidate_id == candidate.pk
    assert updated.project.latest_version_id is None


def test_second_continuation_reuses_successful_retry_instead_of_old_ambiguous_call(
    team: Team,
) -> None:
    from prompt2play.adapters.django.forge.recovery import continuation_checkpoint

    job, _ = job_for(team)
    original = ModelInvocation.objects.create(
        job=job,
        invocation_key="plan:original",
        operation="plan",
        prompt_sha256="a" * 64,
        stage_fence=1,
        reserved_tokens=10,
        state="ambiguous",
    )
    successful = ModelInvocation.objects.create(
        job=job,
        invocation_key="plan:original:user-resume:1",
        operation="plan",
        prompt_sha256="a" * 64,
        stage_fence=2,
        reserved_tokens=10,
        state="completed",
        actual_usage={"calls": 1},
    )
    job.checkpoint = {"user_retry_keys": {original.invocation_key: successful.invocation_key}}
    job.resume_count = 1
    checkpoint = cast(Any, continuation_checkpoint)(job)
    assert checkpoint["user_retry_keys"][original.invocation_key] == successful.invocation_key


def test_native_submission_cannot_disable_mechanics_gate(team: Team) -> None:
    from prompt2play.generation.runtime import assemble_runtime, capture_runtime_identity

    job, lease = job_for(team)
    spec = {
        "title": "Authored gate fixture",
        "format": "runtime-v1",
        "runtime": capture_runtime_identity(),
    }
    files = {
        "game.js": 'function createGame(){return {snapshot(){return {phase:"ready"}},dispatch(){}}}'
    }
    with pytest.raises(ValidationError, match="require basic mechanics"):
        submit(
            job,
            lease,
            team[2],
            format="runtime-v1",
            files=files,
            spec=spec,
            html=assemble_runtime(files, spec),
        )
    assert not Candidate.objects.filter(job=job).exists()


def test_pause_waits_for_paid_reply_and_resumes_without_spend_reset(team: Team) -> None:
    from prompt2play.adapters.django.forge import pauses, planning

    pause: Any = pauses
    saved: Any = planning
    job, lease = job_for(team)
    invocation = workflow.reserve_invocation(
        job.pk,
        team[2],
        {
            "lease_token": lease,
            "stage_fence": job.stage_fence,
            "invocation_key": "plan:fixture",
            "prompt_sha256": "a" * 64,
            "reserved_tokens": 100,
            "operation": "plan",
        },
    )
    pending = pause.pause_job(job.pk, {"stage_fence": job.stage_fence})
    assert pending.status == "running" and pending.pause_requested
    usage = {
        "calls": 1,
        "input_tokens": 10,
        "cached_input_tokens": 5,
        "output_tokens": 20,
        "total_tokens": 30,
    }
    reply = {"game_spec": {"fixture": True}, "build_plan": {}}
    workflow.settle_invocation(
        job.pk,
        team[2],
        {
            "lease_token": lease,
            "stage_fence": job.stage_fence,
            "invocation_id": invocation.pk,
            "state": "completed",
            "response": {"data": reply, "usage": usage},
            "usage": usage,
            "invocation_usage": usage,
        },
    )
    job.refresh_from_db()
    assert job.status == "paused" and not job.pause_requested
    assert saved.load_planning(job)["proposal"] == reply
    assert job.usage == usage
    assert services.claim_job(team[2], CAPABILITIES) == (None, None)
    with pytest.raises(Conflict):
        services.create_job(
            team[1], team[0], {"kind": "generate", "provider": "codex", "prompt": "Blocked"}
        )
    fence = job.stage_fence
    resumed = pause.resume_paused(job.pk, {"stage_fence": fence})
    assert resumed.status == "queued" and resumed.usage == usage
    with pytest.raises(Conflict):
        pause.resume_paused(job.pk, {"stage_fence": fence})
    claimed, new_lease = services.claim_job(team[2], CAPABILITIES)
    replay = workflow.reserve_invocation(
        job.pk,
        team[2],
        {
            "lease_token": new_lease,
            "stage_fence": claimed.stage_fence,
            "invocation_key": "plan:fixture",
            "prompt_sha256": "a" * 64,
            "reserved_tokens": 100,
            "operation": "plan",
        },
    )
    assert replay.pk == invocation.pk and replay.state == "completed"
    assert job.invocations.count() == 1


def test_pause_blocks_new_reservation_and_cancel_is_terminal(team: Team) -> None:
    from prompt2play.adapters.django.forge import pauses

    pause: Any = pauses
    job, lease = job_for(team)
    pause.pause_job(job.pk, {"stage_fence": job.stage_fence})
    assert (
        workflow.reserve_invocation(
            job.pk,
            team[2],
            {
                "lease_token": lease,
                "stage_fence": job.stage_fence,
                "invocation_key": "plan:new",
                "prompt_sha256": "b" * 64,
                "reserved_tokens": 100,
                "operation": "plan",
            },
        )
        is None
    )
    job.refresh_from_db()
    assert job.status == "paused" and job.invocations.count() == 0
    services.cancel_job(job.pk)
    job.refresh_from_db()
    assert job.status == "cancelled"
    with pytest.raises(Conflict):
        pause.resume_paused(job.pk, {"stage_fence": job.stage_fence})


def test_pause_queued_and_approval_keep_their_stage(team: Team) -> None:
    from prompt2play.adapters.django.forge import pauses

    pause: Any = pauses
    for status, stage in (("queued", "plan"), ("waiting", "review_plan")):
        job = Job.objects.create(project=team[1], status=status, stage=stage)
        stopped = pause.pause_job(job.pk, {"stage_fence": 0})
        assert stopped.status == "paused" and stopped.stage == stage
        resumed = pause.resume_paused(job.pk, {"stage_fence": stopped.stage_fence})
        assert resumed.status == status and resumed.stage == stage
        services.cancel_job(job.pk)


def test_pause_api_requires_login_and_fence(team: Team) -> None:
    job, _ = job_for(team)
    client = Client()
    url = f"/api/jobs/{job.pk}/pause/"
    assert client.post(
        url, {"stage_fence": job.stage_fence}, content_type="application/json"
    ).status_code in (401, 403)
    client.force_login(team[0])
    assert (
        client.post(
            url, {"stage_fence": job.stage_fence - 1}, content_type="application/json"
        ).status_code
        == 409
    )
    response = client.post(url, {"stage_fence": job.stage_fence}, content_type="application/json")
    assert response.status_code == 200 and response.json()["pause_requested"]


def test_pause_during_commit_resumes_validation_of_the_same_candidate(team: Team) -> None:
    from prompt2play.adapters.django.forge import pauses

    pause: Any = pauses
    job, lease = job_for(team)
    with (
        patch.object(
            workflow, "finalize_intent", side_effect=RuntimeError("fixture commit interruption")
        ),
        pytest.raises(RuntimeError),
    ):
        submit(job, lease, team[2])
    job.refresh_from_db()
    assert job.stage == "commit"
    candidate_id = job.active_candidate_id
    pause.pause_boundary(
        job.pk,
        team[2],
        {"lease_token": lease, "stage_fence": job.stage_fence, "reason": "Fixture pause"},
    )
    job.refresh_from_db()
    resumed = pause.resume_paused(job.pk, {"stage_fence": job.stage_fence})
    assert resumed.status == "queued" and resumed.stage == "validate"
    assert resumed.active_candidate_id == candidate_id
    assert Candidate.objects.get(pk=candidate_id).committed


def test_requested_pause_is_kept_after_worker_disconnect(team: Team) -> None:
    from prompt2play.adapters.django.forge import pauses

    pause: Any = pauses
    job, _ = job_for(team)
    pause.pause_job(job.pk, {"stage_fence": job.stage_fence})
    Job.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    assert services.claim_job(team[2], CAPABILITIES) == (None, None)
    job.refresh_from_db()
    assert job.status == "paused"


@pytest.mark.django_db(transaction=True)
def test_postgresql_double_resume_from_pause_releases_only_once(team: Team) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL concurrency coverage")
    from prompt2play.adapters.django.forge import pauses

    pause: Any = pauses
    job = Job.objects.create(project=team[1], status="queued")
    job = pause.pause_job(job.pk, {"stage_fence": 0})
    fence = job.stage_fence

    def resume() -> str:
        close_old_connections()
        try:
            pause.resume_paused(job.pk, {"stage_fence": fence})
            return "resumed"
        except Conflict:
            return "stale"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: resume(), range(2))) == ["resumed", "stale"]
    job.refresh_from_db()
    assert job.status == "queued" and job.resume_count == 1


def test_old_worker_cannot_discard_a_saved_planning_checkpoint(team: Team) -> None:
    job = Job.objects.create(
        project=team[1],
        provider="codex",
        kind="generate",
        status="queued",
        checkpoint={"planning": {"key": "a" * 64}},
    )
    assert services.claim_job(team[2], {"providers": ["codex"]}) == (None, None)
    claimed, _ = services.claim_job(team[2], CAPABILITIES)
    assert claimed.pk == job.pk


def test_pause_retains_all_inflight_responses_before_releasing_lease(team: Team) -> None:
    from prompt2play.adapters.django.forge import pauses

    pause: Any = pauses
    job, lease = job_for(team)

    def reserve(key: str) -> Any:
        return workflow.reserve_invocation(
            job.pk,
            team[2],
            {
                "lease_token": lease,
                "stage_fence": job.stage_fence,
                "invocation_key": key,
                "prompt_sha256": "d" * 64,
                "reserved_tokens": 100,
                "operation": "engine",
            },
        )

    calls = [reserve("engine:first"), reserve("renderer:second")]
    pause.pause_job(job.pk, {"stage_fence": job.stage_fence})
    assert reserve("audio:blocked") is None
    job.refresh_from_db()
    assert job.status == "running" and job.pause_requested
    for index, call in enumerate(calls):
        workflow.settle_invocation(
            job.pk,
            team[2],
            {
                "lease_token": lease,
                "stage_fence": job.stage_fence,
                "invocation_id": call.pk,
                "state": "completed",
                "response": {"data": {"fixture": True}, "usage": {}},
            },
        )
        job.refresh_from_db()
        assert job.status == ("running" if index == 0 else "paused")
    assert job.invocations.filter(state="completed").count() == 2
