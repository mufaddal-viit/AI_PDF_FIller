"""Vision API client — generates CoordinateMap from page-guide PNGs.

Processes one page at a time (one API call per PNG) to:
- avoid multi-image context limits
- focus the model on a single page for better accuracy
- reduce tokens per call

Provider is selected via cfg.provider ("groq" or "openai").
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .logging_config import get_logger
from .models import CoordinateMap
from .vision_config import VisionSettings, get_vision_settings
from .vision_provider import VisionProvider, build_provider

_LOGGER = get_logger(__name__)


def load_page_guides(guides_dir: Path) -> list[Path]:
    """Return sorted page_NN_guide.png paths from guides_dir."""
    if not guides_dir.exists():
        raise ValueError(f"Guides dir not found: {guides_dir}")

    pngs = sorted(
        guides_dir.glob("page_*_guide.png"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    if not pngs:
        raise ValueError(f"No page_*_guide.png files in {guides_dir}")
    _LOGGER.info("Found %d page guides: %s", len(pngs), [p.name for p in pngs])
    return pngs


def generate_coordinate_map(
    template_id: str,
    guides_dir: Path,
    version: str = "auto-v1",
    page_size: str = "A4",
    max_pages: int | None = None,
    *,
    provider: str | None = None,
    cfg: VisionSettings | None = None,
) -> CoordinateMap:
    """Generate a CoordinateMap by calling the vision provider once per page guide PNG.

    Args:
        provider: Override the provider ("groq" or "openai"). If None, uses
                  cfg.provider or the VISION_PROVIDER env var (default "groq").
        cfg:      Pass a pre-built VisionSettings to skip env loading (useful in tests).
    """
    if cfg is None:
        cfg = get_vision_settings()

    # Allow a per-call provider override without mutating the cached settings.
    if provider is not None and provider != cfg.provider:
        cfg = cfg.model_copy(update={"provider": provider})

    active_provider: VisionProvider = build_provider(cfg)
    _LOGGER.info("Using vision provider: %s", cfg.provider)

    png_paths = load_page_guides(guides_dir)
    if max_pages is not None:
        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        png_paths = png_paths[:max_pages]

    total = len(png_paths)
    all_fields: dict[str, Any] = {}

    for page_no, png_path in enumerate(png_paths, start=1):
        page_fields = active_provider.call_for_page(template_id, png_path, page_no, total)
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
