import io
import copy
import json
import os
import secrets
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from prompt2play.adapters.django.forge.authentication import secret_hash
from prompt2play.adapters.django.forge.models import (
    Event,
    Job,
    Project,
    Runner,
    User,
    Version,
    empty_usage,
)
from prompt2play.adapters.django.forge.tests.evidence_fixtures import bound_report


PASSWORD = "Cobalt-River-Stage-913!"
MODULES = {
    name: f"// {name}\nconst {name.split('.')[0]} = 1;"
    for name in ("engine.js", "renderer.js", "audio.js", "ui.js")
}
REPORT = {
    "status": "partial",
    "checks": [
        {"name": "syntax", "status": "passed", "message": "Checked fixture syntax."},
        {"name": "browser", "status": "skipped", "message": "No browser in unit tests."},
    ],
    "errors": [],
    "warnings": ["No browser validation."],
}
HTML = '<!doctype html><html><title>Fixture</title><script>"use strict";</script></html>'


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class APITestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="builder", password=PASSWORD)
        self.team = APIClient()
        self.team.force_login(self.user)
        self.project = Project.objects.create(
            title="Test game", prompt="Make a dungeon", created_by=self.user
        )
        self.token = secrets.token_urlsafe(32)
        self.runner = Runner.objects.create(
            name="Local runner", token_hash=secret_hash(self.token), created_by=self.user
        )
        self.worker = APIClient()
        self.worker.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def make_job(self, **values):
        data = dict(kind="generate", prompt="A playable game", provider="codex")
        data.update(values)
        response = self.team.post(f"/api/projects/{self.project.pk}/jobs/", data, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def claim(self, worker=None, providers=None):
        response = (worker or self.worker).post(
            "/api/worker/claim/",
            {
                "capabilities": {
                    "providers": providers or ["codex"],
                    "model": "",
                    "validator": "static",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def write(self, job, action, lease, **values):
        return self.worker.post(
            f"/api/worker/jobs/{job['id']}/{action}/",
            {"lease_token": lease, **values},
            format="json",
        )

    def completion(self, **values):
        payload = dict(
            html=HTML,
            files=MODULES,
            spec={"title": "Fixture"},
            summary="Unit-test artifact",
            usage=empty_usage(),
        )
        payload.update(values)
        payload.setdefault(
            "validation", bound_report(payload["files"], payload["html"], payload["spec"])
        )
        return payload

    def make_version(self, project=None, **values):
        return Version.objects.create(
            project=project or self.project,
            number=1,
            prompt="Original",
            summary="Fixture",
            html=HTML,
            files=MODULES,
            validation=REPORT,
            spec={},
            **values,
        )

    def test_health_session_and_csrf_login(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.get("/api/health/").json(), {"status": "ok"})
        response = client.get("/api/projects/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")
        response = client.get("/api/auth/session/")
        self.assertEqual(response.json(), {"authenticated": False, "user": None})
        self.assertIn("csrftoken", client.cookies)
        response = client.post(
            "/api/auth/login/", {"username": "builder", "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        response = client.post(
            "/api/auth/login/",
            {"username": "builder", "password": "bad"},
            format="json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")
        response = client.post(
            "/api/auth/login/",
            {"username": "builder", "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["authenticated"])
        self.assertEqual(response.json()["user"]["id"], str(self.user.pk))
        self.assertEqual(
            client.post("/api/projects/", {"title": "X", "prompt": "Y"}, format="json").status_code,
            403,
        )
        response = client.post(
            "/api/projects/",
            {"title": "X", "prompt": "Y"},
            format="json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 201)
        response = client.post(
            "/api/auth/logout/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(client.get("/api/auth/session/").json()["authenticated"])

    def test_one_team_shares_projects_and_plain_arrays(self):
        other = User.objects.create_user(username="colleague", password=PASSWORD)
        self.team.force_login(other)
        response = self.team.get("/api/projects/")
        self.assertIsInstance(response.json(), list)
        self.assertEqual(response.json()[0]["id"], str(self.project.pk))
        response = self.team.patch(
            f"/api/projects/{self.project.pk}/", {"title": "Renamed"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Renamed")

    def test_job_bounds_and_active_unique_constraint(self):
        response = self.team.post(
            f"/api/projects/{self.project.pk}/jobs/",
            {"kind": "generate", "prompt": "x", "provider": "fixture"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        for override in ({"budget_tokens": 999}, {"max_repairs": 6}, {"prompt": ""}):
            response = self.team.post(
                f"/api/projects/{self.project.pk}/jobs/",
                {"kind": "generate", "prompt": "x", "provider": "codex", **override},
                format="json",
            )
            self.assertEqual(response.status_code, 400)
        job = self.make_job()
        self.assertEqual(job["max_repairs"], 2)
        response = self.team.post(
            f"/api/projects/{self.project.pk}/jobs/",
            {"kind": "generate", "prompt": "x", "provider": "codex"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "active_job")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Job.objects.create(project=self.project, kind="generate", prompt="x", provider="codex")

    def test_revision_base_is_same_project_and_explicit_null_not_latest(self):
        other = Project.objects.create(title="Other", prompt="Other")
        foreign = self.make_version(project=other)
        base = self.make_version()
        Project.objects.filter(pk=self.project.pk).update(latest_version=base)
        for base_id, expected in (
            (str(foreign.pk), "invalid_base_version"),
            (None, "missing_base_version"),
        ):
            response = self.team.post(
                f"/api/projects/{self.project.pk}/jobs/",
                {
                    "kind": "revise",
                    "prompt": "Improve",
                    "provider": "codex",
                    "base_version_id": base_id,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["code"], expected)
        job = self.make_job(kind="revise")
        self.assertEqual(job["base_version_id"], str(base.pk))
        claim = self.claim()
        self.assertEqual(claim["base_version"]["html"], HTML)
        self.assertEqual(claim["base_version"]["files"], MODULES)

    def test_reference_readonly(self):
        base = self.make_version(is_reference=True)
        response = self.team.post(
            f"/api/projects/{self.project.pk}/jobs/",
            {
                "kind": "revise",
                "prompt": "Edit",
                "provider": "codex",
                "base_version_id": str(base.pk),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "reference_readonly")

    def test_worker_requires_bearer_never_session(self):
        response = self.team.post(
            "/api/worker/claim/", {"capabilities": {"providers": ["codex"]}}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        # Conversely a runner cannot read the browser API with its machine token.
        self.assertEqual(self.worker.get("/api/projects/").status_code, 401)

    def test_runner_secret_one_time_and_revocation(self):
        response = self.team.post("/api/runners/", {"name": "Second"}, format="json")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertGreaterEqual(len(data["token"]), 43)
        runner = Runner.objects.get(pk=data["runner"]["id"])
        self.assertEqual(runner.token_hash, secret_hash(data["token"]))
        self.assertNotEqual(runner.token_hash, data["token"])
        listing = json.dumps(self.team.get("/api/runners/").json())
        self.assertNotIn(data["token"], listing)
        self.assertNotIn(runner.token_hash, listing)
        self.team.post(f"/api/runners/{self.runner.pk}/revoke/", {}, format="json")
        self.assertEqual(
            self.worker.post(
                "/api/worker/claim/", {"capabilities": {"providers": ["codex"]}}, format="json"
            ).status_code,
            401,
        )

    def test_claim_provider_match_double_claim_and_unique_lease(self):
        job = self.make_job()
        self.assertEqual(self.claim(providers=["openai"]), {"job": None})
        first = self.claim()
        self.assertEqual(first["job"]["id"], job["id"])
        self.assertEqual(first["job"]["status"], "running")
        self.assertEqual(self.claim(), {"job": None})
        saved = Job.objects.get(pk=job["id"])
        self.assertEqual(saved.lease_hash, secret_hash(first["lease_token"]))
        self.assertNotIn("lease_hash", first["job"])
        self.assertTrue(self.team.get("/api/runners/").json()[0]["online"])

    def test_checkpoint_survives_expired_reclaim_old_lease_fenced(self):
        job = self.make_job()
        first = self.claim()
        usage = dict(
            input_tokens=100, cached_input_tokens=30, output_tokens=50, total_tokens=150, calls=1
        )
        checkpoint = {
            "spec": {"title": "Dungeon"},
            "files": {"engine.js": "// complete"},
            "completed": ["engine"],
        }
        response = self.write(
            job, "checkpoint", first["lease_token"], checkpoint=checkpoint, usage=usage
        )
        self.assertEqual(response.status_code, 200, response.content)
        Job.objects.filter(pk=job["id"]).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        # Even before a reclaim an expired worker cannot publish.
        self.assertEqual(
            self.write(job, "complete", first["lease_token"], **self.completion()).status_code, 409
        )
        second = self.claim()
        self.assertNotEqual(second["lease_token"], first["lease_token"])
        self.assertEqual(second["checkpoint"], checkpoint)
        self.assertEqual(second["job"]["usage"], usage)
        self.assertEqual(self.write(job, "heartbeat", first["lease_token"]).status_code, 409)
        self.assertEqual(
            self.write(job, "complete", first["lease_token"], **self.completion()).status_code, 409
        )
        self.assertEqual(Version.objects.count(), 0)
        self.assertEqual(self.write(job, "heartbeat", second["lease_token"]).status_code, 200)

    def test_wrong_runner_cannot_use_stolen_lease(self):
        job = self.make_job()
        claim = self.claim()
        token = secrets.token_urlsafe(32)
        Runner.objects.create(name="Other", token_hash=secret_hash(token))
        self.worker.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.write(job, "heartbeat", claim["lease_token"]).status_code, 409)

    def test_cancel_fences_every_write_and_returns_readonly_notice(self):
        job = self.make_job()
        claim = self.claim()
        response = self.team.post(f"/api/jobs/{job['id']}/cancel/", {}, format="json")
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(
            self.write(job, "heartbeat", claim["lease_token"]).json(),
            {"cancelled": True, "lease_seconds": 0},
        )
        for action, data in (
            ("checkpoint", {"checkpoint": {"x": 1}}),
            ("events", {"stage": "engine", "progress": 20, "level": "info", "message": "late"}),
            ("fail", {"error": "late failure"}),
            ("complete", self.completion()),
        ):
            self.assertEqual(self.write(job, action, claim["lease_token"], **data).status_code, 409)
        self.assertEqual(Version.objects.count(), 0)
        self.assertEqual(self.claim(), {"job": None})
        newer = self.make_job(prompt="Try again")
        self.assertNotEqual(newer["id"], job["id"])

    def test_events_monotonic_filtering_progress_and_redaction(self):
        job = self.make_job()
        claim = self.claim()
        response = self.write(
            job,
            "events",
            claim["lease_token"],
            stage="engine",
            progress=25,
            level="info",
            message="Engine complete",
            data={"api_key": "secret", "reasoning": "hidden", "count": 1},
        )
        self.assertEqual(response.status_code, 201, response.content)
        event = response.json()
        self.assertEqual(event["data"]["api_key"], "[redacted]")
        self.assertEqual(event["data"]["reasoning"], "[redacted]")
        self.assertEqual(self.team.get(f"/api/jobs/{job['id']}/").json()["progress"], 25)
        events = self.team.get(f"/api/jobs/{job['id']}/events/").json()
        self.assertEqual([e["id"] for e in events], sorted(e["id"] for e in events))
        self.assertEqual(
            self.team.get(f"/api/jobs/{job['id']}/events/?after={event['id']}").json(), []
        )
        self.assertEqual(self.team.get(f"/api/jobs/{job['id']}/events/?after=bad").status_code, 400)

    def test_completion_atomic_immutable_numbered_and_double_completion(self):
        job = self.make_job()
        claim = self.claim()
        response = self.write(job, "complete", claim["lease_token"], **self.completion())
        self.assertEqual(response.status_code, 201, response.content)
        version = response.json()
        self.assertEqual(version["number"], 1)
        self.assertFalse(version["is_reference"])
        project = self.team.get(f"/api/projects/{self.project.pk}/").json()
        self.assertEqual(project["latest_version_id"], version["id"])
        self.assertIsNone(project["active_job"])
        saved = Job.objects.get(pk=job["id"])
        self.assertEqual(saved.status, "completed")
        self.assertEqual(str(saved.result_version_id), version["id"])
        self.assertEqual(
            self.write(job, "complete", claim["lease_token"], **self.completion()).status_code, 409
        )
        self.assertEqual(
            self.team.post(f"/api/jobs/{job['id']}/cancel/", {}, format="json").json()["status"],
            "completed",
        )
        detail = self.team.get(f"/api/versions/{version['id']}/").json()
        self.assertEqual(detail["files"], MODULES)
        self.assertEqual(detail["html"], HTML)
        self.assertEqual(
            self.team.patch(
                f"/api/versions/{version['id']}/", {"html": "mutate"}, format="json"
            ).status_code,
            405,
        )
        old = Version.objects.get(pk=version["id"])
        old.summary = "mutate"
        with self.assertRaises(DjangoValidationError):
            old.save()
        revised = self.make_job(kind="revise", prompt="Change color")
        next_claim = self.claim()
        second = self.write(revised, "complete", next_claim["lease_token"], **self.completion())
        self.assertEqual(second.json()["number"], 2)
        self.assertEqual(Version.objects.get(pk=version["id"]).summary, "Unit-test artifact")

    def test_failed_validation_and_unsafe_module_names_cannot_publish(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        cases = [
            {"validation": {**REPORT, "status": "failed"}},
            {"validation": {**REPORT, "errors": ["runtime crash"]}},
            {"validation": {**REPORT, "status": "passed"}},
            {"files": {**MODULES, "../secret.py": "exfiltrate"}},
            {"files": {**MODULES, "/tmp/evil.js": "bad"}},
            {"files": {"engine.js": "// missing other modules"}},
            {"html": "\x00"},
            {"usage": dict(input_tokens=10, cached_input_tokens=11)},
        ]
        for values in cases:
            payload = self.completion()
            payload.update(values)
            response = self.write(job, "complete", lease, **payload)
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Version.objects.count(), 0)
        self.assertEqual(Job.objects.get(pk=job["id"]).status, "running")

    def test_download_attachment_and_safe_source_archive(self):
        version = self.make_version()
        html = self.team.get(f"/api/versions/{version.pk}/download/")
        self.assertIn("attachment;", html["Content-Disposition"])
        self.assertIn("sandbox", html["Content-Security-Policy"])
        self.assertEqual(html["X-Content-Type-Options"], "nosniff")
        self.assertEqual(html.content.decode(), HTML)
        response = self.team.get(f"/api/versions/{version.pk}/source/")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                set(MODULES) | {"index.html", "spec.json", "validation.json", "manifest.json"},
            )
            self.assertEqual(archive.read("engine.js").decode(), MODULES["engine.js"])
            self.assertEqual(
                json.loads(archive.read("manifest.json"))["evidence_binding"], "legacy"
            )
        # Even corrupt storage cannot become a zip-slip archive.
        Version.objects.filter(pk=version.pk).update(files={"../../escape.js": "unsafe"})
        self.assertEqual(self.team.get(f"/api/versions/{version.pk}/source/").status_code, 400)

    def test_fail_is_terminal_and_new_job_allowed(self):
        original = self.make_version()
        Project.objects.filter(pk=self.project.pk).update(latest_version=original)
        job = self.make_job()
        lease = self.claim()["lease_token"]
        response = self.write(job, "fail", lease, error="Model unavailable")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "failed")
        self.assertEqual(response.json()["error"], "Model unavailable")
        self.assertEqual(self.write(job, "heartbeat", lease).status_code, 409)
        refreshed = self.team.get(f"/api/projects/{self.project.pk}/").json()
        self.assertIsNone(refreshed["active_job"])
        self.assertEqual(refreshed["latest_job"]["id"], job["id"])
        self.assertEqual(refreshed["latest_job"]["error"], "Model unavailable")
        self.assertEqual(refreshed["latest_version_id"], str(original.pk))
        self.assertEqual(Version.objects.get(pk=original.pk).html, HTML)
        self.make_job()

    def test_nonfinite_progress_is_rejected_before_database_write(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        self.worker.raise_request_exception = False
        response = self.write(
            job,
            "events",
            lease,
            stage="engine",
            progress="NaN",
            level="info",
            message="Invalid progress",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Job.objects.get(pk=job["id"]).progress, 0)

    def test_event_usage_counters_survive_credential_redaction(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        usage = {
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "output_tokens": 20,
            "total_tokens": 120,
        }
        response = self.write(
            job,
            "events",
            lease,
            stage="review",
            progress=80,
            level="info",
            message="Observed provider usage",
            data={
                "usage": usage,
                "api_token": "private",
                "nested": {"input_tokens": "not-a-counter", "cached_input_tokens": -1},
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["usage"], usage)
        self.assertEqual(data["api_token"], "[redacted]")
        self.assertEqual(
            data["nested"], {"input_tokens": "[redacted]", "cached_input_tokens": "[redacted]"}
        )

    def test_failure_credentials_are_redacted_in_job_and_project(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        response = self.write(job, "fail", lease, error="Request failed: Bearer private-credential")
        self.assertEqual(response.status_code, 200)
        for data in (
            response.json(),
            self.team.get(f"/api/jobs/{job['id']}/").json(),
            self.team.get(f"/api/projects/{self.project.pk}/").json(),
            self.team.get(f"/api/jobs/{job['id']}/events/").json(),
        ):
            self.assertNotIn("private-credential", json.dumps(data))
        self.assertNotIn("private-credential", Job.objects.get(pk=job["id"]).error)

    def test_omitted_terminal_usage_preserves_last_checkpoint_accounting(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        usage = dict(
            input_tokens=100, cached_input_tokens=20, output_tokens=50, total_tokens=150, calls=2
        )
        self.assertEqual(
            self.write(
                job, "checkpoint", lease, checkpoint={"saved": True}, usage=usage
            ).status_code,
            200,
        )
        self.assertEqual(
            self.write(job, "checkpoint", lease, checkpoint={"saved": "again"}).status_code, 200
        )
        self.assertEqual(Job.objects.get(pk=job["id"]).usage, usage)
        response = self.write(job, "fail", lease, error="Disconnected")
        self.assertEqual(response.json()["usage"], usage)

    def test_revision_uses_latest_at_job_creation_not_stale_project_read(self):
        from prompt2play.adapters.django.forge.services import create_job

        first = self.make_version()
        Project.objects.filter(pk=self.project.pk).update(latest_version=first)
        stale_project = Project.objects.get(pk=self.project.pk)
        second = Version.objects.create(project=self.project, number=2, prompt="New", html=HTML)
        Project.objects.filter(pk=self.project.pk).update(latest_version=second)
        job = create_job(
            stale_project, self.user, dict(kind="revise", provider="codex", prompt="Revise latest")
        )
        self.assertEqual(job.base_version_id, second.pk)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1024)
    def test_json_body_limit_applies_to_stream_parser(self):
        response = self.team.post(
            "/api/projects/",
            {"title": "Small fields", "prompt": "Small prompt", "unused": "x" * 2048},
            format="json",
        )
        self.assertEqual(response.status_code, 413, response.content)
        self.assertEqual(response.json()["code"], "payload_too_large")

    def test_empty_validation_cannot_claim_passed(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        payload = self.completion()
        payload["validation"] = dict(status="passed", checks=[], errors=[], warnings=[])
        self.assertEqual(self.write(job, "complete", lease, **payload).status_code, 400)

    def test_new_completions_require_bound_v2_reports_without_erasing_checkpoint(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        self.write(job, "checkpoint", lease, checkpoint={"retained": True})
        payload = self.completion(validation=REPORT)
        response = self.write(job, "complete", lease, **payload)
        self.assertEqual(response.status_code, 400, response.content)
        saved = Job.objects.get(pk=job["id"])
        self.assertEqual(saved.status, "running")
        self.assertEqual(saved.checkpoint, {"retained": True})
        self.assertEqual(Version.objects.count(), 0)

    def test_mismatched_artifact_inputs_checks_and_model_review_cannot_publish(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]

        def html_changed(p):
            p["html"] += "\n<!-- after validation -->"

        def source_changed(p):
            p["files"]["engine.js"] += "\n// after validation"

        def spec_changed(p):
            p["spec"]["title"] = "Different specification"

        def bytes_changed(p):
            p["validation"]["artifact"]["html_bytes"] += 1

        def check_changed(p):
            p["validation"]["checks"][0]["artifact_sha256"] = "0" * 64

        def review_changed(p):
            p["validation"]["review"]["artifact_sha256"] = "0" * 64

        def review_rejected(p):
            p["validation"]["review"]["approved"] = False

        for mutate in (
            html_changed,
            source_changed,
            spec_changed,
            bytes_changed,
            check_changed,
            review_changed,
            review_rejected,
        ):
            with self.subTest(mutation=mutate.__name__):
                payload = copy.deepcopy(self.completion())
                mutate(payload)
                response = self.write(job, "complete", lease, **payload)
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Version.objects.count(), 0)
        self.assertEqual(Job.objects.get(pk=job["id"]).status, "running")

    def test_evidence_metadata_survives_completion_and_source_zip_matches_saved_bytes(self):
        from prompt2play.adapters.django.forge.artifacts import artifact_manifest

        job = self.make_job()
        lease = self.claim()["lease_token"]
        payload = self.completion(html=HTML.replace("Fixture", "Янтарь"))
        check = payload["validation"]["checks"][0]
        check.update(
            scenario_id="survival",
            affected_files=["engine.js", "ui.js"],
            command="fixture-runner survival",
            limitations=["DOM fixture; not a browser."],
            evidence={"assertions": 4, "seed": 20261011},
        )
        payload["validation"]["review"]["issues"] = [
            {
                "file": "ui.js",
                "severity": "warning",
                "message": "Listening remains manual.",
                "scope": "integration",
                "affected_files": ["ui.js", "audio.js"],
                "contract_ids": ["music-gain"],
                "reproduction": "Start and change volume.",
                "expected": "Independent gain buses.",
                "observed": "Synthetic test only.",
                "regression_scenario_id": "audio-controls",
            }
        ]
        payload["validation"]["provenance"] = {
            "calls": [{"role": "review", "prompt_sha256": "b" * 64}],
            "iterations": [{"cycle": 0}],
            "module_summaries": {"engine": "Pure rules", "ui": "Inputs and lifecycle"},
        }
        response = self.write(job, "complete", lease, **payload)
        self.assertEqual(response.status_code, 201, response.content)
        result = response.json()
        self.assertEqual(result["validation"]["checks"][0], check)
        self.assertEqual(result["validation"]["review"], payload["validation"]["review"])
        self.assertEqual(result["validation"]["provenance"], payload["validation"]["provenance"])
        detail = self.team.get(f"/api/versions/{result['id']}/").json()
        self.assertEqual(detail["validation"]["binding_status"], "verified")
        with zipfile.ZipFile(
            io.BytesIO(self.team.get(f"/api/versions/{result['id']}/source/").content)
        ) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            files = {name: archive.read(name).decode("utf-8") for name in MODULES}
            self.assertEqual(
                manifest["artifact"],
                artifact_manifest(
                    files,
                    archive.read("index.html").decode("utf-8"),
                    json.loads(archive.read("spec.json")),
                ),
            )
            self.assertEqual(manifest["evidence_binding"], "verified")
        done = Job.objects.get(pk=job["id"]).events.last()
        self.assertEqual(done.data["artifact"], payload["validation"]["artifact"])

    def test_corrupt_bound_storage_is_visible_and_cannot_be_exported_as_checked(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        response = self.write(job, "complete", lease, **self.completion())
        version_id = response.json()["id"]
        Version.objects.filter(pk=version_id).update(html=HTML + "\nchanged")
        detail = self.team.get(f"/api/versions/{version_id}/").json()
        self.assertEqual(detail["validation"]["status"], "failed")
        self.assertEqual(detail["validation"]["binding_status"], "mismatch")
        for action in ("download", "source"):
            response = self.team.get(f"/api/versions/{version_id}/{action}/")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["code"], "artifact_mismatch")

    def test_legacy_read_is_annotated_without_mutating_the_stored_version(self):
        version = self.make_version()
        Version.objects.filter(pk=version.pk).update(validation={**REPORT, "status": "passed"})
        result = self.team.get(f"/api/versions/{version.pk}/").json()
        self.assertEqual(result["validation"]["status"], "partial")
        self.assertEqual(result["validation"]["binding_status"], "legacy")
        version.refresh_from_db()
        self.assertEqual(version.validation["status"], "passed")
        self.assertNotIn("binding_status", version.validation)
        self.assertEqual(self.team.get(f"/api/versions/{version.pk}/download/").status_code, 200)

    def test_new_budget_default_preserves_explicit_values(self):
        job = self.make_job()
        self.assertEqual(job["budget_tokens"], 400000)
        self.team.post(f"/api/jobs/{job['id']}/cancel/", {}, format="json")
        explicit = self.make_job(budget_tokens=180000)
        self.assertEqual(explicit["budget_tokens"], 180000)

    def test_static_or_model_only_report_cannot_claim_full_runtime_validation(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        payload = self.completion()
        report = payload["validation"]
        report["status"] = "passed"
        report["checks"] = report["checks"][:1]
        for kind in ("static", "syntax", "model_review"):
            report["checks"][0]["check_kind"] = kind
            self.assertEqual(self.write(job, "complete", lease, **payload).status_code, 400)

    def test_omitted_planned_scenarios_prevent_full_pass_claim(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        payload = self.completion(spec={"qa_scenarios": [{"id": "restore-progress"}]})
        report = payload["validation"]
        report["status"] = "passed"
        report["checks"] = [{**report["checks"][0], "check_kind": "browser"}]
        response = self.write(job, "complete", lease, **payload)
        self.assertEqual(response.status_code, 400, response.content)
        report["status"] = "partial"
        self.assertEqual(self.write(job, "complete", lease, **payload).status_code, 201)

    def test_summary_polling_does_not_load_artifacts_or_checkpoints(self):
        version = self.make_version()
        Project.objects.filter(pk=self.project.pk).update(latest_version=version)
        job = self.make_job()
        for path in (
            "/api/projects/",
            f"/api/projects/{self.project.pk}/",
            f"/api/projects/{self.project.pk}/versions/",
            f"/api/jobs/{job['id']}/",
        ):
            with self.subTest(path=path), CaptureQueriesContext(connection) as captured:
                response = self.team.get(path)
                self.assertEqual(response.status_code, 200)
                sql = "\n".join(q["sql"] for q in captured if q["sql"].startswith("SELECT"))
                for heavy_field in ('"html"', '"files"', '"checkpoint"'):
                    self.assertNotIn(heavy_field, sql)

    def test_project_list_uses_bounded_queries_for_last_jobs(self):
        for index in range(6):
            project = Project.objects.create(title=f"Project {index}", prompt="History")
            for _ in range(3):
                Job.objects.create(
                    project=project,
                    kind="generate",
                    provider="codex",
                    prompt="Old",
                    status="failed",
                )
        with CaptureQueriesContext(connection) as captured:
            response = self.team.get("/api/projects/")
            self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(captured), 4)  # session, user, projects, one bounded related query
        for project in response.json():
            if project["id"] != str(self.project.pk):
                self.assertEqual(project["latest_job"]["status"], "failed")
                self.assertIsNone(project["active_job"])

    def test_completion_without_usage_keeps_checkpoint_metrics_on_version(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        usage = dict(
            input_tokens=100, cached_input_tokens=20, output_tokens=50, total_tokens=150, calls=2
        )
        self.write(job, "checkpoint", lease, checkpoint={"saved": True}, usage=usage)
        payload = self.completion()
        del payload["usage"]
        response = self.write(job, "complete", lease, **payload)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["usage"], usage)
        self.assertEqual(Job.objects.get(pk=job["id"]).usage, usage)

    def test_inconsistent_usage_total_cannot_replace_saved_accounting(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        usage = dict(
            input_tokens=100, cached_input_tokens=20, output_tokens=50, total_tokens=150, calls=2
        )
        self.write(job, "checkpoint", lease, checkpoint={"saved": True}, usage=usage)
        for invalid in ({"input_tokens": 100, "output_tokens": 10}, {**usage, "total_tokens": 151}):
            response = self.write(job, "checkpoint", lease, checkpoint={}, usage=invalid)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(Job.objects.get(pk=job["id"]).usage, usage)

    def test_stale_same_lease_checkpoint_preserves_usage_and_checkpoint_atomically(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        usage = dict(
            input_tokens=100, cached_input_tokens=20, output_tokens=50, total_tokens=150, calls=2
        )
        self.assertEqual(
            self.write(
                job, "checkpoint", lease, checkpoint={"saved": "newer"}, usage=usage
            ).status_code,
            200,
        )
        saved = Job.objects.get(pk=job["id"])
        # Every provider counter is cumulative. Even when total spend increases,
        # cached tokens or completed calls may not fall back to an older value.
        stale = [
            dict(usage, input_tokens=90, total_tokens=140),
            dict(usage, output_tokens=40, total_tokens=140),
            dict(usage, input_tokens=110, total_tokens=160, cached_input_tokens=19),
            dict(usage, input_tokens=110, total_tokens=160, calls=1),
        ]
        for old_usage in stale:
            with self.subTest(usage=old_usage):
                response = self.write(
                    job, "checkpoint", lease, checkpoint={"saved": "older"}, usage=old_usage
                )
                self.assertEqual(response.status_code, 409, response.content)
                self.assertEqual(response.json()["code"], "stale_usage")
                fresh = Job.objects.get(pk=job["id"])
                self.assertEqual(fresh.usage, usage)
                self.assertEqual(fresh.checkpoint, {"saved": "newer"})
                self.assertEqual(
                    fresh.updated_at, saved.updated_at, "a rejected write must roll back its fence"
                )
        self.assertEqual(
            self.write(
                job, "checkpoint", lease, checkpoint={"saved": "same counters"}, usage=usage
            ).status_code,
            200,
        )
        self.assertEqual(Job.objects.get(pk=job["id"]).checkpoint, {"saved": "same counters"})

    def test_stale_completion_cannot_publish_or_erase_checkpoint_usage(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        usage = dict(
            input_tokens=100, cached_input_tokens=20, output_tokens=50, total_tokens=150, calls=2
        )
        self.write(job, "checkpoint", lease, checkpoint={"saved": True}, usage=usage)
        events = Event.objects.filter(job_id=job["id"]).count()
        response = self.write(job, "complete", lease, **self.completion())
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["code"], "stale_usage")
        saved = Job.objects.get(pk=job["id"])
        self.assertEqual(
            (saved.status, saved.usage, saved.checkpoint), ("running", usage, {"saved": True})
        )
        self.assertIsNone(saved.result_version_id)
        self.project.refresh_from_db()
        self.assertIsNone(self.project.latest_version_id)
        self.assertFalse(Version.objects.filter(project=self.project).exists())
        self.assertEqual(Event.objects.filter(job_id=job["id"]).count(), events)
        response = self.write(job, "complete", lease, **self.completion(usage=usage))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["usage"], usage)

    def test_stale_failure_preserves_live_job_and_known_usage(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        usage = dict(
            input_tokens=100, cached_input_tokens=20, output_tokens=50, total_tokens=150, calls=2
        )
        self.write(job, "checkpoint", lease, checkpoint={"saved": True}, usage=usage)
        events = Event.objects.filter(job_id=job["id"]).count()
        response = self.write(
            job, "fail", lease, error="An earlier request arrived late", usage=empty_usage()
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["code"], "stale_usage")
        saved = Job.objects.get(pk=job["id"])
        self.assertEqual(
            (saved.status, saved.usage, saved.checkpoint), ("running", usage, {"saved": True})
        )
        self.assertEqual(saved.error, "")
        self.assertEqual(Event.objects.filter(job_id=job["id"]).count(), events)
        response = self.write(job, "fail", lease, error="Confirmed failure", usage=usage)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["status"], response.json()["usage"]), ("failed", usage))

    def test_requires_job_model_skips_incompatible_head_and_keeps_fifo(self):
        waiting = self.make_job(provider="openai")
        second = Project.objects.create(title="Second", prompt="With model")
        named = Job.objects.create(
            project=second,
            kind="generate",
            provider="openai",
            model="selected-model",
            prompt="Ready",
        )
        third = Project.objects.create(title="Third", prompt="Codex")
        codex = Job.objects.create(project=third, kind="generate", provider="codex", prompt="Ready")
        capabilities = {"providers": ["openai", "codex"], "requires_job_model": ["openai"]}
        response = self.worker.post(
            "/api/worker/claim/", {"capabilities": capabilities}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["job"]["id"], str(named.pk))
        response = self.worker.post(
            "/api/worker/claim/", {"capabilities": capabilities}, format="json"
        )
        self.assertEqual(response.json()["job"]["id"], str(codex.pk))
        self.assertEqual(Job.objects.get(pk=waiting["id"]).status, "queued")
        self.assertEqual(self.claim(providers=["openai"])["job"]["id"], waiting["id"])

    def test_requires_job_model_validates_capability_subset(self):
        for requires in ("openai", ["openai"], ["codex", "codex"], [{}]):
            response = self.worker.post(
                "/api/worker/claim/",
                {"capabilities": {"providers": ["codex"], "requires_job_model": requires}},
                format="json",
            )
            self.assertEqual(response.status_code, 400, response.content)

    def test_readiness_checks_database_without_leaking_driver_error(self):
        client = APIClient()
        self.assertEqual(client.get("/api/ready/").json(), {"status": "ok"})
        with patch(
            "forge.views.connection.cursor", side_effect=DatabaseError("secret-driver-connection")
        ):
            response = client.get("/api/ready/")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["code"], "not_ready")
            self.assertNotIn("secret-driver-connection", response.content.decode())
            self.assertEqual(client.get("/api/health/").json(), {"status": "ok"})

    def test_json_parser_keeps_normal_errors_and_enforces_utf8_bytes(self):
        response = self.team.post("/api/projects/", b"{broken", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "parse_error")
        body = json.dumps({"title": "Valid", "prompt": "\u044f" * 60}, ensure_ascii=False).encode()
        with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=len(body)):
            self.assertEqual(
                self.team.post("/api/projects/", body, content_type="application/json").status_code,
                201,
            )
        with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=len(body) - 1):
            self.assertEqual(
                self.team.post("/api/projects/", body, content_type="application/json").status_code,
                413,
            )

    def test_excessively_nested_json_is_bad_request_not_server_failure(self):
        self.team.raise_request_exception = False
        body = b'{"unused":' + b"[" * 200000 + b"0" + b"]" * 200000 + b"}"
        response = self.team.post("/api/projects/", body, content_type="application/json")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "parse_error")

    def test_revoked_runner_job_can_be_reclaimed_without_old_publication(self):
        job = self.make_job()
        lease = self.claim()["lease_token"]
        self.team.post(f"/api/runners/{self.runner.pk}/revoke/", {}, format="json")
        self.assertEqual(self.write(job, "complete", lease, **self.completion()).status_code, 401)
        token = secrets.token_urlsafe(32)
        Runner.objects.create(name="Replacement", token_hash=secret_hash(token))
        self.worker.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.claim()["job"]["id"], job["id"])

    def test_frontend_csp_and_api_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "index.html").write_text("<html>studio</html>")
            with override_settings(FRONTEND_DIST=Path(directory)):
                response = self.team.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("frame-src 'self'", response["Content-Security-Policy"])
            # Direct WhiteNoise entry must enforce the same iframe boundary.
            with override_settings(WHITENOISE_ROOT=Path(directory), STATIC_ROOT=Path(directory)):
                direct = APIClient().get("/index.html")
                self.assertEqual(direct.status_code, 200)
                self.assertIn("frame-src 'self'", direct["Content-Security-Policy"])
                self.assertEqual(direct["Cache-Control"], "no-cache")
                direct.close()
        response = self.team.get("/api/not-a-route/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not_found")

    def test_bootstrap_idempotent_password_and_explicit_reference_import(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.html"
            reference.write_text(HTML)
            (reference.parent / "music.js").write_text("// historic audio source")
            output = io.StringIO()
            with patch.dict(os.environ, {"TEST_BOOTSTRAP_PASSWORD": PASSWORD}):
                call_command(
                    "bootstrap",
                    username="admin",
                    password_env="TEST_BOOTSTRAP_PASSWORD",
                    noinput=True,
                    import_reference=True,
                    reference_file=str(reference),
                    stdout=output,
                )
            admin = User.objects.get(username="admin")
            self.assertTrue(admin.is_staff and admin.is_superuser)
            self.assertTrue(admin.check_password(PASSWORD))
            with patch.dict(os.environ, {"TEST_BOOTSTRAP_PASSWORD": "Different-Password-678!"}):
                call_command(
                    "bootstrap",
                    username="admin",
                    password_env="TEST_BOOTSTRAP_PASSWORD",
                    noinput=True,
                    import_reference=True,
                    reference_file=str(reference),
                    stdout=output,
                )
            admin.refresh_from_db()
            self.assertTrue(admin.check_password(PASSWORD))
            self.assertEqual(Version.objects.filter(is_reference=True).count(), 1)
            self.assertEqual(Version.objects.get(is_reference=True).validation["status"], "partial")
            self.assertEqual(
                Version.objects.get(is_reference=True).files["audio.js"], "// historic audio source"
            )
