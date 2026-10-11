"""Explicitly authored API fixtures, not real model or browser results."""

from prompt2play.adapters.django.forge.artifacts import artifact_manifest


def bound_report(files, html, spec):
    manifest = artifact_manifest(files, html, spec)
    return {
        "schema_version": 2,
        "status": "partial",
        "artifact": manifest,
        "checks": [
            {
                "name": "fixture_syntax",
                "status": "passed",
                "message": "Authored test fixture.",
                "check_kind": "syntax",
                "artifact_sha256": manifest["html_sha256"],
                "limitations": ["Fixture only."],
                "evidence": {"fixture": True},
            },
            {
                "name": "fixture_browser",
                "status": "skipped",
                "message": "No browser in unit tests.",
                "check_kind": "browser_runtime",
                "artifact_sha256": manifest["html_sha256"],
                "limitations": ["No browser executed."],
                "evidence": {},
            },
        ],
        "errors": [],
        "warnings": ["No browser validation."],
        "review": {
            "approved": True,
            "summary": "Authored review fixture.",
            "issues": [],
            "provider": "fixture",
            "model": "fixture",
            "contract_sha256": spec.get("generation", {}).get("contract_sha256", "a" * 64),
            "prompt_sha256": "b" * 64,
            "artifact_sha256": manifest["html_sha256"],
        },
        "provenance": {"calls": [], "iterations": []},
    }
