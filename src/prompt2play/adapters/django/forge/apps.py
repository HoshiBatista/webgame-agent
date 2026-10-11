from django.apps import AppConfig


class ForgeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "prompt2play.adapters.django.forge"
    label = "forge"
