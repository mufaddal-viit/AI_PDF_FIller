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
- `make-coordinate-guide` renders per-page PNGs with a coordinate grid.
- **`generate-coordinate-map` auto-generates a coordinate map from those PNGs
  using Groq's vision API — no manual coordinate hunting needed.**
- Typer CLI + clean Python API.

---

## Project layout

```
pdf_filler/
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example              # copy to .env and add GROQ_API_KEY
├── .gitignore
├── src/pdf_filler/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── coordinates.py
│   ├── exceptions.py
│   ├── filler.py
│   ├── groq_config.py        # Groq API settings (lazy-loaded)
│   ├── groq_prompt.py        # Token-efficient vision prompts
│   ├── groq_vision.py        # One Groq call per page, merges results
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
│   └── page_guides/              # coordinate-guide PNGs land here
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

### Groq vision (optional)

Only needed for `generate-coordinate-map`. Install the extra and add your key:

```powershell
pip install groq pydantic-settings
```

```powershell
# copy the example and fill in your key
copy .env.example .env
# edit .env: GROQ_API_KEY=gsk_...
```

Get a free key at <https://console.groq.com/keys>.

---

## How the two workflows compare

### Manual workflow (full control)

```
template.pdf  →  make-coordinate-guide  →  page PNGs
                                               │
                                    open in image viewer,
                                    read (x, y) off grid
                                               │
                                     hand-edit coordinate_map.json
                                               │
                                           fill  →  output.pdf
```

### Groq-assisted workflow (faster first draft)

```
template.pdf  →  make-coordinate-guide  →  page PNGs
                                               │
                                    generate-coordinate-map
                                     (one Groq API call per page)
                                               │
                                  auto-generated coordinate_map.json
                                               │
                              review / tweak / validate-coordinate-map
                                               │
                                           fill  →  output.pdf
```

The Groq step replaces the tedious "hunt for coordinates" phase. The output is
around 80–90 % accurate; always review before stamping real documents.

---

## CLI usage

After installation the `pdf-filler` console script is on `PATH`. You can also
run the module directly via `python -m pdf_filler.cli`.

### Fill a template

```powershell
pdf-filler fill `
  --template   templates/schengen/template.pdf `
  --data       examples/input_data.example.json `
  --coordinates templates/schengen/coordinate_map.json `
  --metadata   templates/schengen/template_metadata.json `
  --output     output/filled_schengen.pdf
```

Useful flags:

| Flag                     | Purpose                                                  |
| ------------------------ | -------------------------------------------------------- |
| `--metadata <PATH>`      | Template metadata (page count + SHA-256 lock).           |
| `--ignore-template-hash` | Skip SHA-256 check.                                      |
| `--debug-boxes`          | Draw faint red outlines around field areas.              |
| `--overwrite`            | Overwrite an existing output file.                       |
| `-v / --verbose`         | Enable debug logging.                                    |

### Inspect a template

```powershell
pdf-filler inspect-template --template templates/schengen/template.pdf --page 1
```

Prints page count, geometry for each page, and a recap of the PyMuPDF
coordinate system.

### Render coordinate guides

```powershell
pdf-filler make-coordinate-guide `
  --template templates/schengen/template.pdf `
  --output   output/page_guides/
```

Writes `page_01_guide.png`, `page_02_guide.png`, … with a coordinate grid
overlaid (`x=…` / `y=…` labels every 100 pt, minor lines every 25 pt).
Open in any image viewer to read field positions.

Tunables: `--grid-step 25`, `--major-step 100`, `--zoom 2.0`.

### Auto-generate a coordinate map with Groq

> **Prerequisite:** render the guide PNGs first (step above).

```powershell
pdf-filler generate-coordinate-map schengen_visa_application `
  --guides-dir output/page_guides `
  --output-dir templates `
  --version    "2026-11-14" `
  --page-size  A4 `
  --max-pages  2
