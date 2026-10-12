"""Contract boundary tests."""

import pytest
from pydantic import ValidationError

from prompt2play.config import Settings
from prompt2play.contracts import CreateProjectRequest, Finding, ValidationReport


def test_prompt_is_trimmed_and_bounded() -> None:
    request = CreateProjectRequest(prompt="  Сделай космический раннер  ")
    assert request.prompt == "Сделай космический раннер"
    with pytest.raises(ValidationError):
        CreateProjectRequest(prompt="short")


def test_validation_report_defaults_to_unverified_browser() -> None:
    report = ValidationReport(
        passed=False,
        static_passed=False,
        findings=[
            Finding(
                code="TEST",
                severity="error",
                message="broken",
                repair_hint="fix it",
            )
        ],
    )
    assert report.browser_status == "unverified"
    assert report.findings[0].code == "TEST"


def test_settings_parse_origins_and_keep_luna_default() -> None:
    settings = Settings(cors_origins="https://one.test, https://two.test")
    assert settings.openai_model == "gpt-6-luna"
    assert settings.cors_origin_list == ["https://one.test", "https://two.test"]
