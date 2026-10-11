import importlib.util
from django.conf import settings
from django.test import SimpleTestCase

from prompt2play.adapters.django.forge.artifacts import artifact_manifest


class ArtifactInteropTests(SimpleTestCase):
    def test_coordinator_and_worker_hash_exactly_the_same_unicode_and_spec_values(self):
        path = settings.PROJECT_ROOT / "validator" / "evidence.py"
        if not path.is_file():
            self.skipTest("Worker source is not part of the minimal coordinator image.")
        module_spec = importlib.util.spec_from_file_location("forge_validator_evidence_test", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        files = {"ui.js": "// Привет\n", "engine.js": "class GameEngine {}\r\n"}
        html = "<!doctype html><title>Янтарь 🏰</title>\n"
        spec = {
            "generation": {"model": "", "contract_sha256": "a" * 64},
            "nested": {"z": True, "a": [None, 0, 1.0, "e\u0301", "é"]},
            "title": "Пример",
        }
        self.assertEqual(
            artifact_manifest(files, html, spec), module.artifact_manifest(files, html, spec)
        )
        self.assertEqual(
            artifact_manifest(files, html, spec)["html_bytes"], len(html.encode("utf-8"))
        )
        for source, document, plan in (
            (files, html + " ", spec),
            ({**files, "ui.js": "// Привет"}, html, spec),
            (files, html, {**spec, "title": "Другой"}),
        ):
            self.assertNotEqual(
                artifact_manifest(files, html, spec), artifact_manifest(source, document, plan)
            )

    def test_nonfinite_or_invalid_values_cannot_receive_a_manifest(self):
        for spec in ({"bad": float("nan")}, {"bad": float("inf")}):
            with self.assertRaises(ValueError):
                artifact_manifest({}, "<html/>", spec)
        with self.assertRaises(ValueError):
            artifact_manifest({"ui.js": {}}, "<html/>", {})
