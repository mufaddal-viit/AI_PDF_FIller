# Groq Coordinate Map Generator Integration
Track progress on integrating Groq vision API to auto-generate coordinate_map.json from page guides.

## Steps (check off as completed)

### 1. [x] Update dependencies
- Edit pyproject.toml: add groqclient>=0.6.1, httpx[http2], python-dotenv to dependencies/dev.
- Update requirements.txt.
- pip install -e .[dev,groq]

### 2. [x] Config files
- Create .env.example with GROQ_API_KEY=your_key_here
- src/pdf_filler/groq_config.py: load_dotenv, pydantic settings (key, model='llama-3.2-11b-vision-preview', base_url).

### 3. [x] Prompt template
- src/pdf_filler/groq_prompt.py: SYSTEM_PROMPT str w/ few-shot (use provided coordinate_map.json), model_json_schema from models.CoordinateMap.

### 4. [x] Groq vision client
- src/pdf_filler/groq_vision.py created: load_page_guides, png_to_base64_image, generate_coordinate_map (retries, validation, Groq SDK).

### 5. [x] CLI integration
- Edit src/pdf_filler/cli.py: Added @app.command('generate-coordinate-map') (template_id arg, guides_dir/output_dir, Groq → JSON + summary).

### 6. [x] Docs
- Updated README.md: Added "Auto-Generate Coordinate Maps with Groq Vision" section w/ usage.

### 7. [ ] Test end-to-end (user action)
- Ensure templates/schengen/template.pdf exists.
- `pdf-filler make-coordinate-guide --template templates/schengen/template.pdf --output output/page_guides`
- `pdf-filler generate-coordinate-map schengen_visa_application`
- `pdf-filler validate-coordinate-map templates/schengen_visa_application/coordinate_map.json`
- `pdf-filler fill ... --coordinates templates/schengen_visa_application/coordinate_map.json`
- Review.

**Current Progress: Steps 1-5 complete. Run `pip install -e .[groq]` then test:**

**Notes:**
- Schema from models.CoordinateMap.model_json_schema().
- Handle multi-page: List all PNGs in single prompt.
- Defaults in prompt for robust output.
- Error: Retry, fallback manual.

