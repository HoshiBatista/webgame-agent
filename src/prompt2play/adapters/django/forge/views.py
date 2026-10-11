import io
import json
import secrets
import zipfile

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import RunnerAuthentication, secret_hash
from .artifacts import artifact_manifest, require_report_binding
from .errors import Conflict
from .models import Candidate, Event, Job, Project, Runner, Version
from .middleware import PARENT_CSP
from .queries import public_jobs, public_projects
from .representations import event_data, job_data, project_data, runner_data, version_data
from .serializers import (
    CheckpointSerializer,
    ClaimSerializer,
    CompleteSerializer,
    EventCreateSerializer,
    FailSerializer,
    JobCreateSerializer,
    LeaseSerializer,
    LoginSerializer,
    ProjectCreateSerializer,
    ProjectUpdateSerializer,
    RunnerCreateSerializer,
    validate_files,
)
from . import services
from . import workflow
from .serializers import (
    CandidateSerializer,
    InvocationAccountSerializer,
    CandidateValidationSerializer,
    ReserveSerializer,
    SettleSerializer,
)


def validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def session_data(user, request):
    return {
        "csrf_token": get_token(request),
        "authenticated": bool(user.is_authenticated),
        "user": {
            "id": str(user.pk),
            "username": user.username,
            "is_staff": user.is_staff,
        }
        if user.is_authenticated
        else None,
    }


