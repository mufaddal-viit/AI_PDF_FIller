# pdf-filler

A production-quality, **coordinate-based** static PDF template filler written in
Python. Stamps text and checkbox marks onto a fixed visual template using a
JSON input data file and a JSON coordinate map.

The first packaged template is the Schengen visa application form (4 pages),
but the engine is template-agnostic.

---

## Why coordinate-based?

Many real-world forms — including the Schengen visa application — are
distributed as **printed/scanned, non-fillable PDFs**. They have no AcroForm
or XFA fields, so libraries that "fill PDFs" by looking up form-field names
can't help.

The only reliable approach is to treat the PDF as a *visual* template and stamp
values at precise coordinates. That's what this project does.

* No PDF form fields are required.
* The original template file is **never modified**.
* The output is a normal, flattened PDF where the values are part of the page
  content.

---

## Features

- Pydantic v2-validated coordinate maps and template metadata.
- Discriminated-union field types: `text`, `multiline_text`, `checkbox`,
  `date`, `image` (placeholder), `signature_text`.
- 1-based page numbers in the coordinate map (PyMuPDF uses 0-based internally).
- Text alignment (`left` / `center` / `right`), font size, max width, max
  characters.
- Overflow strategies: `error` (default), `shrink`, `truncate`.
- Checkboxes: boolean and option-style (`checked_when`); draw as `x`,
  `check`, or `filled_square`.
- Nested data paths (`applicant.surname`, `travel.purpose.tourism`).
- Optional vs required fields with clear missing-data errors.
- SHA-256 template hash check against metadata.
- `--debug-boxes` overlay for visual coordinate calibration.
- `make-coordinate-guide` command renders PNGs with a coordinate grid.
- Typer CLI + clean Python API.

---

## Project layout

```
pdf_filler/
├── README.md
├── pyproject.toml
├── requirements.txt
├── .gitignore
├── src/pdf_filler/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── coordinates.py
│   ├── exceptions.py
│   ├── filler.py
│   ├── logging_config.py
│   ├── models.py
│   ├── render_check.py
│   ├── utils.py
│   └── validators.py
├── templates/schengen/
│   ├── coordinate_map.json
│   └── template_metadata.json    # drop your template.pdf here
├── examples/
│   └── input_data.example.json
├── output/                       # generated PDFs land here (.gitkeep'd)
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_coordinates.py
    └── test_filler.py
```

> The template PDF (`templates/schengen/template.pdf`) is **not** committed.
> Drop your own copy in.

---

## Installation

Requires **Python 3.11+**.

```powershell
# create a venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# install the package + dev tools
pip install -e ".[dev]"
```

Or just the runtime dependencies:

```powershell
pip install -r requirements.txt
```

---

## CLI usage

After installation the `pdf-filler` console script is on `PATH`. You can also
run the module directly via `python -m pdf_filler.cli`.

### Fill a template

```powershell
python -m pdf_filler.cli fill `
  --template templates/schengen/template.pdf `
  --data examples/input_data.example.json `
  --coordinates templates/schengen/coordinate_map.json `
  --metadata templates/schengen/template_metadata.json `
  --output output/filled_schengen.pdf
```

Equivalent installed-script form:

```powershell
pdf-filler fill --template ... --data ... --coordinates ... --output ...
```

Useful flags:

| Flag                     | Purpose                                                       |
| ------------------------ | ------------------------------------------------------------- |
| `--metadata <PATH>`      | Optional template metadata (page count + SHA-256 lock).       |
| `--ignore-template-hash` | Don't fail if SHA-256 mismatches the metadata.                |
| `--debug-boxes`          | Draw faint outlines around field areas for calibration.       |
| `--overwrite`            | Overwrite an existing output file.                            |
| `-v / --verbose`         | Enable debug logging.                                         |

### Inspect a template

```powershell
python -m pdf_filler.cli inspect-template --template templates/schengen/template.pdf --page 1
```

Prints page count, the geometry of the selected page (or all pages), and a
recap of the PyMuPDF coordinate system.

### Render a coordinate guide

```powershell
python -m pdf_filler.cli make-coordinate-guide `
  --template templates/schengen/template.pdf `
  --output output/page_guides/
