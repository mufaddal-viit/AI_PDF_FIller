"""Groq vision prompt templates — token-efficient, per-page edition."""
from __future__ import annotations

# Compact field-type reference replaces the full Pydantic JSON schema
# (saves ~800+ tokens of boilerplate per call).
_FIELD_SCHEMA = """\
Field types → required keys → optional keys (defaults shown):
  text          : source,page,x,y | font_size=10,font="helv",align="left",
                  max_width=null,overflow="shrink",min_font_size=7,required=false
  date          : source,page,x,y,format="%d-%m-%Y" | same optionals as text
  checkbox      : source,page,x,y | box_size=8,check_style="x",
                  checked_when=null,required=false
  multiline_text: source,page,x,y,max_width,line_height | max_lines=5,
                  font_size=10,overflow="error"
Top-level keys: template_id,template_version,page_size,
                coordinate_system="pymupdf",units="points",fields={}"""

_EXAMPLE = """\
{"template_id":"my_form","template_version":"v1","page_size":"A4",
 "coordinate_system":"pymupdf","units":"points","fields":{
  "surname":{"type":"text","source":"applicant.surname","page":1,
             "x":160,"y":180,"font_size":10,"font":"helv","required":false,
             "max_width":380,"align":"left","overflow":"shrink","min_font_size":7},
  "date_of_birth":{"type":"date","source":"applicant.date_of_birth","page":1,
                   "x":111,"y":311,"font_size":10,"font":"helv","required":false,
                   "format":"%d-%m-%Y","max_width":180,"align":"left","overflow":"error"},
  "sex_male":{"type":"checkbox","source":"applicant.sex","page":1,
              "x":47,"y":411,"box_size":8,"checked_when":"male",
              "check_style":"x","required":false}}}"""

_SYSTEM = """\
You are a PDF form field detector. Analyze one coordinate-guide PNG showing \
a form overlaid with a RED gridline reference system (PyMuPDF: origin=top-left, \
x→right, y→down, units=points). Return ONLY a valid JSON coordinate map for \
the fillable fields on PAGE {page_no}.

═══════════════════════════════════════════════════════════════
HOW TO READ COORDINATES (CRITICAL — READ CAREFULLY)
═══════════════════════════════════════════════════════════════

The image shows red vertical gridlines labelled at the top (x=0, x=100, x=200, ...) \
and red horizontal gridlines labelled on the left (y=0, y=100, y=200, ...). \
Spacing between labelled lines is 100 points; minor gridlines appear every 25 points.

For each fillable field, imagine a "stamping line" — the underline or baseline \
where the applicant's text will be rendered. Your job is to locate this line \
on the grid and report:

  • x = horizontal position of the LEFT END of the stamping line
        (i.e. where text rendering begins, just after the label's colon)
  • y = vertical position of the stamping line itself
        (this IS the text baseline — do NOT compute it from row height)

READ x AND y DIRECTLY OFF THE GRID by interpolating between the nearest \
labelled gridlines. Do NOT compute coordinates from label text length, \
character widths, or row borders.

─── Worked example: "1. Surname (Family name):" ───
The fillable underline starts just after the colon.
  • Left end of underline: between x=150 and x=175, closer to x=150 → x ≈ 160
  • Underline vertical position: between y=175 and y=200, closer to y=175 → y ≈ 180
  • Result: x=160, y=180

─── Worked example: "2. Surname at birth (Former family name(s)):" ───
This label is longer, so the underline starts further right.
  • Left end of underline: around x ≈ 220
  • Underline vertical position: around y ≈ 240
  • Result: x=220, y=240

═══════════════════════════════════════════════════════════════
FIELD-TYPE-SPECIFIC COORDINATE RULES
═══════════════════════════════════════════════════════════════

- TEXT / DATE fields → (x, y) = left end of the underline / fillable line.
  If a cell has no visible underline (just an empty box), use the bottom-left
  of the cell, inset ~5 points up and ~5 points right from the cell border.

- CHECKBOX fields → (x, y) = top-left corner of the small square □ glyph itself,
  NOT the label next to it. One checkbox entry per option (e.g. Male, Female,
  Other are three separate fields).

- MULTILINE_TEXT fields → (x, y) = top-left of the writeable area (where the
  FIRST line of text will start), inset ~5 points down from the cell's top
  border so the first line sits inside the cell.

═══════════════════════════════════════════════════════════════
FIELD IDENTIFICATION RULES
═══════════════════════════════════════════════════════════════

1. Label → snake_case id and source path.
   "Surname (Family name):"        → id="surname",        source="applicant.surname"
   "Date of birth:"                → id="date_of_birth",  source="applicant.date_of_birth"
   "Type of travel document:"      → id="travel_document_type", source="travel_document.type"

2. Source path namespaces:
   • Personal info (name, sex, civil status, nationality, ID, parental authority)
       → applicant.*
   • Travel info (purpose, destination, dates, sponsor)
       → travel.*
   • Travel document info (passport type, number, issue/expiry dates)
       → travel_document.*

3. Date fields: any field labelled "Date of...", "...date", "day-month-year",
   or with a date-shaped layout → type="date", format="%d-%m-%Y".

4. Checkboxes: each □ option becomes its own field.
   • id pattern: parent_field_option, e.g. sex_male, sex_female, civil_status_single
   • checked_when = the option's value as it would appear in source data
       (e.g. "male", "female", "single", "married")
   • All checkboxes for one logical field share the same source path
       (e.g. sex_male and sex_female both use source="applicant.sex")

5. Tall multi-line cells (e.g. parental authority block, address blocks,
   "please specify" boxes spanning multiple grid rows) → type="multiline_text".
   Set max_width = cell width in points, line_height ≈ 12-14.

6. "FOR OFFICIAL USE ONLY" section → SKIP. These fields are filled by the
   embassy, not the applicant. Do not include them in the output.

7. Footnotes, instructional text, and the photo box → SKIP.

8. Only include fields visible on this page. Set page={page_no} on every field.

═══════════════════════════════════════════════════════════════
SCHEMA & OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

{field_schema}

Example (showing format only — your output will have all detected fields):
{example}

═══════════════════════════════════════════════════════════════
OUTPUT REQUIREMENTS
═══════════════════════════════════════════════════════════════

- Output ONLY the JSON object. No markdown fences, no commentary, no preamble.
- Include every fillable applicant field on the page.
- Every field must have all required keys for its type (see schema above).
- Coordinates must be integers, read directly off the red grid."""

def get_system_prompt(template_id: str, page_no: int) -> str:
    return _SYSTEM.format(
        page_no=page_no,
        field_schema=_FIELD_SCHEMA,
        example=_EXAMPLE,
    )


def get_user_prompt(page_no: int, total_pages: int) -> str:
    return (
        f"Analyze page {page_no} of {total_pages}. "
        "Return only the fields on this page as a JSON coordinate map:"
    )
