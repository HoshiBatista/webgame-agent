from django.http import JsonResponse
from django.core.exceptions import RequestDataTooBig
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class Conflict(APIException):
    status_code = 409
    default_detail = "Состояние изменилось. Обновите данные."
    default_code = "conflict"


def _flatten(value):
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_flatten(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "; ".join(_flatten(item) for item in value)
    return str(value)


def exception_handler(exc, context):
    if isinstance(exc, RequestDataTooBig):
        return Response(
            {"error": "Тело запроса превышает допустимый размер.", "code": "payload_too_large"},
            status=413,
        )
    response = drf_exception_handler(exc, context)
    if response is not None:
        code = exc.get_codes() if hasattr(exc, "get_codes") else "error"
        if (
            isinstance(code, list)
            and code
            and all(item == code[0] for item in code)
            and isinstance(code[0], str)
        ):
            code = code[0]
        if not isinstance(code, str):
            code = "validation_error"
        detail = (
            response.data.get("detail", response.data)
            if isinstance(response.data, dict)
            else response.data
        )
        response.data = {"error": _flatten(detail), "code": code}
    return response


def csrf_failure(request, reason=""):
    return JsonResponse(
        {"error": "Проверка CSRF не пройдена. Обновите страницу.", "code": "csrf_failed"},
        status=403,
    )


def api_not_found(request, path=""):
    return JsonResponse({"error": "API-маршрут не найден.", "code": "not_found"}, status=404)
