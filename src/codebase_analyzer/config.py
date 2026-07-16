from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str | None = None
    llm_model: str = "gpt-4.1-mini"
    llm_base_url: str | None = None
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_input_tokens: int = Field(default=12_000, ge=1_000)
    reserved_output_tokens: int = Field(default=1_800, ge=256)
    max_file_bytes: int = Field(default=300_000, ge=10_000)
    llm_max_retries: int = Field(default=3, ge=1, le=10)
    llm_request_delay_seconds: float = Field(default=0.0, ge=0.0)
    llm_request_timeout_seconds: float = Field(default=90.0, ge=10.0)
    cache_dir: Path = Path(".analysis-cache")

    @model_validator(mode="after")
    def validate_token_budget(self) -> "Settings":
        if self.reserved_output_tokens >= self.max_input_tokens:
            raise ValueError("RESERVED_OUTPUT_TOKENS must be less than MAX_INPUT_TOKENS")
        return self

    @property
    def usable_input_tokens(self) -> int:
        return self.max_input_tokens - self.reserved_output_tokens
