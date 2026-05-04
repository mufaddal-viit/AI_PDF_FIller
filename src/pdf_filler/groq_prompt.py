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

# Minimal valid example — no JSON comments, only 3 fields.
_EXAMPLE = """\
{"template_id":"my_form","template_version":"v1","page_size":"A4",
 "coordinate_system":"pymupdf","units":"points","fields":{
  "surname":{"type":"text","source":"applicant.surname","page":1,
             "x":175,"y":180,"font_size":10,"font":"helv","required":false,
             "max_width":380,"align":"left","overflow":"shrink","min_font_size":7},
  "date_of_birth":{"type":"date","source":"applicant.date_of_birth","page":1,
                   "x":111,"y":311,"font_size":10,"font":"helv","required":false,
                   "format":"%d-%m-%Y","max_width":180,"align":"left","overflow":"error"},
  "sex_male":{"type":"checkbox","source":"applicant.sex","page":1,
              "x":27,"y":511,"box_size":8,"checked_when":"male",
              "check_style":"x","required":false}}}"""

_SYSTEM = """\
You are a PDF form field detector. Analyze one coordinate-guide PNG \
(PyMuPDF grid: origin=top-left, x→right, y→down, units=points).
Return ONLY a valid JSON coordinate map for the fields on PAGE {page_no}.

Rules:
1. Coordinates: use the grid label at the TOP-LEFT corner of each fillable area.
2. TEXT lines/boxes → type="text". Label in snake_case → id and source
   (e.g. "Surname:" → id="surname", source="applicant.surname").
3. DATE fields → type="date", format="%d-%m-%Y".
4. Small checkboxes → type="checkbox", one per option
   (e.g. "Male" box → id="sex_male", checked_when="male", source="applicant.sex").
5. Tall multi-line box → type="multiline_text".
6. Source paths: personal → applicant.*, travel → travel.*, document → travel_document.*
7. Only include fields visible on this page. Set page={page_no} on every field.

{field_schema}

Example:
{example}

Output ONLY the JSON object (no markdown fences)."""


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
