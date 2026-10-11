from django.contrib import admin
from django.urls import include, path, re_path
from prompt2play.adapters.django.forge.errors import api_not_found
from prompt2play.adapters.django.forge.views import frontend

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("prompt2play.adapters.django.forge.urls")),
    re_path(r"^api/.*$", api_not_found),
    path("", frontend),
]
