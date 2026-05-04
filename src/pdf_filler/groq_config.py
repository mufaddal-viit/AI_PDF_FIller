"""Groq configuration using pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class GroqSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(".env"),
        env_ignore_empty=True,
        extra="ignore",
    )

    groq_api_key: str
    model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    base_url: str = "https://api.groq.com/openai/v1"
    temperature: float = 0.1
    max_retries: int = 3


@lru_cache(maxsize=1)
def get_settings() -> GroqSettings:
    """Lazy singleton — only loads .env when first called."""
    return GroqSettings()
