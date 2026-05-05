"""Unified vision-provider configuration via pydantic-settings.

Reads from environment / .env.  Set VISION_PROVIDER to "groq" or "openai".
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VisionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(".env"),
        env_ignore_empty=True,
        extra="ignore",
    )

    # Reads VISION_PROVIDER from env / .env
    provider: Literal["groq", "openai"] = Field(default="groq", validation_alias="vision_provider")

    # --- Groq ---
    groq_api_key: str = ""
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # --- Shared ---
    temperature: float = 0.1
    max_retries: int = 3


def get_vision_settings() -> VisionSettings:
    """Load settings fresh each call so .env changes are always picked up."""
    return VisionSettings()
