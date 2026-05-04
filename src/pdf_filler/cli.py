"""Typer-based command-line interface for ``pdf_filler``.

Six commands now:
* ``fill`` — fill template.
* ``inspect-template`` — page geometry.
* ``make-coordinate-guide`` — grid PNGs for manual coords.
* ``generate-coordinate-map`` — Groq vision auto-gen from guides.
* ``validate-coordinate-map`` — validate JSON map.
* ``hash-template`` — SHA-256 template.

"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .coordinates import load_coordinate_map, summarise_coordinate_map
from .exceptions import PdfFillerError
from .filler import PdfFiller
from .logging_config import configure_logging
from .render_check import inspect_template, render_coordinate_guide
from .utils import sha256_file
from .validators import load_template_metadata, validate_input_data

app = typer.Typer(
    name="pdf-filler",
    help="Coordinate-based static PDF template filler.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


# Common helpers
VerboseOpt = Annotated[
    bool,
    typer.Option("--verbose", "-v", help="Enable debug logging."),
]


def _bootstrap_logging(verbose: bool) -> None:
    configure_logging(level=logging.DEBUG if verbose else logging.INFO, force=True)


def _abort(msg: str, *, code: int = 1) -> None:
    console.print(f"[red]Error:[/red] {msg}")
    raise typer.Exit(code=code)


# Existing commands (unchanged)
@app.command("fill")
def fill_cmd(
    template: Annotated[Path, typer.Option("--template", help="Path to template PDF.")],
    data: Annotated[Path, typer.Option("--data", help="Path to input data JSON.")],
    coordinates: Annotated[Path, typer.Option("--coordinates", help="Path to coordinate map JSON.")],
    output: Annotated[Path, typer.Option("--output", help="Path to write filled PDF.")],
    metadata: Annotated[Path | None, typer.Option("--metadata", help="Optional template metadata JSON.")] = None,
    ignore_template_hash: Annotated[bool, typer.Option("--ignore-template-hash", help="Skip SHA-256 hash check against metadata.")] = False,
    debug_boxes: Annotated[bool, typer.Option("--debug-boxes", help="Draw faint outlines around field target areas.")] = False,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Overwrite existing output file.")] = False,
    verbose: VerboseOpt = False,
) -> None:
    """Fill a template PDF with values from a JSON data file."""
    _bootstrap_logging(verbose)

    try:
        coord_map = load_coordinate_map(coordinates)
        meta = load_template_metadata(metadata)
        input_data = validate_input_data(data)

        filler = PdfFiller(template, coord_map, metadata=meta)
        result = filler.fill(
            data=input_data,
            output_path=output,
            debug_boxes=debug_boxes,
            ignore_template_hash=ignore_template_hash,
            overwrite=overwrite,
        )
    except PdfFillerError as exc:
        _abort(str(exc))
    except FileNotFoundError as exc:
        _abort(f"File not found: {exc}")

    table = Table(title="Fill result")
    table.add_column("Output")
    table.add_column("Pages")
    table.add_column("Written")
    table.add_column("Skipped")
    table.add_row(
        str(result.output_path),
        str(result.page_count),
        str(len(result.fields_written)),
        str(len(result.fields_skipped)),
    )
    console.print(table)
    if result.warnings:
        console.print(Panel("\\n".join(result.warnings), title="Warnings", style="yellow"))
    console.print(f"[green]Wrote[/green] {result.output_path}")


@app.command("inspect-template")
def inspect_template_cmd(
    template: Annotated[Path, typer.Option("--template", help="Path to template PDF.")],
    page: Annotated[int | None, typer.Option("--page", help="1-based page (default: all).")] = None,
    verbose: VerboseOpt = False,
) -> None:
    """Print page count and geometry for a template PDF."""
    _bootstrap_logging(verbose)
    try:
        info = inspect_template(template, page=page)
    except PdfFillerError as exc:
        _abort(str(exc))
    except ValueError as exc:
        _abort(str(exc))

    console.print(
        Panel(
            f"[bold]{info.template_path}[/bold]\\n"
            f"page count: {info.page_count}\\n\\n"
            f"{info.coordinate_system}",
            title="Template",
        )
    )

    table = Table(title="Pages")
    table.add_column("Page", justify="right")
    table.add_column("Width (pt)", justify="right")
    table.add_column("Height (pt)", justify="right")
    for p in info.pages:
        table.add_row(str(p.page_number), f"{p.width:.2f}", f"{p.height:.2f}")
    console.print(table)


@app.command("make-coordinate-guide")
def make_coordinate_guide_cmd(
    template: Annotated[Path, typer.Option("--template", help="Path to template PDF.")],
    output: Annotated[Path, typer.Option("--output", help="Output dir for PNG guides.")] = Path("output/page_guides"),
    grid_step: Annotated[float, typer.Option("--grid-step", help="Minor grid (pt).")] = 25.0,
    major_step: Annotated[float, typer.Option("--major-step", help="Major grid (pt).")] = 100.0,
    zoom: Annotated[float, typer.Option("--zoom", help="Raster zoom.")] = 2.0,
    verbose: VerboseOpt = False,
) -> None:
    """Render PNGs with coordinate grid overlay for calibration."""
    _bootstrap_logging(verbose)
    try:
        written = render_coordinate_guide(template_path=template, output_dir=output, grid_step=grid_step, major_step=major_step, zoom=zoom)
    except PdfFillerError as exc:
        _abort(str(exc))
    console.print(f"[green]Wrote[/green] {len(written)} guides to {output}")
    for path in written:
        console.print(f"  [dim]- {path}[/dim]")


@app.command("validate-coordinate-map")
def validate_coordinate_map_cmd(
    coordinates: Annotated[Path, typer.Option("--coordinates", help="Path to map JSON.")],
    verbose: VerboseOpt = False,
) -> None:
    """Validate coordinate map JSON."""
    _bootstrap_logging(verbose)
    try:
        coord_map = load_coordinate_map(coordinates)
    except PdfFillerError as exc:
        _abort(str(exc))

    summary = summarise_coordinate_map(coord_map)
    console.print(Panel(json.dumps(summary, indent=2), title="Coordinate Map Summary"))


@app.command("hash-template")
def hash_template_cmd(
    template: Annotated[Path, typer.Option("--template", help="Path to template PDF.")],
    update_metadata: Annotated[Path | None, typer.Option("--update-metadata", help="Update metadata JSON w/ hash.")] = None,
    verbose: VerboseOpt = False,
) -> None:
    """Print SHA-256 hash of template PDF."""
    _bootstrap_logging(verbose)
    if not template.exists():
        _abort(f"Template not found: {template}")
    digest = sha256_file(template)
    console.print(f"[green]SHA-256:[/green] [blue]{digest}[/blue]  [dim]{template}[/dim]")
    
    if update_metadata:
        if not update_metadata.exists():
            _abort(f"Metadata not found: {update_metadata}")
        try:
            with update_metadata.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["sha256"] = digest
            with update_metadata.open("w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
                f.write("\\n")
            console.print(f"[green]Updated[/green] {update_metadata}")
        except json.JSONDecodeError as e:
            _abort(f"Invalid JSON: {e}")


@app.command("generate-coordinate-map")
def generate_coordinate_map_cmd(
    template_id: Annotated[str, typer.Argument(help="Template ID (e.g. schengen_visa_application)")],
    guides_dir: Annotated[Path, typer.Option(help="Directory containing page_*_guide.png files.")] = Path("output/page_guides"),
    output_dir: Annotated[Path, typer.Option(help="Output root; writes {template_id}/coordinate_map.json.")] = Path("templates"),
    version: Annotated[str, typer.Option(help="Version string embedded in the map.")] = "auto-v1",
    page_size: Annotated[str, typer.Option(help="Page size reported in the map (A4, Letter, …).")] = "A4",
    verbose: VerboseOpt = False,
) -> None:
    """Auto-generate coordinate_map.json via Groq vision on page-guide PNGs."""
    _bootstrap_logging(verbose)

    # Lazy import — only load Groq modules when this command is actually invoked.
    try:
        from .groq_vision import generate_coordinate_map as _gen_map  # noqa: PLC0415
    except ImportError as exc:
        _abort(f"Groq dependencies not installed: {exc}")

    if not Path(".env").exists():
        _abort(".env missing; copy .env.example and add GROQ_API_KEY.")

    try:
        coord_map = _gen_map(template_id, guides_dir, version, page_size)

        out_dir = output_dir / template_id
        out_dir.mkdir(exist_ok=True, parents=True)
        out_path = out_dir / "coordinate_map.json"

        with out_path.open("w", encoding="utf-8") as f:
            json.dump(coord_map.model_dump(), f, indent=2)
            f.write("\n")

        summary = summarise_coordinate_map(coord_map)
        console.print(Panel(json.dumps(summary, indent=2), title="Generated Coordinate Map"))
        console.print(f"[green]Saved:[/green] [bold cyan]{out_path}[/bold cyan]")

    except Exception as exc:
        _abort(str(exc))


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(main())

