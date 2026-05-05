"""FastAPI backend for pdf-filler."""
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
import tempfile
import shutil
import os
from pathlib import Path
from typing import List

from pdf_filler.groq_vision import generate_coordinate_map
from pdf_filler.filler import PdfFiller
from pdf_filler.coordinates import load_coordinate_map
from pdf_filler.validators import validate_input_data, load_template_metadata
from pdf_filler.render_check import render_coordinate_guide
from pdf_filler.exceptions import PdfFillerError

app = FastAPI(title="PDF Filler API", version="0.1.0")

class GenerateRequest(BaseModel):
    template_id: str
    version: str = "auto-v1"
    page_size: str = "A4"
    max_pages: int | None = None

class FillRequest(BaseModel):
    data: dict
    coordinate_map: dict  # JSON map

@app.post("/generate-map")
async def generate_map(pdf: UploadFile = File(...), req: GenerateRequest = Depends()):
    """Upload PDF → generate grid PNGs (temp) → Groq → coordinate_map JSON."""
    if not pdf.filename.endswith('.pdf'):
        raise HTTPException(400, "Upload PDF only")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "template.pdf"
        with pdf_path.open("wb") as f:
            shutil.copyfileobj(pdf.file, f)
        
        guides_dir = Path(tmpdir) / "page_guides"
        render_coordinate_guide(pdf_path, guides_dir)
        
        coord_map = generate_coordinate_map(req.template_id, guides_dir, req.version, req.page_size, max_pages=req.max_pages)
    
    return coord_map.model_dump()

@app.post("/fill")
async def fill_pdf(pdf: UploadFile = File(...), request: FillRequest = Depends()):
    """Fill PDF using data & map."""
    if not pdf.filename.endswith('.pdf'):
        raise HTTPException(400, "Upload PDF only")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "template.pdf"
        with template_path.open("wb") as f:
            shutil.copyfileobj(pdf.file, f)
        
        # Temp JSONs
        data_path = Path(tmpdir) / "data.json"
        with data_path.open("w") as f:
            json.dump(request.data, f)
        
        map_path = Path(tmpdir) / "map.json"
        with map_path.open("w") as f:
            json.dump(request.coordinate_map, f)
        
        coord_map = load_coordinate_map(map_path)
        data = validate_input_data(data_path)
        
        filler = PdfFiller(template_path, coord_map)
        out_path = Path(tmpdir) / "filled.pdf"
        filler.fill(data, out_path, overwrite=True)
        
        return StreamingResponse(out_path.open("rb"), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=filled.pdf"})

@app.get("/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

