"""Core PDF filling engine.

The :class:`PdfFiller` class loads a static template PDF and stamps text and
checkbox marks at coordinates declared in a :class:`CoordinateMap`. It treats
the PDF as a fixed visual template — it does *not* use AcroForm/XFA APIs.

Design:
    * One :class:`PdfFiller` per template.
    * :py:meth:`PdfFiller.fill` is pure with respect to the template (the
      template file on disk is never modified — we open it, copy via
      ``insert_pdf`` into a fresh document, stamp into the copy, and save).
    * Errors short-circuit the operation; partial PDFs are not written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from .config import SETTINGS
from .exceptions import (
    DataValidationError,
    MissingRequiredFieldError,
    PdfFillerError,
    TemplateNotFoundError,
    TextOverflowError,
    UnsupportedFieldTypeError,
)
from .logging_config import get_logger
from .models import (
    CheckboxFieldConfig,
    CoordinateMap,
    DateFieldConfig,
    ImageFieldConfig,
    MultilineTextFieldConfig,
    SignatureTextFieldConfig,
    TemplateMetadata,
    TextFieldConfig,
)
from .utils import is_empty_value, resolve_path
from .validators import (
    parse_date_value,
    validate_metadata_page_count,
    validate_pages_in_range,
    validate_template_hash,
    validate_template_path,
)

_LOGGER = get_logger("filler")


# --------------------------------------------------------------------------- #
# Result type                                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class FillResult:
    """Summary returned by :py:meth:`PdfFiller.fill`."""

    output_path: Path
    fields_written: list[str] = field(default_factory=list)
    fields_skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: int = 0
    template_sha256: str | None = None


# --------------------------------------------------------------------------- #
# Engine                                                                       #
# --------------------------------------------------------------------------- #


class PdfFiller:
    """Stamps coordinate-mapped values onto a static template PDF."""

    def __init__(
        self,
        template_path: Path,
        coordinate_map: CoordinateMap,
        metadata: TemplateMetadata | None = None,
    ) -> None:
        self.template_path = validate_template_path(Path(template_path))
        self.coordinate_map = coordinate_map
        self.metadata = metadata
        self._template_sha: str | None = None

    # ----- public API ----------------------------------------------------- #

    def fill(
        self,
        data: dict[str, Any],
        output_path: Path,
        *,
        debug_boxes: bool = False,
        ignore_template_hash: bool = False,
        overwrite: bool = False,
    ) -> FillResult:
        """Fill the template with ``data`` and write to ``output_path``."""
        output_path = Path(output_path)
        if output_path.exists() and not overwrite:
            raise PdfFillerError(
                f"Output file already exists: {output_path}. Pass overwrite=True / --overwrite."
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._template_sha = validate_template_hash(
            self.template_path, self.metadata, ignore=ignore_template_hash
        )

        result = FillResult(output_path=output_path, template_sha256=self._template_sha)

        # Open the template, copy it into a fresh document so we never touch the original.
        with fitz.open(self.template_path) as src_doc:
            if src_doc.is_encrypted:
                if not SETTINGS.allow_encrypted_pdfs:
                    raise TemplateNotFoundError(
                        "Template PDF is encrypted; encrypted PDFs are not supported."
                    )
                # Best-effort: try empty password if user explicitly opted in.
                if not src_doc.authenticate(""):
                    raise TemplateNotFoundError("Encrypted template requires a password.")

            page_count = src_doc.page_count
            result.page_count = page_count

            validate_metadata_page_count(self.metadata, page_count)
            validate_pages_in_range(self.coordinate_map, page_count)

            out_doc = fitz.open()  # empty document
            try:
                out_doc.insert_pdf(src_doc)

                for name, fcfg in self.coordinate_map.fields.items():
                    self._render_field(out_doc, name, fcfg, data, result, debug_boxes)

                # Save with garbage collection + deflation for a smaller, clean PDF.
                out_doc.save(
                    str(output_path),
                    garbage=3,
                    deflate=True,
                    clean=True,
                )
            finally:
                out_doc.close()

        _LOGGER.info(
            "Fill complete: %d written, %d skipped -> %s",
            len(result.fields_written),
            len(result.fields_skipped),
            output_path,
        )
        return result

    # ----- field dispatch ------------------------------------------------- #

    def _render_field(
        self,
        doc: fitz.Document,
        name: str,
        cfg: Any,
        data: dict[str, Any],
        result: FillResult,
        debug_boxes: bool,
    ) -> None:
        """Resolve the source value for ``cfg`` and dispatch by field type."""
        value = resolve_path(data, cfg.source)
        page = doc[cfg.page - 1]  # 1-based → 0-based

        # Handle missing / empty values uniformly.
        if is_empty_value(value):
            if isinstance(cfg, CheckboxFieldConfig):
                # Checkbox with empty source: simply leave it unchecked.
                result.fields_skipped.append(name)
                _LOGGER.debug("Field '%s' (checkbox): empty source, leaving unchecked.", name)
                return
            if cfg.required:
                raise MissingRequiredFieldError(name, cfg.source)
            result.fields_skipped.append(name)
            warning = f"Optional field '{name}' has no value (source '{cfg.source}'); skipped."
            result.warnings.append(warning)
            _LOGGER.info(warning)
            return

        if debug_boxes:
            self._draw_debug_box(page, cfg)

        try:
            if isinstance(cfg, TextFieldConfig):
                self._render_text(page, name, cfg, str(value))
            elif isinstance(cfg, MultilineTextFieldConfig):
                self._render_multiline(page, name, cfg, str(value))
            elif isinstance(cfg, CheckboxFieldConfig):
                self._render_checkbox(page, name, cfg, value)
            elif isinstance(cfg, DateFieldConfig):
                self._render_date(page, name, cfg, value)
            elif isinstance(cfg, ImageFieldConfig):
                # Documented as a placeholder; we explicitly refuse rather than silently skip.
                raise UnsupportedFieldTypeError(
                    f"Field '{name}': image field type is not yet implemented."
                )
            elif isinstance(cfg, SignatureTextFieldConfig):
                # Reuse the text rendering with shrink-by-default.
                self._render_text_like(page, name, cfg, str(value))
            else:
                raise UnsupportedFieldTypeError(
                    f"Field '{name}' has unsupported type {type(cfg).__name__}."
                )
        except PdfFillerError:
            raise
        except Exception as exc:  # pragma: no cover — defensive guard
            raise PdfFillerError(f"Failed to render field '{name}': {exc}") from exc

        result.fields_written.append(name)
        _LOGGER.debug("Field '%s' rendered on page %d.", name, cfg.page)

    # ----- per-type renderers --------------------------------------------- #

    def _render_text(
        self,
        page: fitz.Page,
        name: str,
        cfg: TextFieldConfig,
        value: str,
    ) -> None:
        text = self._truncate_chars(value, cfg.max_chars)
        font_size = cfg.font_size

        # max_chars truncate mode: already applied above. If overflow=truncate
        # and there's no max_chars, fall back to width-based truncation below.
        if cfg.max_width is None:
            point = fitz.Point(cfg.x, cfg.y)
            page.insert_text(
                point,
                text,
                fontname=cfg.font,
                fontsize=font_size,
                color=cfg.color,
            )
            return

        font_size = self._fit_text_width(
            name=name,
            text=text,
            font_name=cfg.font,
            font_size=font_size,
            min_font_size=cfg.min_font_size,
            max_width=cfg.max_width,
            overflow=cfg.overflow,
        )
        if cfg.overflow == "truncate" and cfg.max_chars is None:
            text = self._truncate_to_width(text, cfg.font, font_size, cfg.max_width)

        rect = fitz.Rect(cfg.x, cfg.y, cfg.x + cfg.max_width, cfg.y + font_size * 4.0)
        rc = page.insert_textbox(
            rect,
            text,
            fontname=cfg.font,
            fontsize=font_size,
            align=_align_to_fitz(cfg.align),
            color=cfg.color,
        )
        if rc < 0 and cfg.overflow == "error":
            raise TextOverflowError(name, len(text), cfg.max_width)

    def _render_text_like(
        self,
        page: fitz.Page,
        name: str,
        cfg: SignatureTextFieldConfig,
        value: str,
    ) -> None:
        """Reuse text rendering with the SignatureTextFieldConfig settings."""
        font_size = cfg.font_size
        if cfg.max_width is None:
            page.insert_text(
                fitz.Point(cfg.x, cfg.y),
                value,
                fontname=cfg.font,
                fontsize=font_size,
                color=cfg.color,
            )
            return

        font_size = self._fit_text_width(
            name=name,
            text=value,
            font_name=cfg.font,
            font_size=font_size,
            min_font_size=cfg.min_font_size,
            max_width=cfg.max_width,
            overflow=cfg.overflow,
        )
        if cfg.overflow == "truncate":
            value = self._truncate_to_width(value, cfg.font, font_size, cfg.max_width)

        rect = fitz.Rect(cfg.x, cfg.y, cfg.x + cfg.max_width, cfg.y + font_size * 4.0)
        rc = page.insert_textbox(
            rect,
            value,
            fontname=cfg.font,
            fontsize=font_size,
            align=_align_to_fitz(cfg.align),
            color=cfg.color,
        )
        if rc < 0 and cfg.overflow == "error":
            raise TextOverflowError(name, len(value), cfg.max_width)

    def _render_multiline(
        self,
        page: fitz.Page,
        name: str,
        cfg: MultilineTextFieldConfig,
        value: str,
    ) -> None:
        height = cfg.line_height * cfg.max_lines + 2  # tiny pad
        rect = fitz.Rect(cfg.x, cfg.y, cfg.x + cfg.max_width, cfg.y + height)
        rc = page.insert_textbox(
            rect,
            value,
            fontname=cfg.font,
            fontsize=cfg.font_size,
            align=_align_to_fitz(cfg.align),
            color=cfg.color,
        )
        if rc < 0:
            if cfg.overflow == "error":
                raise TextOverflowError(name, len(value), cfg.max_width)
            if cfg.overflow == "shrink":
                # Try smaller sizes until it fits or we hit a floor at 6pt.
                fitted = False
                for fs in _shrink_steps(cfg.font_size, floor=6.0):
                    rc = page.insert_textbox(
                        rect,
                        value,
                        fontname=cfg.font,
                        fontsize=fs,
                        align=_align_to_fitz(cfg.align),
                        color=cfg.color,
                    )
                    if rc >= 0:
                        fitted = True
                        break
                if not fitted:
                    raise TextOverflowError(name, len(value), cfg.max_width)
            elif cfg.overflow == "truncate":
                # Drop characters from the end until it fits.
                truncated = value
                while truncated and (
                    rc := page.insert_textbox(
                        rect,
                        truncated,
                        fontname=cfg.font,
                        fontsize=cfg.font_size,
                        align=_align_to_fitz(cfg.align),
                        color=cfg.color,
                    )
                ) < 0:
                    truncated = truncated[:-1]
                if not truncated:
                    raise TextOverflowError(name, len(value), cfg.max_width)

    def _render_date(
        self,
        page: fitz.Page,
        name: str,
        cfg: DateFieldConfig,
        value: Any,
    ) -> None:
        date_obj = parse_date_value(value)
        try:
            text = date_obj.strftime(cfg.format)
        except ValueError as exc:
            raise DataValidationError(
                f"Field '{name}': invalid date format string '{cfg.format}': {exc}"
            ) from exc

        # Reuse text-field machinery via a synthesised text config.
        synthesised = TextFieldConfig(
            type="text",
            source=cfg.source,
            page=cfg.page,
            x=cfg.x,
            y=cfg.y,
            required=cfg.required,
            font=cfg.font,
            font_size=cfg.font_size,
            min_font_size=cfg.min_font_size,
            align=cfg.align,
            max_width=cfg.max_width,
            overflow=cfg.overflow,
            color=cfg.color,
        )
        self._render_text(page, name, synthesised, text)

    def _render_checkbox(
        self,
        page: fitz.Page,
        name: str,
        cfg: CheckboxFieldConfig,
        value: Any,
    ) -> None:
        if not _checkbox_should_check(cfg.checked_when, value):
            _LOGGER.debug("Checkbox '%s' resolved to unchecked.", name)
            return

        x0, y0 = cfg.x, cfg.y
        size = cfg.box_size
        x1, y1 = x0 + size, y0 + size
        rect = fitz.Rect(x0, y0, x1, y1)

        if cfg.check_style == "filled_square":
            page.draw_rect(
                rect,
                color=cfg.color,
                fill=cfg.color,
                width=cfg.line_width,
                overlay=True,
            )
        elif cfg.check_style == "x":
            page.draw_line(fitz.Point(x0, y0), fitz.Point(x1, y1),
                           color=cfg.color, width=cfg.line_width, overlay=True)
            page.draw_line(fitz.Point(x1, y0), fitz.Point(x0, y1),
                           color=cfg.color, width=cfg.line_width, overlay=True)
        elif cfg.check_style == "check":
            # Drawn as two segments: short left stroke, longer right stroke.
            mid_x = x0 + size * 0.4
            mid_y = y0 + size * 0.75
            page.draw_line(
                fitz.Point(x0 + size * 0.1, y0 + size * 0.5),
                fitz.Point(mid_x, mid_y),
                color=cfg.color, width=cfg.line_width, overlay=True,
            )
            page.draw_line(
                fitz.Point(mid_x, mid_y),
                fitz.Point(x0 + size * 0.95, y0 + size * 0.15),
                color=cfg.color, width=cfg.line_width, overlay=True,
            )

    # ----- helpers -------------------------------------------------------- #

    @staticmethod
    def _truncate_chars(text: str, max_chars: int | None) -> str:
        if max_chars is None or len(text) <= max_chars:
            return text
        return text[:max_chars]

    @staticmethod
    def _fit_text_width(
        *,
        name: str,
        text: str,
        font_name: str,
        font_size: float,
        min_font_size: float,
        max_width: float,
        overflow: str,
    ) -> float:
        """Return a font size that fits, applying the configured overflow strategy."""
        width = fitz.get_text_length(text, fontname=font_name, fontsize=font_size)
        if width <= max_width:
            return font_size
        if overflow == "shrink":
            for fs in _shrink_steps(font_size, floor=min_font_size):
                if fitz.get_text_length(text, fontname=font_name, fontsize=fs) <= max_width:
                    return fs
            raise TextOverflowError(name, len(text), max_width)
        if overflow == "truncate":
            return font_size  # caller will truncate the text
        # "error" or anything else
        raise TextOverflowError(name, len(text), max_width)

    @staticmethod
    def _truncate_to_width(
        text: str, font_name: str, font_size: float, max_width: float
    ) -> str:
        """Drop trailing characters until the rendered width fits."""
        result = text
        while result and fitz.get_text_length(
            result, fontname=font_name, fontsize=font_size
        ) > max_width:
            result = result[:-1]
        return result

    @staticmethod
    def _draw_debug_box(page: fitz.Page, cfg: Any) -> None:
        """Draw a faint outline around the field's target area for visual debugging."""
        debug_color = (1.0, 0.4, 0.4)  # light red
        if isinstance(cfg, CheckboxFieldConfig):
            rect = fitz.Rect(cfg.x, cfg.y, cfg.x + cfg.box_size, cfg.y + cfg.box_size)
        elif isinstance(cfg, MultilineTextFieldConfig):
            rect = fitz.Rect(
                cfg.x, cfg.y, cfg.x + cfg.max_width,
                cfg.y + cfg.line_height * cfg.max_lines,
            )
        else:
            width = getattr(cfg, "max_width", None) or 80.0
            font_size = getattr(cfg, "font_size", 10.0)
            rect = fitz.Rect(cfg.x, cfg.y, cfg.x + width, cfg.y + font_size * 1.6)
        page.draw_rect(rect, color=debug_color, width=0.4, overlay=True)


