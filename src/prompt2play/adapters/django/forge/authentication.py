import hashlib
import hmac

from rest_framework.authentication import (
    BaseAuthentication,
    SessionAuthentication,
    get_authorization_header,
)
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from .models import Runner


def secret_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TeamSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request):
        return "Session"

    def enforce_csrf(self, request):
        try:
            return super().enforce_csrf(request)
        except PermissionDenied as exc:
            raise PermissionDenied(
                "Проверка CSRF не пройдена. Обновите страницу.", code="csrf_failed"
            ) from exc


class RunnerAuthentication(BaseAuthentication):
    """Worker routes deliberately never accept Django sessions or CSRF cookies."""

    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0].lower() != b"bearer" or len(parts[1]) > 256:
            raise AuthenticationFailed("Неверный токен исполнителя.", code="invalid_runner_token")
        try:
            supplied = parts[1].decode("ascii")
        except UnicodeDecodeError as exc:
            raise AuthenticationFailed(
                "Неверный токен исполнителя.", code="invalid_runner_token"
            ) from exc
        digest = secret_hash(supplied)
        runner = Runner.objects.filter(token_hash=digest).first()
        expected = runner.token_hash if runner else "0" * 64
        matches = hmac.compare_digest(digest, expected)
        if not runner or not matches or runner.revoked:
            raise AuthenticationFailed(
                "Токен исполнителя недействителен или отозван.", code="invalid_runner_token"
            )
        return runner, digest
