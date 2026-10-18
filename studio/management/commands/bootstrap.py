import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction


class Command(BaseCommand):
    help = "Create the initial administrator after migrations. Existing passwords are never replaced."

    def handle(self, *args, **kwargs):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not username or not password:
            raise CommandError("Set DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD.")
        if len(password) < 10:
            raise CommandError("Administrator password must have at least ten characters.")
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            self.stdout.write("Administrator account already exists; credentials unchanged.")
            return
        try:
            with transaction.atomic():
                User.objects.create_superuser(
                    username=username, password=password, email=os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
                )
        except IntegrityError:
            if not User.objects.filter(username__iexact=username).exists():
                raise
        self.stdout.write("Administrator initialized.")
