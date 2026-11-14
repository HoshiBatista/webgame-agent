from django.urls import path

from studio.views import health_view, preview_view

urlpatterns = [path("health/", health_view), path("preview/<str:token>/", preview_view)]
