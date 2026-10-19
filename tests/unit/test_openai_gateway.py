"""OpenAI adapter tests without network calls or credentials."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import prompt2play.adapters.openai_gateway as gateway_module
from prompt2play.adapters.model_gateway import build_model_gateway
from prompt2play.adapters.openai_gateway import OpenAIModelGateway, VLLMModelGateway
from prompt2play.config import Settings
from prompt2play.contracts import GameSpec, GeneratedGame, Rubric


def spec() -> GameSpec:
    return GameSpec(
        title="Runner",
        genre="runner",
        audience="все",
        player_goal="Добежать до финиша",
        core_loop="Прыгать через препятствия",
        controls=["touch"],
        visual_direction="Контрастный неон",
        accessibility=["крупные кнопки"],
        win_condition="Финиш",
        lose_condition="Нет жизней",
        rubrics=[
            Rubric(id=str(index), description="Проверка механики", verification="bridge")
            for index in range(3)
        ],
    )


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        output_type = kwargs["text_format"]
        parsed = (
            spec()
            if output_type is GameSpec
            else GeneratedGame(
                title="Runner", summary="Playable runner", html="<!doctype html>" + "x" * 1000
            )
        )
        return SimpleNamespace(
            output_parsed=parsed,
            id="resp_test",
            usage=SimpleNamespace(input_tokens=12, output_tokens=34),
        )


class FakeOpenAI:
    instance: "FakeOpenAI | None" = None

    def __init__(self, **kwargs: object) -> None:
        self.options = kwargs
        self.responses = FakeResponses()
        FakeOpenAI.instance = self


def test_gateway_requires_api_key() -> None:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIModelGateway(Settings(openai_api_key=None, openai_model="hosted-model"))
    with pytest.raises(RuntimeError, match="P2P_VLLM_API_KEY"):
        VLLMModelGateway(Settings(vllm_api_key=None))


def test_openai_gateway_uses_structured_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway_module, "OpenAI", FakeOpenAI)
    gateway = OpenAIModelGateway(
        Settings(openai_api_key=SecretStr("test"), openai_model="hosted-model")
    )
    specified = gateway.specify("Сделай раннер", "no analytics")
    generated = gateway.generate(
        "Сделай раннер",
        specified.value,
        parent_html="<!doctype html><p>old</p>",
        revision_instruction="Крупнее",
        findings="BROKEN",
        feedback_context="music priority=6",
    )
    assert gateway.model_name == "hosted-model"
    assert generated.input_tokens == 12
    assert generated.output_tokens == 34
    assert generated.response_id == "resp_test"
    assert FakeOpenAI.instance is not None
    calls = FakeOpenAI.instance.responses.calls
    assert calls[0]["model"] == "hosted-model"
    assert "reasoning" in calls[0]
    assert calls[0]["max_output_tokens"] == 64_000
    assert calls[0]["text_format"] is GameSpec
    assert "<previous_game_source>" in str(calls[1]["input"])
    assert "<untrusted_creator_feedback>" in str(calls[1]["input"])


def test_vllm_connector_uses_base_url_without_openai_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway_module, "OpenAI", FakeOpenAI)
    settings = Settings(
        model_provider="vllm",
        vllm_api_key=SecretStr("internal-token"),
        vllm_base_url="https://models.internal.example/v1",
        vllm_model="company/code-model",
    )

    gateway = build_model_gateway(settings)
    result = gateway.specify("Сделай раннер", "no analytics")

    assert isinstance(gateway, VLLMModelGateway)
    assert gateway.model_name == "company/code-model"
    assert result.response_id == "resp_test"
    assert FakeOpenAI.instance is not None
    assert FakeOpenAI.instance.options["base_url"] == "https://models.internal.example/v1/"
    call = FakeOpenAI.instance.responses.calls[0]
    assert call["model"] == "company/code-model"
    assert call["text_format"] is GameSpec
    assert "reasoning" not in call
