import getpass
import os
from pathlib import Path

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from prompt2play.adapters.django.forge.models import Project, User, Version, empty_usage
from prompt2play.adapters.django.forge.serializers import MIB, MODULE_NAMES, validate_files
from prompt2play.paths import LEGACY_ROOT


class Command(BaseCommand):
    help = "Создать администратора доверенной команды и, по желанию, импортировать эталон."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password-env", default="FORGE_ADMIN_PASSWORD")
        parser.add_argument("--noinput", action="store_true")
        parser.add_argument("--reset-password", action="store_true")
        parser.add_argument("--import-reference", action="store_true")
        parser.add_argument(
            "--reference-file",
            default=str(LEGACY_ROOT / "reference" / "Ashen_Vault.html"),
        )

    def handle(self, *args, **options):
        username = options["username"].strip()
        if not username or len(username) > 150:
            raise CommandError("Укажите username длиной 1–150 символов.")
        user = User.objects.filter(username=username).first()
        new = user is None
        user = user or User(username=username)
        if new or options["reset_password"]:
            password = os.environ.get(options["password_env"], "")
            if not password and not options["noinput"]:
                password = getpass.getpass("Новый пароль администратора: ")
                if password != getpass.getpass("Повторите пароль: "):
                    raise CommandError("Пароли не совпадают.")
            if not password:
                raise CommandError(
                    f"Задайте {options['password_env']} или запустите без --noinput."
                )
            try:
                validate_password(password, user=user)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()
        self.stdout.write(
            self.style.SUCCESS(f"Администратор {username}: {'создан' if new else 'доступен'}.")
        )
        if not new and not options["reset_password"]:
            self.stdout.write(
                "Существующий пароль сохранён; для смены используйте --reset-password."
            )
        if options["import_reference"]:
            self.import_reference(Path(options["reference_file"]), user)

    def import_reference(self, path, user):
        existing = Version.objects.filter(is_reference=True).first()
        if existing:
            self.stdout.write(f"Эталон уже импортирован: {existing.project_id}.")
            return
        if not path.is_file():
            raise CommandError(f"Файл эталона не найден: {path}")
        if path.stat().st_size > 8 * MIB:
            raise CommandError("HTML эталона превышает 8 MiB.")
        html = path.read_text(encoding="utf-8")
        files = {}
        for name in MODULE_NAMES:
            module = path.parent / name
            if module.is_file():
                files[name] = module.read_text(encoding="utf-8")
        # Historical example uses music.js; expose it under the safe export allowlist.
        # The reference remains readonly because its class interfaces predate GameAudio.
        if "audio.js" not in files and (path.parent / "music.js").is_file():
            files["audio.js"] = (path.parent / "music.js").read_text(encoding="utf-8")
        validate_files(files, required=False)
        report = {
            "status": "partial",
            "checks": [
                {
                    "name": "reference_import",
                    "status": "passed",
                    "message": "Явно импортирован авторский пример.",
                },
                {
                    "name": "browser_runtime",
                    "status": "skipped",
                    "message": "Импорт не запускает игру и не проверяет её в WebView.",
                },
            ],
            "errors": [],
            "warnings": [
                "Эталон создан отдельно. Это не результат текущего генератора и не гарантия качества будущих игр."
            ],
        }
        with transaction.atomic():
            project = Project.objects.create(
                title="Пепельный свод — эталон",
                prompt="Авторский пример автономной HTML5-игры: пошаговый roguelike с процедурными этажами, анимацией и музыкой.",
                created_by=user,
            )
            version = Version.objects.create(
                project=project,
                number=1,
                prompt=project.prompt,
                summary="Эталон для просмотра и сравнения. Старые интерфейсы модулей; правки генератором отключены.",
                is_reference=True,
                validation=report,
                usage=empty_usage(),
                spec={"title": "Пепельный свод", "reference": True, "editable": False},
                files=files,
                html=html,
            )
            Project.objects.filter(pk=project.pk).update(latest_version=version)
        self.stdout.write(self.style.SUCCESS(f"Эталон импортирован: {project.pk}."))
