"""Groq vision API client — generates CoordinateMap from page-guide PNGs.

Processes one page at a time (one API call per PNG) to:
- avoid multi-image context limits
- focus the model on a single page for better accuracy
- reduce tokens per call
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import groq

from .groq_config import get_settings
from .groq_prompt import get_system_prompt, get_user_prompt
from .logging_config import get_logger
from .models import CoordinateMap

_LOGGER = get_logger(__name__)


def load_page_guides(guides_dir: Path) -> list[Path]:
    """Return sorted page_NN_guide.png paths from guides_dir."""
    if not guides_dir.exists():
        raise ValueError(f"Guides dir not found: {guides_dir}")

    pngs = sorted(
        guides_dir.glob("page_*_guide.png"),
        key=lambda p: int(p.stem.split("_")[1]),  # page_01_guide → 1
    )
    if not pngs:
        raise ValueError(f"No page_*_guide.png files in {guides_dir}")
    _LOGGER.info("Found %d page guides: %s", len(pngs), [p.name for p in pngs])
    return pngs


def _png_to_image_block(path: Path) -> dict[str, Any]:
    """Encode PNG as a base64 image_url block for the Groq vision API."""
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64}"},
    }


def _call_groq_for_page(
    client: groq.Groq,
    template_id: str,
    png_path: Path,
    page_no: int,
    total_pages: int,
) -> dict[str, Any]:
    """One Groq vision call for a single page; returns the raw fields dict."""
    cfg = get_settings()
    messages = [
        {"role": "system", "content": get_system_prompt(template_id, page_no)},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": get_user_prompt(page_no, total_pages)},
                _png_to_image_block(png_path),
            ],
        },
    ]

    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(1, cfg.max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=cfg.model,
                messages=messages,
                temperature=cfg.temperature,
                response_format={"type": "json_object"},
                max_tokens=2048,
            )
            content = resp.choices[0].message.content
            if not content:
                raise ValueError("Empty response from Groq")

            raw: dict[str, Any] = json.loads(content)
            # Model may return a full CoordinateMap object or just the fields dict.
            fields = raw.get("fields", raw)
            if not isinstance(fields, dict) or not fields:
                raise ValueError(f"Expected non-empty fields dict, got: {type(fields)}")

            _LOGGER.info("Page %d: %d field(s) extracted", page_no, len(fields))
            return fields

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_exc = exc
            _LOGGER.warning("Page %d attempt %d/%d failed: %s", page_no, attempt, cfg.max_retries, exc)
            if attempt == cfg.max_retries:
                raise RuntimeError(
                    f"Page {page_no}: all {cfg.max_retries} attempts failed. Last error: {exc}"
                ) from exc

    raise last_exc


def generate_coordinate_map(
    template_id: str,
    guides_dir: Path,
    version: str = "auto-v1",
    page_size: str = "A4",
) -> CoordinateMap:
    """Generate a CoordinateMap by calling Groq vision once per page guide PNG."""
    cfg = get_settings()
    client = groq.Groq(api_key=cfg.groq_api_key, base_url=cfg.base_url)

    png_paths = load_page_guides(guides_dir)
    total = len(png_paths)
    all_fields: dict[str, Any] = {}

    for page_no, png_path in enumerate(png_paths, start=1):
        page_fields = _call_groq_for_page(client, template_id, png_path, page_no, total)
        # Stamp page number on any field that forgot it.
        for fdata in page_fields.values():
            if isinstance(fdata, dict):
                fdata.setdefault("page", page_no)
        all_fields.update(page_fields)

    payload = {
        "template_id": template_id,
        "template_version": version,
        "page_size": page_size,
        "coordinate_system": "pymupdf",
        "units": "points",
        "fields": all_fields,
    }
    coord_map = CoordinateMap.model_validate(payload)
    _LOGGER.info(
        "Coordinate map ready: %d fields across %d page(s)", len(coord_map.fields), total
    )
    return coord_map
