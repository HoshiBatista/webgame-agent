"""Scoped preview delivery, exposed solely by the separate preview listener."""

from urllib.parse import urlparse

from django.conf import settings
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from .artifacts import require_report_binding
from .models import Version
from .errors import Conflict
from .workflow import candidate_payload, version_eligible, version_reviewable

SALT = "prompt2play.preview.v1"


def preview_url(version):
    if settings.PREVIEW_ORIGIN == settings.APP_ORIGIN:
        return None
    token = signing.dumps(
        {
            "version": str(version.pk),
            "candidate": str(version.candidate_id),
            "artifact": version.candidate.artifact_key,
        },
        salt=SALT,
        compress=True,
    )
    return f"{settings.PREVIEW_ORIGIN}/preview/{version.pk}/?token={token}"


def preview(request, pk):
    if request.method != "GET":
        return HttpResponse(status=405)
    # This URLconf is never mounted in the coordinator. Also pin its configured host.
    if request.get_host() != urlparse(settings.PREVIEW_ORIGIN).netloc:
        return HttpResponse("Preview host mismatch.", status=403)
    try:
        claims = signing.loads(request.GET.get("token", ""), salt=SALT, max_age=600)
    except signing.BadSignature:
        return HttpResponse("Preview link expired or invalid.", status=403)
    version = get_object_or_404(Version, pk=pk, candidate__committed=True)
    if not (version_eligible(version) or version_reviewable(version)):
        return HttpResponse("Required validation is unavailable.", status=409)
    if claims != {
        "version": str(version.pk),
        "candidate": str(version.candidate_id),
        "artifact": version.candidate.artifact_key,
    }:
        return HttpResponse("Preview scope mismatch.", status=403)
    try:
        payload = candidate_payload(version.candidate)
        if version.spec != payload["spec"]:
            raise ValueError("Stored specification differs from its immutable candidate.")
        require_report_binding(
            payload["files"], payload["html"], payload["spec"], version.validation
        )
    except (ValueError, KeyError, TypeError, Conflict):
        return HttpResponse("Artifact validation mismatch.", status=409)
    response = HttpResponse(payload["html"], content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; "
        f"frame-ancestors {settings.APP_ORIGIN}; sandbox allow-scripts allow-pointer-lock"
    )
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    return response


class IsolationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Cookies are ignored even when development origins differ only by port.
        request.META.pop("HTTP_COOKIE", None)
        request.COOKIES.clear()
        response = self.get_response(request)
        response.cookies.clear()
        return response