class TeamView(APIView):
    throttle_scope = "team"

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        services.expire_jobs()


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class ReadyView(HealthView):
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError:
            # Never expose a driver exception, connection string or credentials.
            return Response({"error": "База данных недоступна.", "code": "not_ready"}, status=503)
        return Response({"status": "ok"})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(TeamView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(session_data(request.user, request))


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "login"

    def post(self, request):
        data = validated(LoginSerializer, request.data)
        user = authenticate(request, **data)
        if user is None:
            raise AuthenticationFailed("Неверный логин или пароль.", code="invalid_credentials")
        login(request, user)
        return Response(session_data(user, request))

    def get_authenticate_header(self, request):
        return "Session"


class LogoutView(TeamView):
    def post(self, request):
        logout(request)
        return Response({"ok": True})


class ProjectsView(TeamView):
    def get(self, request):
        return Response([project_data(p) for p in public_projects()])

    def post(self, request):
        project = Project.objects.create(
            created_by=request.user, **validated(ProjectCreateSerializer, request.data)
        )
        return Response(project_data(project), status=201)


class ProjectView(TeamView):
    def get(self, request, pk):
        return Response(project_data(get_object_or_404(public_projects(), pk=pk)))

    def patch(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        project.title = validated(ProjectUpdateSerializer, request.data)["title"]
        project.save(update_fields=["title", "updated_at"])
        return Response(project_data(project))


class ProjectVersionsView(TeamView):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        return Response([version_data(v) for v in project.versions.defer("files", "html")])


class ProjectJobsView(TeamView):
    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        job = services.create_job(
            project, request.user, validated(JobCreateSerializer, request.data)
        )
        return Response(job_data(job), status=201)


class JobView(TeamView):
    def get(self, request, pk):
        return Response(job_data(get_object_or_404(public_jobs(), pk=pk)))


class JobEventsView(TeamView):
    def get(self, request, pk):
        job = get_object_or_404(Job.objects.only("id"), pk=pk)
        try:
            after = int(request.query_params.get("after", "0"))
            if after < 0 or after > 2**63 - 1:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError("after должен быть неотрицательным целым числом.")
        return Response([event_data(e) for e in job.events.filter(id__gt=after)[:1000]])


class JobCancelView(TeamView):
    def post(self, request, pk):
        return Response(job_data(services.cancel_job(pk)))


class JobCandidatesView(TeamView):
    def get(self, request, pk):
        job = get_object_or_404(Job, pk=pk)
        return Response([workflow.candidate_data(candidate) for candidate in job.candidates.all()])


class CandidateView(TeamView):
    def get(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        return Response(workflow.candidate_data(candidate, detail=True))


class VersionView(TeamView):
    def get(self, request, pk):
        return Response(version_data(get_object_or_404(Version, pk=pk), detail=True))


def attachment_response(content, content_type, filename):
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox; frame-ancestors 'none'"
    return response


class VersionDownloadView(TeamView):
    def get(self, request, pk):
        version = get_object_or_404(Version, pk=pk)
        if not workflow.version_eligible(version):
            raise Conflict("Версия не прошла обязательную проверку.", code="validation_required")
        export_manifest(version)
        payload = (
            workflow.candidate_payload(version.candidate)
            if version.candidate_id
            else {"html": version.html}
        )
        return attachment_response(
            payload["html"],
            "text/html; charset=utf-8",
            f"game-{version.project_id}-v{version.number}.html",
        )


def export_manifest(version):
    """Capture and compare the same in-memory strings later written to the ZIP."""
    try:
        payload = (
            workflow.candidate_payload(version.candidate)
            if version.candidate_id
            else {"files": version.files, "html": version.html, "spec": version.spec}
        )
        if version.candidate_id and version.spec != payload["spec"]:
            raise ValueError("Stored specification differs from its immutable candidate.")
        if isinstance(version.validation, dict) and version.validation.get("schema_version") == 2:
            artifact = require_report_binding(
                payload["files"], payload["html"], payload["spec"], version.validation
            )
            binding = "verified"
        else:
            artifact = artifact_manifest(version.files, version.html, version.spec)
            binding = "legacy"
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        raise Conflict(
            "Сохранённые файлы не соответствуют отчёту. Повторите проверку в новой версии.",
            code="artifact_mismatch",
        ) from exc
    return {"format": "game-forge-source-v2", "artifact": artifact, "evidence_binding": binding}


class VersionSourceView(TeamView):
    def get(self, request, pk):
        version = get_object_or_404(Version, pk=pk)
        # Revalidate on export too: admin/database/import are separate trust boundaries.
        payload = (
            workflow.candidate_payload(version.candidate)
            if version.candidate_id
            else {"files": validate_files(version.files, required=False), "html": version.html}
        )
        files = payload["files"]
        manifest = export_manifest(version)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                archive.writestr(name, content)
            archive.writestr("index.html", payload["html"])
            archive.writestr("spec.json", json.dumps(version.spec, ensure_ascii=False, indent=2))
            archive.writestr(
                "validation.json", json.dumps(version.validation, ensure_ascii=False, indent=2)
            )
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return attachment_response(
            stream.getvalue(),
            "application/zip",
            f"game-{version.project_id}-v{version.number}-source.zip",
        )


class RunnersView(TeamView):
    def get(self, request):
        return Response([runner_data(r) for r in Runner.objects.all()])

    def post(self, request):
        data = validated(RunnerCreateSerializer, request.data)
        if data["role"] == "validator" and not request.user.is_staff:
            raise PermissionDenied("Only team administrators can authorize validators.")
        token = secrets.token_urlsafe(32)
        runner = Runner.objects.create(
            created_by=request.user, token_hash=secret_hash(token), **data
        )
        return Response({"runner": runner_data(runner), "token": token}, status=201)


class RunnerRevokeView(TeamView):
    def post(self, request, pk):
        with transaction.atomic():
            Runner.objects.filter(pk=pk).update(revoked=True)
            runner = get_object_or_404(Runner, pk=pk)
            runner.revoked = True
        # Do not hold Runner then Job locks: worker writes lock Job then Runner.
        # Revocation is already committed and fences writes even if this cleanup fails.
        Job.objects.filter(runner_id=pk, status="running").update(lease_expires_at=timezone.now())
        return Response(runner_data(runner))


class WorkerView(APIView):
    authentication_classes = [RunnerAuthentication]
    throttle_scope = "worker"

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        services.expire_jobs()


class ClaimView(WorkerView):
    def post(self, request):
        values = validated(ClaimSerializer, request.data)
        job, lease = services.claim_job(request.user, **values)
        if job is None:
            return Response({"job": None})
        worker_job = job_data(job)
        worker_job["checkpoint"] = job.checkpoint
        return Response(
            {
                "job": worker_job,
                "lease_token": lease,
                "lease_seconds": settings.FORGE_LEASE_SECONDS,
                "checkpoint": job.checkpoint,
                "project": project_data(job.project),
                "base_version": version_data(job.base_version, detail=True)
                if job.base_version_id
                else None,
                "candidate": workflow.candidate_data(job.active_candidate, detail=True)
                if job.active_candidate_id
                else None,
            }
        )


class HeartbeatView(WorkerView):
    def post(self, request, pk):
        data = validated(LeaseSerializer, request.data)
        return Response(services.heartbeat(pk, request.user, data["lease_token"]))


class WorkerEventsView(WorkerView):
    def post(self, request, pk):
        data = validated(EventCreateSerializer, request.data)
        with transaction.atomic():
            job = services.fence(pk, request.user, data.pop("lease_token"))
            data["stage"] = job.stage
            data.pop("progress")
            data = services.scrub_log(data)
            data["message"] = data["message"][:2000]
            item = Event.objects.create(job=job, **data)
        return Response(event_data(item), status=201)


class CheckpointView(WorkerView):
    def post(self, request, pk):
        data = validated(CheckpointSerializer, request.data)
        if any(key in data.get("checkpoint", {}) for key in ("html", "files", "state")):
            raise ValidationError("Store source bytes through the candidate protocol.")
        with transaction.atomic():
            services.fence(pk, request.user, data.pop("lease_token"), **data)
        return Response({"ok": True})


class CompleteView(WorkerView):
    def post(self, request, pk):
        version = services.complete_job(
            pk, request.user, validated(CompleteSerializer, request.data)
        )
        return Response(version_data(version), status=201)


class CandidateSubmitView(WorkerView):
    def post(self, request, pk):
        candidate = workflow.submit_candidate(
            pk, request.user, validated(CandidateSerializer, request.data)
        )
        return Response(workflow.candidate_data(candidate), status=201)


class InvocationReserveView(WorkerView):
    def post(self, request, pk):
        invocation = workflow.reserve_invocation(
            pk, request.user, validated(ReserveSerializer, request.data)
        )
        return Response(workflow.invocation_data(invocation), status=201)


class InvocationSettleView(WorkerView):
    def post(self, request, pk):
        invocation = workflow.settle_invocation(
            pk, request.user, validated(SettleSerializer, request.data)
        )
        return Response(workflow.invocation_data(invocation))


class InvocationAccountView(WorkerView):
    def post(self, request, pk):
        invocation = workflow.account_invocation(
            pk, request.user, validated(InvocationAccountSerializer, request.data)
        )
        # Accounting cannot disclose a stale source response.
        return Response({"id": str(invocation.pk), "actual_usage": invocation.actual_usage})


class CandidateValidateView(WorkerView):
    def post(self, request, pk):
        version = workflow.validate_candidate(
            pk, request.user, validated(CandidateValidationSerializer, request.data)
        )
        return Response(version_data(version), status=201)


class FailView(WorkerView):
    def post(self, request, pk):
        data = validated(FailSerializer, request.data)
        data["error"] = services.scrub_log(data["error"])[:4000]
        with transaction.atomic():
            job = services.fence(
                pk,
                request.user,
                data.pop("lease_token"),
                status="failed",
                lease_hash="",
                lease_expires_at=None,
                **data,
            )
            services.event(job, data["error"][:2000], level="error")
        return Response(job_data(job))


def frontend(request):
    index = settings.FRONTEND_DIST / "index.html"
    if not index.is_file():
        return HttpResponse(
            "React build отсутствует. Выполните npm ci && npm run build в frontend/.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    response = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = PARENT_CSP
    response["Cache-Control"] = "no-cache"
    return response
