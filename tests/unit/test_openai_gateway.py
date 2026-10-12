"""OpenAI adapter tests without network calls or credentials."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import prompt2play.adapters.openai_gateway as gateway_module
from prompt2play.adapters.openai_gateway import OpenAIModelGateway
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

    def __init__(self, **_: object) -> None:
        self.responses = FakeResponses()
        FakeOpenAI.instance = self


def test_gateway_requires_api_key() -> None:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIModelGateway(Settings(openai_api_key=None))


def test_gateway_uses_luna_structured_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway_module, "OpenAI", FakeOpenAI)
    gateway = OpenAIModelGateway(Settings(openai_api_key=SecretStr("test")))
    specified = gateway.specify("Сделай раннер", "no analytics")
    generated = gateway.generate(
        "Сделай раннер",
        specified.value,
        parent_html="<!doctype html><p>old</p>",
        revision_instruction="Крупнее",
        findings="BROKEN",
    )
    assert gateway.model_name == "gpt-6-luna"
    assert generated.input_tokens == 12
    assert generated.output_tokens == 34
    assert generated.response_id == "resp_test"
    assert FakeOpenAI.instance is not None
    calls = FakeOpenAI.instance.responses.calls
    assert calls[0]["model"] == "gpt-6-luna"
    assert calls[0]["text_format"] is GameSpec
    assert "<previous_game_source>" in str(calls[1]["input"])