```

This sends **one PNG at a time** to the Groq vision model, extracts field
coordinates per page, and merges the results into a single coordinate map.

Output: `templates/schengen_visa_application/coordinate_map.json`

All options and their defaults:

| Option          | Default                  | Purpose                                  |
| --------------- | ------------------------ | ---------------------------------------- |
| `TEMPLATE_ID`   | *(required argument)*    | Used as `template_id` in the map and as the output subfolder name. |
| `--guides-dir`  | `output/page_guides`     | Directory containing `page_*_guide.png`. |
| `--output-dir`  | `templates`              | Root output directory.                   |
| `--version`     | `auto-v1`                | Value for `template_version` in the map. |
| `--page-size`   | `A4`                     | Value for `page_size` in the map.        |
| `--max-pages`   | *(all pages)*            | Stop after this many pages (min 1). Useful for testing on just the first page or two before committing to a full run. |
| `-v`            | off                      | Debug logging.                           |

After generation, always:

1. Validate the map: `pdf-filler validate-coordinate-map --coordinates templates/schengen_visa_application/coordinate_map.json`
2. Do a test fill with `--debug-boxes` and visually inspect the output PDF.
3. Nudge any coordinates that are off.

### Validate a coordinate map

```powershell
pdf-filler validate-coordinate-map --coordinates templates/schengen/coordinate_map.json
```

Prints a JSON summary (field counts by type and page). Exits non-zero on
validation errors and lists every problem.

### Hash a template

```powershell
# Print the SHA-256:
pdf-filler hash-template --template templates/schengen/template.pdf

# Write it directly into the metadata file:
pdf-filler hash-template `
  --template       templates/schengen/template.pdf `
  --update-metadata templates/schengen/template_metadata.json
```

---

## Full Groq-assisted walkthrough

```powershell
# 1. Render guide PNGs (do this once per template version)
pdf-filler make-coordinate-guide `
  --template templates/schengen/template.pdf `
  --output   output/page_guides/

# 2. Auto-generate the coordinate map
# --max-pages is optional; use it to test on just the first N pages before a full run
pdf-filler generate-coordinate-map schengen_visa_application `
  --guides-dir output/page_guides `
  --output-dir templates `
  --version    "2026-11-14" `
  --max-pages  1

# 3. Validate the generated map
pdf-filler validate-coordinate-map `
  --coordinates templates/schengen_visa_application/coordinate_map.json

# 4. Test-fill with debug outlines to check positioning
pdf-filler fill `
  --template    templates/schengen/template.pdf `
  --data        examples/input_data.example.json `
  --coordinates templates/schengen_visa_application/coordinate_map.json `
  --output      output/debug.pdf `
  --overwrite `
  --debug-boxes

# 5. Open output/debug.pdf, tweak coordinates in coordinate_map.json, repeat

# 6. Lock the template hash once you're happy
pdf-filler hash-template `
  --template        templates/schengen/template.pdf `
  --update-metadata templates/schengen_visa_application/template_metadata.json

# 7. Fill for real
pdf-filler fill `
  --template    templates/schengen/template.pdf `
  --data        my_application.json `
  --coordinates templates/schengen_visa_application/coordinate_map.json `
  --metadata    templates/schengen_visa_application/template_metadata.json `
  --output      output/filled_application.pdf `
  --overwrite
```

---

## Groq vision — how it works internally

1. `make-coordinate-guide` renders each page to a PNG with a point-unit grid.
2. `generate-coordinate-map` loops over the PNGs **one at a time** (one API
   call per page). Sending all pages in a single call would be very expensive
   and hit context limits.
3. Each call sends a compact system prompt describing the field schema and one
   example, plus the single page PNG. The model returns a JSON fragment
   containing only the fields detected on that page.
4. The per-page field dicts are merged into a single `CoordinateMap` object,
   which is validated by Pydantic before being written to disk.
5. Retries (default 3) are applied per page if the model returns invalid JSON.

Model used: `meta-llama/llama-4-scout-17b-16e-instruct` (configurable via
`GROQ_MODEL` in `.env`).

**Groq settings** (all optional, set in `.env`):

