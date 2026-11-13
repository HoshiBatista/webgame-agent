from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

from generation.audiences import AUDIENCES
from generation.errors import ContractError

from .analytics import KEY, summary
from .models import AnalyticsDataset
from .services import DomainError


@api_view(["GET"])
def analytics_summary_view(request):
    if not settings.GAMEFORGE_ANALYTICS_ENABLED:
        raise DomainError("analytics_disabled", "Аналитика отключена.", 404)
    audience = request.query_params.get("audience", "everyone")
    if audience not in AUDIENCES:
        raise DomainError("invalid_audience", "Неизвестная аудитория.")
    dataset = AnalyticsDataset.objects.filter(key=KEY, enabled=True).first()
    if dataset is None:
        return Response({"dataset": None, "audience": audience, "groups": [],
                         "recommendations": [], "data_status": "empty", "policy_version": 1})
    try:
        return Response(summary(dataset, audience))
    except (ValueError, TypeError, ContractError) as exc:
        raise DomainError("analytics_unavailable", "Данные аналитики временно недоступны.", 503) from exc
