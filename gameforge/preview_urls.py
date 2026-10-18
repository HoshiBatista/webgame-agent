from django.urls import path

from studio.views import preview_view

urlpatterns = [path("preview/<str:token>/", preview_view)]