# --------------------------------------------------------------------------- #
# Module-level helpers                                                         #
# --------------------------------------------------------------------------- #


def _align_to_fitz(align: str) -> int:
    """Map our alignment strings to PyMuPDF align constants."""
    return {
        "left": fitz.TEXT_ALIGN_LEFT,
        "center": fitz.TEXT_ALIGN_CENTER,
        "right": fitz.TEXT_ALIGN_RIGHT,
    }[align]


def _shrink_steps(start: float, floor: float, step: float = 0.5) -> list[float]:
    """Generate descending font sizes from ``start`` down to ``floor``."""
    sizes: list[float] = []
    current = start - step
    while current >= floor:
        sizes.append(round(current, 2))
        current -= step
    return sizes


def _checkbox_should_check(checked_when: Any, value: Any) -> bool:
    """Decide whether a checkbox should be marked given its ``checked_when`` rule.

    * If ``checked_when`` is None → boolean checkbox: truthy ``value`` checks it.
    * Otherwise → option checkbox: case-insensitive string equality.
    """
    if checked_when is None:
        return bool(value)
    if isinstance(value, bool):
        # Avoid bool→str pitfalls: treat boolean values literally for option checkboxes only
        # if the configured checked_when is also a bool.
        if isinstance(checked_when, bool):
            return value == checked_when
        return False
    return str(value).strip().lower() == str(checked_when).strip().lower()
