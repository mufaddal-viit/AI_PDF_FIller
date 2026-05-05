"""Pydantic v2 models for the coordinate map, template metadata, and fill request.

The coordinate-map field configs are a discriminated union on the ``type``
field, so each concrete config (text, multiline_text, checkbox, date, image,
signature_text) gets its own validator schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

# --------------------------------------------------------------------------- #
# Shared types                                                                 #
# --------------------------------------------------------------------------- #

Alignment = Literal["left", "center", "right"]
OverflowStrategy = Literal["error", "shrink", "truncate"]
CheckStyle = Literal["check", "x", "filled_square"]
CoordinateSystem = Literal["pymupdf"]
PageSize = Literal["A4", "Letter", "Legal", "custom"]


class _BaseField(BaseModel):
    """Common fields shared by every concrete coordinate field type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(
        ...,
        description="Dotted path into the input data (e.g. 'applicant.surname').",
        min_length=1,
    )
    page: PositiveInt = Field(
        ...,
        description="1-based page number (PyMuPDF uses 0-based internally).",
    )
    x: float = Field(..., description="X coordinate in points (origin top-left).")
    y: float = Field(..., description="Y coordinate in points (origin top-left).")
    required: bool = Field(default=False)


# --------------------------------------------------------------------------- #
# Concrete field configs                                                       #
# --------------------------------------------------------------------------- #


class TextFieldConfig(_BaseField):
    """A single-line text field stamped onto the page."""

    type: Literal["text"] = "text"
    font_size: PositiveFloat = 10.0
    font: str = "helv"
    align: Alignment = "left"
    max_width: PositiveFloat | None = None
    max_chars: PositiveInt | None = None
    overflow: OverflowStrategy = "error"
    min_font_size: PositiveFloat = 6.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @model_validator(mode="after")
    def _check_min_font_size(self) -> TextFieldConfig:
        if self.min_font_size > self.font_size:
            raise ValueError(
                f"min_font_size ({self.min_font_size}) cannot exceed font_size ({self.font_size})."
            )
        return self


class MultilineTextFieldConfig(_BaseField):
    """A multi-line text field rendered into a bounding rectangle."""

    type: Literal["multiline_text"] = "multiline_text"
    font_size: PositiveFloat = 10.0
    font: str = "helv"
    align: Alignment = "left"
    max_width: PositiveFloat = Field(..., description="Required for multiline text.")
    line_height: PositiveFloat = Field(..., description="Line height in points.")
    max_lines: PositiveInt = Field(default=5)
    overflow: OverflowStrategy = "error"
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)


class CheckboxFieldConfig(_BaseField):
    """A checkbox stamped over a printed empty box.

    There are two flavours of checkbox use:

    * **Boolean checkbox** (``checked_when`` omitted): the source value is
      coerced to bool and the box is checked iff truthy.
    * **Option checkbox** (``checked_when`` present): the source value is
      compared (string-equality, case-insensitive) to ``checked_when``.
    """

    type: Literal["checkbox"] = "checkbox"
    box_size: PositiveFloat = 8.0
    checked_when: str | int | float | bool | None = None
    check_style: CheckStyle = "x"
    line_width: PositiveFloat = 1.2
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)


class DateFieldConfig(_BaseField):
    """A date field, formatted via :py:meth:`datetime.date.strftime`."""

    type: Literal["date"] = "date"
    font_size: PositiveFloat = 10.0
    font: str = "helv"
    align: Alignment = "left"
    format: str = "%d-%m-%Y"
    max_width: PositiveFloat | None = None
    overflow: OverflowStrategy = "error"
    min_font_size: PositiveFloat = 6.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)


class ImageFieldConfig(_BaseField):
    """Placeholder for future image support (e.g. a photograph)."""

    type: Literal["image"] = "image"
    width: PositiveFloat
    height: PositiveFloat
    keep_aspect: bool = True


class SignatureTextFieldConfig(_BaseField):
    """A signature rendered as text in a script-like font."""

    type: Literal["signature_text"] = "signature_text"
    font_size: PositiveFloat = 14.0
    font: str = "helv"  # callers can swap for a script font installed in fitz
    align: Alignment = "left"
    max_width: PositiveFloat | None = None
    overflow: OverflowStrategy = "shrink"
    min_font_size: PositiveFloat = 8.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)


# Discriminated union: pydantic picks the right model based on the ``type`` tag.
FieldConfig = Annotated[
    TextFieldConfig | MultilineTextFieldConfig | CheckboxFieldConfig | DateFieldConfig | ImageFieldConfig | SignatureTextFieldConfig,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
# Coordinate map                                                               #
# --------------------------------------------------------------------------- #


class CoordinateMap(BaseModel):
    """Top-level coordinate map document."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(..., min_length=1)
    template_version: str = Field(..., min_length=1)
    page_size: PageSize = "A4"
    coordinate_system: CoordinateSystem = "pymupdf"
    units: Literal["points"] = "points"
    fields: dict[str, FieldConfig]  # type: ignore[valid-type]

    @field_validator("fields")
    @classmethod
    def _check_fields_non_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("Coordinate map must define at least one field.")
        return value

    def field_names(self) -> list[str]:
        """Return field names in declaration order."""
        return list(self.fields.keys())


# --------------------------------------------------------------------------- #
# Template metadata                                                            #
# --------------------------------------------------------------------------- #


class TemplateMetadata(BaseModel):
    """Companion metadata file describing the template PDF."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(..., min_length=1)
    template_version: str = Field(..., min_length=1)
    expected_pages: PositiveInt
    sha256: str = ""
    description: str = ""

    @field_validator("sha256")
    @classmethod
    def _check_sha(cls, value: str) -> str:
        v = value.strip().lower()
        if v == "":
            return v
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError("sha256 must be a 64-character hex string or empty.")
        return v


# --------------------------------------------------------------------------- #
# Fill request (used by CLI / programmatic API)                                #
# --------------------------------------------------------------------------- #


class FillRequest(BaseModel):
    """Bundle of inputs required to perform a fill operation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    template_path: Path
    data: dict[str, Any]
    coordinate_map: CoordinateMap
    metadata: TemplateMetadata | None = None
    output_path: Path
    debug_boxes: bool = False
    ignore_template_hash: bool = False
    overwrite: bool = False
