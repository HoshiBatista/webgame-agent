"""Publish model display metadata without sharing the Codex credential directory."""

import json
import os
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from generation.providers.codex import codex_home


class Command(BaseCommand):
    help = "Export non-secret Codex model metadata for a separate web process. Does not call the model."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            source = json.loads((codex_home() / "models_cache.json").read_text())
            models = source["models"]
            if not isinstance(models, list) or not models:
                raise ValueError("empty catalog")
            fields = {"slug", "display_name", "visibility", "supported_reasoning_levels", "default_reasoning_level"}
            public = []
            for model in models:
                if not isinstance(model, dict) or not isinstance(model.get("slug"), str):
                    raise ValueError("invalid model")
                public.append({key: value for key, value in model.items() if key in fields})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise CommandError("Codex model cache is missing or invalid; export was not replaced.") from exc
        target = Path(options["output"])
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"models": public}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        except OSError as exc:
            raise CommandError("Could not write Codex display catalog.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.stdout.write(f"Exported {len(public)} model entries; no credentials copied.")
