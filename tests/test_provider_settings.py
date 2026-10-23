import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize("provider,model", [("codex", "gpt-6-luna"), ("vllm", "qwen38"), ("relay", "qwen38")])
def test_llm_aliases_do_not_replace_codex_selection(monkeypatch, provider, model):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    monkeypatch.setenv("DJANGO_SECRET_KEY", "isolated-configuration-test")
    monkeypatch.setenv("GAMEFORGE_PROVIDER", provider)
    monkeypatch.setenv("GAMEFORGE_MODEL", "")
    monkeypatch.setenv("GAMEFORGE_VLLM_MODEL", "")
    monkeypatch.setenv("LLM_MODEL", "qwen38")
    values = runpy.run_path(str(Path(__file__).resolve().parents[1] / "gameforge/settings.py"))
    assert values["GAMEFORGE_PROVIDER"] == provider
    assert values["GAMEFORGE_MODEL"] == model


@pytest.mark.parametrize("value", ["0", "1", "4", "999", "invalid"])
def test_repair_limit_cannot_create_an_unbounded_new_run(monkeypatch, value):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    monkeypatch.setenv("GAMEFORGE_MAX_REPAIR_ATTEMPTS", value)
    with pytest.raises(ValueError):
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "gameforge/settings.py"))
