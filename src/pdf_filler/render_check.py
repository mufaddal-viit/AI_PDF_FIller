"""Tools for visually calibrating coordinates.

Two helpers:

* :func:`inspect_template` — print page count and per-page geometry.
* :func:`render_coordinate_guide` — render every page to PNG with a coordinate
  grid overlay so you can visually pick (x, y) for each field.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from .logging_config import get_logger
from .validators import validate_template_path

_LOGGER = get_logger("render_check")


# --------------------------------------------------------------------------- #
# Inspection                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PageInfo:
    page_number: int
    width: float
    height: float


@dataclass(frozen=True)
class TemplateInspection:
    template_path: Path
    page_count: int
    pages: list[PageInfo]
    coordinate_system: str = (
        "PyMuPDF: origin = top-left of page; x increases right; y increases down; "
        "units = points (1 inch = 72 points). A4 ~= 595x842 pt; Letter ~= 612x792 pt."
    )


def inspect_template(template_path: Path, page: int | None = None) -> TemplateInspection:
    """Inspect a template PDF and return geometric info for one or all pages.

    Args:
        template_path: Path to the template PDF.
        page: Optional 1-based page number to inspect. If None, all pages.
    """
    template_path = validate_template_path(Path(template_path))
    pages: list[PageInfo] = []
    with fitz.open(template_path) as doc:
        if page is not None:
            if page < 1 or page > doc.page_count:
                raise ValueError(
                    f"Requested page {page} but PDF has {doc.page_count} page(s)."
                )
            target_pages = [page]
        else:
            target_pages = list(range(1, doc.page_count + 1))

        for p in target_pages:
            pdf_page = doc[p - 1]
            rect = pdf_page.rect
            pages.append(
                PageInfo(page_number=p, width=float(rect.width), height=float(rect.height))
            )
        page_count = doc.page_count

    return TemplateInspection(
        template_path=template_path, page_count=page_count, pages=pages
    )


# --------------------------------------------------------------------------- #
# Coordinate guide rendering                                                   #
# --------------------------------------------------------------------------- #


def render_coordinate_guide(
    template_path: Path,
    output_dir: Path,
    *,
    grid_step: float = 25.0,
    major_step: float = 100.0,
    zoom: float = 2.0,
) -> list[Path]:
    """Render every page of the template to PNG with a coordinate grid overlay.

    The output is intended for visual coordinate calibration: you open the PNG,
    locate the field on the page, read the ``x``/``y`` from the grid, and paste
    those numbers into the coordinate map.

    Args:
        template_path: Path to template PDF.
        output_dir: Directory to write the guide PNGs into. Created if missing.
        grid_step: Minor grid line spacing in points.
        major_step: Major (labelled) grid line spacing in points.
        zoom: Output rasterisation zoom factor.

    Returns:
        A list of written PNG paths, in page order.
    """
    template_path = validate_template_path(Path(template_path))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    with fitz.open(template_path) as src_doc:
        # We'll create a *separate* PDF containing the grid overlay, then render it
        # so the original template file stays untouched.
        for index in range(src_doc.page_count):
            page_no = index + 1
            with fitz.open() as overlay_doc:
                overlay_doc.insert_pdf(src_doc, from_page=index, to_page=index)
                overlay_page = overlay_doc[0]
                _draw_grid(overlay_page, grid_step=grid_step, major_step=major_step)
                pix = overlay_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                out_path = output_dir / f"page_{page_no:02d}_guide.png"
                pix.save(str(out_path))
                _LOGGER.info("Wrote coordinate guide for page %d -> %s", page_no, out_path)
                written.append(out_path)
    return written


def _draw_grid(
    page: fitz.Page,
    *,
    grid_step: float,
    major_step: float,
) -> None:
    """Draw a coordinate grid + labels onto a page in-place.

    Minor lines: light gray. Major lines (every ``major_step`` points): darker
    gray with x/y labels.
    """
    rect = page.rect
    width = rect.width
    height = rect.height

    minor_color = (1.0, 0.6, 0.6)
    major_color = (0.9, 0.0, 0.0)
    label_color = (0.7, 0.0, 0.0)

    # Vertical lines (x = constant).
    x = 0.0
    while x <= width + 0.5:
        is_major = abs(x % major_step) < 1e-6
        page.draw_line(
            fitz.Point(x, 0),
            fitz.Point(x, height),
            color=major_color if is_major else minor_color,
            width=0.4 if is_major else 0.2,
            overlay=True,
        )
        x += grid_step

    # Horizontal lines (y = constant).
    y = 0.0
    while y <= height + 0.5:
        is_major = abs(y % major_step) < 1e-6
        page.draw_line(
            fitz.Point(0, y),
            fitz.Point(width, y),
            color=major_color if is_major else minor_color,
            width=0.4 if is_major else 0.2,
            overlay=True,
        )
        y += grid_step

    # Axis labels along the top (x) and left (y) using major_step.
    label_size = 6.0
    x = 0.0
    while x <= width + 0.5:
        if abs(x % major_step) < 1e-6:
            page.insert_text(
                fitz.Point(x + 1.5, 8),
                f"x={round(x)}",
                fontname="helv",
                fontsize=label_size,
                color=label_color,
                overlay=True,
            )
        x += major_step
    y = 0.0
    while y <= height + 0.5:
        if abs(y % major_step) < 1e-6:
            page.insert_text(
                fitz.Point(2, y + 7),
                f"y={round(y)}",
                fontname="helv",
                fontsize=label_size,
                color=label_color,
                overlay=True,
            )
        y += major_step
