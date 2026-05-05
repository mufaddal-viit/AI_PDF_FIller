# FastAPI Backend for pdf-filler

## Plana

**Info Gathered**: CLI ready; add FastAPI for /generate-map, /fill endpoints.a

**Plan**:
1. pyproject.toml: deps.
2. api/main.py: FastAPI app.
3. api/models.py: Pydantic req.
4. api/routers/pdf.py: Endpoints.
5. api/utils.py: Temp files.
6. README update.

**Deps**: fastapi[standard], uvicorn[standard].

**Endpoints**:
- POST /generate-map: PDF bytes → map JSON
- POST /fill: PDF, data dict, map → PDF bytes

Confirm?