| Variable           | Default                                           |
| ------------------ | ------------------------------------------------- |
| `GROQ_API_KEY`     | *(required)*                                      |
| `GROQ_MODEL`       | `meta-llama/llama-4-scout-17b-16e-instruct`       |
| `GROQ_TEMPERATURE` | `0.1`                                             |
| `GROQ_MAX_RETRIES` | `3`                                               |

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
provided". `0` and `false` are treated as explicit values.

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
  "page": 1, "x": 24, "y": 190,
  "font": "helv", "font_size": 10, "align": "left",
  "max_width": 550, "overflow": "shrink", "min_font_size": 7,
  "required": true
}
```

#### `multiline_text`

```json
{
  "type": "multiline_text",
  "source": "applicant.home_address",
  "page": 2, "x": 24, "y": 325,
  "font_size": 9, "max_width": 420, "line_height": 11,
  "max_lines": 5, "overflow": "error", "required": true
}
```

`max_width` and `line_height` are required.

#### `checkbox`

Boolean (checked when source value is truthy):

```json
{ "type": "checkbox", "source": "travel.purpose.tourism",
  "page": 3, "x": 27, "y": 200, "box_size": 8, "check_style": "x" }
```

Option-style (checked when value matches `checked_when`, case-insensitive):

```json
{ "type": "checkbox", "source": "applicant.sex",
  "page": 1, "x": 27, "y": 511,
  "box_size": 8, "checked_when": "male", "check_style": "x" }
```

`check_style` is one of `"x"`, `"check"`, `"filled_square"`.

#### `date`

```json
{
  "type": "date", "source": "applicant.date_of_birth",
  "page": 1, "x": 24, "y": 360,
  "format": "%d-%m-%Y", "max_width": 180, "overflow": "error",
  "required": true
}
```

`format` is a Python `strftime` string.

#### `signature_text`

Same options as `text`, with `overflow` defaulting to `shrink` and a larger
default font size.

#### `image` (placeholder)

Reserved for future photo support. Raises `UnsupportedFieldTypeError` if used.

---

## Coordinate system

`pdf-filler` uses PyMuPDF coordinates throughout:

- Origin is the **top-left** corner of each page.
- `x` increases to the **right**.
- `y` increases **downward**.
- Units are **PDF points** (1 inch = 72 pt).
- A4 page ~= **595 x 842 pt**. US Letter ~= **612 x 792 pt**.

Use `inspect-template` to confirm a specific template's per-page geometry.

---

## Manual coordinate calibration

If you prefer full manual control (or want to tune Groq-generated coordinates):

1. Render guide PNGs, open `page_01_guide.png` in any image viewer.
2. Locate each field and read its top-left (x, y) off the labelled grid.
3. Add the entry to `coordinate_map.json`.
4. Test-fill with `--debug-boxes` and inspect the result.
5. Nudge coordinates as needed:
   - increase `x` → move right, decrease → move left
   - increase `y` → move down, decrease → move up
6. For checkboxes, pick (x, y) at the **top-left of the printed box**.

---

## Programmatic API

```python
from pathlib import Path
from pdf_filler import PdfFiller
from pdf_filler.coordinates import load_coordinate_map
from pdf_filler.validators import load_template_metadata, validate_input_data

template   = Path("templates/schengen/template.pdf")
coord_map  = load_coordinate_map(Path("templates/schengen/coordinate_map.json"))
metadata   = load_template_metadata(Path("templates/schengen/template_metadata.json"))
data       = validate_input_data(Path("examples/input_data.example.json"))

filler = PdfFiller(template, coord_map, metadata=metadata)
result = filler.fill(data, Path("output/filled.pdf"), overwrite=True)
print(result.fields_written, result.fields_skipped)
```

---

## Production notes

- **Lock the template by SHA-256.** Run `hash-template --update-metadata`
  whenever you adopt a new official form version. Filling will refuse to run
  against a different template unless `--ignore-template-hash` is passed.
- **Version coordinate maps** alongside the template version
  (`template_version` field) — embassies do re-issue forms.
- **Always review Groq-generated maps.** The auto-generated map is a starting
  point. Verify with `--debug-boxes` before using on real applications.
- **Avoid logging PII.** The included logger logs field *names* and outcomes,
  not values.
- **Constrain output paths.** Use `pdf_filler.utils.safe_resolve_output_path`
  if accepting paths from untrusted callers.

---

## Running the tests

```powershell
pytest -q
```

Tests synthesise a 4-page A4 PDF on the fly — no real template needed.

---

## Roadmap

- FastAPI wrapper around the engine.
- Image / photo placement (`image` field type is reserved for this).
- Database-backed batch filling.
- Groq result confidence scoring and interactive review mode.
