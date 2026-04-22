"""Application settings from environment (.env optional)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    debug: bool = Field(default=False, description="Expose /sample-claims and demo fixtures")

    max_upload_bytes: int = Field(default=15 * 1024 * 1024, ge=1024)

    upload_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / ".cache" / "uploads"
    )

    groq_api_key: str | None = None
    groq_model: str = "qwen/qwen3-32b"

    # Shorter system prompt saves input tokens. Groq often returns HTTP 413 when a request exceeds tier TPM/token limits.
    groq_compact_system_prompt: bool = Field(default=True)

    # Hard cap on document characters sent to Groq (before JSON sizing). Lower if 413 persists on free tier.
    groq_max_document_chars: int = Field(default=12_000, ge=500, le=500_000)

    # Completion budget; lower values reduce "requested tokens" on some Groq tiers.
    groq_max_tokens: int = Field(default=4096, ge=256, le=32_768)

    # Serialized JSON body budget (bytes) for httpx; secondary to token caps above.
    groq_max_request_body_bytes: int = Field(default=28_000, ge=8_192, le=500_000)

    document_text_max_chars: int = Field(default=32_000, ge=4000, le=200_000)

    llm_timeout_seconds: float = 120.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
