"""Configuration-driven model connector selection."""

from prompt2play.adapters.openai_gateway import OpenAIModelGateway, VLLMModelGateway
from prompt2play.application.ports import ModelGateway
from prompt2play.config import Settings


def build_model_gateway(settings: Settings) -> ModelGateway:
    """Build exactly one configured provider adapter for a model worker."""

    if settings.model_provider == "vllm":
        return VLLMModelGateway(settings)
    if settings.model_provider == "openai":
        return OpenAIModelGateway(settings)
    raise ValueError(f"Unsupported model provider: {settings.model_provider}")
