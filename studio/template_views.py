"""Private prompt drafts. CRUD never creates a game or calls a model."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import PromptTemplate
from .services import DomainError

TITLE_LIMIT = 60
DESCRIPTION_LIMIT = 2500


def template_data(template):
    return {"id": str(template.id), "title": template.title, "description": template.description,
            "created_at": template.created_at.isoformat(), "updated_at": template.updated_at.isoformat()}


def template_fields(data, *, partial=False):
    if not isinstance(data, dict):
        raise DomainError("invalid_template", "Укажите название и описание шаблона.")
    fields = {}
    for name, limit, label in (("title", TITLE_LIMIT, "Название"),
                               ("description", DESCRIPTION_LIMIT, "Описание")):
        if partial and name not in data:
            continue
        value = data.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise DomainError("invalid_template", f"{label} шаблона: от 1 до {limit} символов.")
        fields[name] = value.strip()
    return fields


@api_view(["GET", "POST"])
def templates_view(request):
    if request.method == "POST":
        template = PromptTemplate.objects.create(owner=request.user, **template_fields(request.data))
        return Response(template_data(template), status=201)
    templates = PromptTemplate.objects.filter(owner=request.user)
    query = request.query_params.get("q", "").strip()
    if query:
        templates = templates.filter(title__icontains=query)
    return Response({"results": [template_data(template) for template in templates]})


@api_view(["GET", "PATCH", "DELETE"])
def template_view(request, ident):
    with transaction.atomic():
        template = get_object_or_404(PromptTemplate.objects.select_for_update(), pk=ident, owner=request.user)
        if request.method == "DELETE":
            template.delete()
            return Response(status=204)
        if request.method == "PATCH":
            fields = template_fields(request.data, partial=True)
            for name, value in fields.items():
                setattr(template, name, value)
            if fields:
                template.save(update_fields=[*fields, "updated_at"])
        return Response(template_data(template))
