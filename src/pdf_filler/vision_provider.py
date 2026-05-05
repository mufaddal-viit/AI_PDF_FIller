"""Vision-provider abstraction — Groq and OpenAI backends.

Both providers expose the same interface:
    call_for_page(template_id, png_path, page_no, total_pages) -> dict
"""
from __future__ import annotations

import base64
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .groq_prompt import get_system_prompt, get_user_prompt
from .logging_config import get_logger
from .vision_config import VisionSettings

_LOGGER = get_logger(__name__)


def _png_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


class VisionProvider(ABC):
    """Abstract base — one method to implement."""

    @abstractmethod
    def call_for_page(
        self,
        template_id: str,
        png_path: Path,
        page_no: int,
        total_pages: int,
    ) -> dict[str, Any]:
        """Return the raw fields dict for a single page."""


class GroqVisionProvider(VisionProvider):
    def __init__(self, cfg: VisionSettings) -> None:
        import groq as _groq  # lazy import

        self._client = _groq.Groq(api_key=cfg.groq_api_key)
        self._cfg = cfg

    def call_for_page(
        self,
        template_id: str,
        png_path: Path,
        page_no: int,
        total_pages: int,
    ) -> dict[str, Any]:
        cfg = self._cfg
        messages = [
            {"role": "system", "content": get_system_prompt(template_id, page_no)},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": get_user_prompt(page_no, total_pages)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_png_b64(png_path)}"},
                    },
                ],
            },
        ]
        return _retry(
            lambda: self._client.chat.completions.create(
                model=cfg.groq_model,
                messages=messages,
                temperature=cfg.temperature,
                response_format={"type": "json_object"},
                max_tokens=4096,
            ),
            cfg.max_retries,
            page_no,
        )


class OpenAIVisionProvider(VisionProvider):
    def __init__(self, cfg: VisionSettings) -> None:
        import openai as _openai  # lazy import

        self._client = _openai.OpenAI(api_key=cfg.openai_api_key)
        self._cfg = cfg

    def call_for_page(
        self,
        template_id: str,
        png_path: Path,
        page_no: int,
        total_pages: int,
    ) -> dict[str, Any]:
        cfg = self._cfg
        messages = [
            {"role": "system", "content": get_system_prompt(template_id, page_no)},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": get_user_prompt(page_no, total_pages)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_png_b64(png_path)}"},
                    },
                ],
            },
        ]
        return _retry(
            lambda: self._client.chat.completions.create(
                model=cfg.openai_model,
                messages=messages,
                temperature=cfg.temperature,
                max_completion_tokens=4096,
            ),
            cfg.max_retries,
            page_no,
        )


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that some models wrap around JSON."""
    text = text.strip()
    if text.startswith("```"):
        # drop opening fence line and closing fence
        lines = text.splitlines()
        start = 1  # skip ```json or ```
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
    return text


def _retry(api_call: Any, max_retries: int, page_no: int) -> dict[str, Any]:
    """Execute api_call, parse JSON, retry on soft failures."""
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(1, max_retries + 1):
        try:
            resp = api_call()
            content = resp.choices[0].message.content
            if not content:
                raise ValueError("Empty response from provider")
            finish_reason = resp.choices[0].finish_reason
            if finish_reason == "length":
                raise ValueError("Response truncated (finish_reason=length); increase max_tokens")
            content = _strip_fences(content)
            raw: dict[str, Any] = json.loads(content)
            fields = raw.get("fields", raw)
            if not isinstance(fields, dict) or not fields:
                raise ValueError(f"Expected non-empty fields dict, got: {type(fields)}")
            _LOGGER.info("Page %d: %d field(s) extracted", page_no, len(fields))
            return fields
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_exc = exc
            _LOGGER.warning("Page %d attempt %d/%d failed: %s", page_no, attempt, max_retries, exc)
            if attempt == max_retries:
                raise RuntimeError(
                    f"Page {page_no}: all {max_retries} attempts failed. Last error: {exc}"
                ) from exc
    raise last_exc


def build_provider(cfg: VisionSettings) -> VisionProvider:
    """Factory — returns the right provider based on cfg.provider."""
    if cfg.provider == "groq":
        if not cfg.groq_api_key:
            raise ValueError("GROQ_API_KEY is not set in .env / environment.")
        return GroqVisionProvider(cfg)
    if cfg.provider == "openai":
        if not cfg.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set in .env / environment.")
        return OpenAIVisionProvider(cfg)
    raise ValueError(f"Unknown provider: {cfg.provider!r}")
