"""Application configuration loaded exclusively from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="P2P_", env_file=".env", extra="ignore", case_sensitive=False
    )

    environment: str = "development"
    database_url: str = "postgresql+psycopg://prompt2play:prompt2play@localhost:5432/prompt2play"
    redis_url: str = "redis://localhost:6379/0"
    artifact_root: Path = Path("artifacts")
    validation_root: Path = Path("artifacts/private")
    model_provider: Literal["vllm", "openai"] = "vllm"
    model_max_output_tokens: int = Field(default=64_000, ge=1000, le=128_000)
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str | None = None
    openai_timeout_seconds: float = 120.0
    openai_reasoning_effort: str = "medium"
    vllm_base_url: str = "http://vllm:8000/v1"
    vllm_api_key: SecretStr | None = None
    vllm_model: str = "prompt2play-code"
    vllm_timeout_seconds: float = 180.0
    max_repair_attempts: int = Field(default=2, ge=0, le=3)
    stage_lease_seconds: int = Field(default=600, ge=300, le=3600)
    browser_validation: bool = True
    browser_timeout_ms: int = Field(default=12_000, ge=1000, le=60_000)
    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173"
    session_cookie_name: str = "p2p_session"
    session_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)
    admin_username: str | None = None
    admin_password: SecretStr | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        """Return normalized allowed creator origins."""

        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return one immutable process-local settings instance."""

    return Settings()
