"""Contract boundary tests."""

import pytest
from pydantic import ValidationError

from prompt2play.config import Settings
from prompt2play.contracts import (
    CreateProjectRequest,
    FeedbackReason,
    Finding,
    SubmitFeedbackRequest,
    ValidationReport,
)


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
    assert report.validator_version == "2"
    assert report.findings[0].code == "TEST"


def test_settings_parse_origins_and_default_to_vllm_connector() -> None:
    settings = Settings(cors_origins="https://one.test, https://two.test")
    assert settings.model_provider == "vllm"
    assert settings.vllm_model == "prompt2play-code"
    assert settings.openai_model is None
    assert settings.cors_origin_list == ["https://one.test", "https://two.test"]


def test_low_feedback_rating_requires_an_actionable_signal() -> None:
    with pytest.raises(ValidationError):
        SubmitFeedbackRequest(rating=3)
    request = SubmitFeedbackRequest(
        rating=3,
        reasons=[FeedbackReason.MUSIC],
        comment="  Не хватает крутой музыки  ",
    )
    assert request.comment == "Не хватает крутой музыки"
