"""Infrastructure-independent application ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from prompt2play.contracts import GameSpec, GeneratedGame

OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True)
class ModelResult(Generic[OutputT]):
    """Typed provider output with metering information."""

    value: OutputT
    response_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class ModelGateway(Protocol):
    """Provider-independent interface used by the workflow."""

    @property
    def model_name(self) -> str:
        """Return the configured provenance identifier."""

    def specify(self, prompt: str, analytics_context: str) -> ModelResult[GameSpec]:
        """Convert an untrusted user prompt to a validated game specification."""

    def generate(
        self,
        prompt: str,
        spec: GameSpec,
        *,
        parent_html: str | None = None,
        revision_instruction: str | None = None,
        findings: str | None = None,
    ) -> ModelResult[GeneratedGame]:
        """Generate or repair one complete self-contained game candidate."""