```

Writes one PNG per page, with a coordinate grid overlaid (`x=…`, `y=…`
labels every 100 pt by default, minor lines every 25 pt). Open these in any
image viewer to read the (x, y) for each field.

Tunables: `--grid-step 25`, `--major-step 100`, `--zoom 2.0`.

### Validate a coordinate map

```powershell
python -m pdf_filler.cli validate-coordinate-map --coordinates templates/schengen/coordinate_map.json
```

Loads the coordinate map and prints a JSON summary (field counts by type and
page). Exits non-zero on validation errors and lists every problem.

### Hash a template

```powershell
# Print the template's SHA-256:
python -m pdf_filler.cli hash-template --template templates/schengen/template.pdf

# Or write it directly into the metadata file:
python -m pdf_filler.cli hash-template `
  --template templates/schengen/template.pdf `
  --update-metadata templates/schengen/template_metadata.json
```

---

## JSON input data format

The input data is a regular JSON object. Coordinate fields reference values
inside it by **dotted paths** (`applicant.surname`, `travel.purpose.tourism`).
There is no fixed schema — the coordinate map decides which paths matter.

See [`examples/input_data.example.json`](examples/input_data.example.json) for
a complete Schengen sample.

```json
{
  "applicant": {
    "surname": "DOE",
    "first_names": "JOHN MICHAEL",
    "date_of_birth": "1990-04-21",
    "sex": "male",
    "home_address": "123 Example Street, Mumbai, Maharashtra, India"
  },
  "travel_document": {
    "number": "X1234567",
    "date_of_issue": "2023-01-01",
    "valid_until": "2033-01-01"
  },
  "travel": {
    "purpose": { "tourism": true, "business": false },
    "main_destination": "France",
    "arrival_date": "2026-03-10",
    "departure_date": "2026-03-25"
  }
}
```

Empty strings, `null`, and missing keys are all treated as "no input
provided". `0` and `false` are treated as explicit values (so a boolean `false`
is valid input for an option-checkbox compared against `false`).

---

## JSON coordinate map format

Top-level shape:

```json
{
  "template_id": "schengen_visa_application",
  "template_version": "2026-11-14",
  "page_size": "A4",
  "coordinate_system": "pymupdf",
  "units": "points",
  "fields": { ... }
}
```

Every entry under `fields` has a `type`, a `source` (dotted path), `page`
(1-based), and `x`, `y` in PDF points.

### Field-type reference

#### `text`

```json
{
  "type": "text",
  "source": "applicant.surname",
  "page": 1,
  "x": 24, "y": 190,
  "font": "helv",
  "font_size": 10,
  "align": "left",
  "max_width": 550,
  "max_chars": 60,
  "overflow": "shrink",
  "min_font_size": 7,
  "color": [0, 0, 0],
  "required": true
}
```

#### `multiline_text`

```json
{
  "type": "multiline_text",
  "source": "applicant.home_address",
  "page": 2,
  "x": 24, "y": 325,
  "font_size": 9,
  "max_width": 420,
  "line_height": 11,
  "max_lines": 5,
  "overflow": "error",
  "required": true
}
```

`max_width` and `line_height` are required.

#### `checkbox`

Boolean checkbox (`checked_when` omitted):

```json
{
  "type": "checkbox",
  "source": "travel.purpose.tourism",
  "page": 3,
  "x": 27, "y": 200,
  "box_size": 8,
  "check_style": "x"
}
```

Option checkbox (`checked_when` matches the source value, case-insensitive):

```json
{
  "type": "checkbox",
  "source": "applicant.sex",
  "page": 1,
  "x": 27, "y": 511,
  "box_size": 8,
  "checked_when": "male",
  "check_style": "x"
}
```

`check_style` is one of: `"x"`, `"check"`, `"filled_square"`.

#### `date`

```json
{
  "type": "date",
  "source": "applicant.date_of_birth",
  "page": 1,
  "x": 24, "y": 360,
  "format": "%d-%m-%Y",
  "max_width": 180,
  "overflow": "error",
  "required": true
}
```

`format` is a Python `strftime` string.

#### `signature_text`

Same options as `text`, with `overflow` defaulting to `shrink` and a larger
default font size — handy for stamping a typed signature line.

#### `image` (placeholder)

Reserved for future image/photo support. Currently raises
`UnsupportedFieldTypeError` so it can't be silently ignored.

---

## Coordinate system

`pdf-filler` uses PyMuPDF coordinates throughout:

- Origin is the **top-left** corner of each page.
- `x` increases to the **right**.
- `y` increases **downward**.
- Units are **PDF points** (1 inch = 72 pt).
- A4 page ≈ **595 × 842 pt**. US Letter ≈ **612 × 792 pt**.

Use `inspect-template` to confirm a specific template's per-page geometry.

---

## How to create a coordinate map

1. **Render a coordinate guide.**
   ```powershell
   python -m pdf_filler.cli make-coordinate-guide --template templates/schengen/template.pdf --output output/page_guides/
   ```
2. **Open the PNG** (`output/page_guides/page_01_guide.png` etc.) in any
   image viewer. The grid has labelled major lines.
3. **Locate each field visually** and read its top-left (x, y) off the grid.
4. **Add the entry to `coordinate_map.json`** with the right `type`, `page`,
   `x`, `y`, plus type-specific options (font size, max width, etc.).
5. **Run `fill`** with sample data:
   ```powershell
   python -m pdf_filler.cli fill --template ... --data examples/input_data.example.json --coordinates templates/schengen/coordinate_map.json --output output/test.pdf --overwrite
   ```
6. **Open the output PDF** and check positioning.
7. **Nudge** if needed:
   - increase `x` to move text right
   - decrease `x` to move text left
   - increase `y` to move text down
   - decrease `y` to move text up
8. For checkboxes, pick (x, y) at the **top-left of the printed box**. The
   stamp is drawn inside an `box_size` × `box_size` square anchored there.
9. Once aligned, **commit the coordinate map together with the template
   version** so they evolve in lockstep.

### Debug boxes

Pass `--debug-boxes` to draw a faint red outline around every field's target
area. Open the resulting PDF to verify that text rectangles and checkbox
target squares land where you expect.

```powershell
python -m pdf_filler.cli fill --template ... --data ... --coordinates ... --output output/debug.pdf --overwrite --debug-boxes
```

---

## Programmatic API

```python
from pathlib import Path

