from django.urls import path

from prompt2play.adapters.django.forge.preview import preview

urlpatterns = [path("preview/<uuid:pk>/", preview)]