from pdf_filler import PdfFiller
from pdf_filler.coordinates import load_coordinate_map
from pdf_filler.validators import load_template_metadata, validate_input_data

template = Path("templates/schengen/template.pdf")
coord_map = load_coordinate_map(Path("templates/schengen/coordinate_map.json"))
metadata = load_template_metadata(Path("templates/schengen/template_metadata.json"))
data = validate_input_data(Path("examples/input_data.example.json"))

filler = PdfFiller(template, coord_map, metadata=metadata)
result = filler.fill(data, Path("output/filled.pdf"), overwrite=True)
print(result.fields_written, result.fields_skipped)
```

The Pydantic models, exceptions, and engine are also re-exported from the
package root.

---

## Production notes

- **Lock the template by SHA-256.** Run
  `pdf-filler hash-template --template ... --update-metadata templates/schengen/template_metadata.json`
  whenever you adopt a new official version, then check the metadata into
  source control. Filling will refuse to run against a different template
  unless `--ignore-template-hash` is passed.
- **Version your coordinate maps** alongside the template version
  (`template_version` field) — embassies *do* re-issue forms.
- **Validate input data** at the application boundary (the supplied Pydantic
  models give you a head start; the engine itself only reads the dotted
  paths it needs).
- **Flatten output by stamping content directly.** That's already how this
  package works — values are part of the page content stream, not editable
  form fields.
- **Render output for QA.** Keep a folder of golden sample PDFs and diff them
  visually (or pixel-diff via `get_pixmap`) when changing coordinates or the
  engine.
- **Avoid logging PII.** The included logger logs field *names* and outcomes,
  not values. Don't add `logger.info(value)` lines without thinking.
- **Constrain output paths.** Use
  `pdf_filler.utils.safe_resolve_output_path` if accepting paths from
  untrusted callers.

---

## Running the tests

```powershell
pytest -q
```

Tests synthesise a 4-page A4 PDF on the fly, so you can run them without the
real Schengen template.

---

## Roadmap (intentionally not done yet)

- FastAPI wrapper around the engine.
- OCR-based field discovery.
- Image / photo placement (the `image` field type is reserved for this).
- Database-backed batch filling.

These are deliberately out of scope for the current local CLI engine.

---

Full README.md content with new Groq section added after "How to create a coordinate map":

## Auto-Generate Coordinate Maps with Groq Vision (New!)

1. Generate guides: `pdf-filler make-coordinate-guide --template your.pdf --output output/page_guides`
2. Run: `pdf-filler generate-coordinate-map schengen_visa_application --guides-dir output/page_guides`
3. Review `templates/schengen_visa_application/coordinate_map.json`, tweak, validate: `pdf-filler validate-coordinate-map templates/schengen_visa_application/coordinate_map.json`
4. Fill!

Requires .env with GROQ_API_KEY (free at console.groq.com). Uses llama-3.2-11b-vision-preview.

~80% accurate; human review essential for precision.