from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Optional

import typer

from core.driver import InMemoryCalcDriver, WorkbookSnapshot
from core.reasoning import GemmaModelChoice, GoogleAIBackend, OllamaBackend, VitreusReasoning
from core.vision import VisionInput


app = typer.Typer(help="Vitreus: local-first Gemma 4 spreadsheet intelligence.")


@app.command()
def models() -> None:
    """Show the Gemma 4 model selection used by Vitreus."""
    choice = GemmaModelChoice.default()
    typer.echo(f"Primary: {choice.primary} (Gemma 4 31B Dense)")
    typer.echo(f"Drafter: {choice.drafter} (Gemma 4 4B)")
    typer.echo(f"Why: {choice.rationale}")


@app.command()
def analyze(
    csv_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    query: Annotated[str, typer.Argument(help="Natural-language spreadsheet request.")],
    sheet_name: Annotated[str, typer.Option("--sheet", "-s")] = "Sheet1",
    backend: Annotated[str, typer.Option("--backend", "-b", help="Backend: fallback | ollama | google")] = "fallback",
    api_key: Annotated[
        Optional[str], typer.Option("--api-key", envvar="GEMINI_API_KEY", help="Google AI Studio API key.")
    ] = None,
    model: Annotated[Optional[str], typer.Option("--model", "-m", help="Override model name for the chosen backend.")] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Save result directly to this file (.csv or .xlsx). Skips printing the manifest.",
        ),
    ] = None,
) -> None:
    """Analyze a CSV or XLSX workbook and either print the JSON manifest or save the result with --output.

    \b
    --output result.csv   Saves modified data. Highlights → _highlights.json sidecar.
                          ⚠ CSV cannot store colors or formulas natively.
    --output result.xlsx  Saves cell values, formulas, AND highlight colors in one file.
    """
    selected_backend = None
    if backend == "ollama":
        selected_backend = OllamaBackend(model=model or "gemma4:31b")
    elif backend == "google":
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            typer.echo(
                "Error: --backend google requires an API key via --api-key or GEMINI_API_KEY env var.",
                err=True,
            )
            raise typer.Exit(code=1)
        selected_backend = GoogleAIBackend(api_key=key, model=model or "gemma-4-31b-it")

    snapshot = WorkbookSnapshot.from_file(str(csv_path), sheet_name=sheet_name)
    active_sheet = sheet_name if sheet_name in snapshot.sheets else next(iter(snapshot.sheets))
    sheet_data = snapshot.sheets[active_sheet]
    max_row = len(sheet_data)
    max_col = len(sheet_data[0]) if max_row else 1
    context = snapshot.range_to_json(f"{active_sheet}!A1:{_column_name(max_col - 1)}{max_row}")
    manifest = VitreusReasoning(backend=selected_backend).plan_action_sync(query, context, sheet_name=active_sheet)

    if output is None:
        # Default: print the manifest JSON so it can be piped or inspected.
        typer.echo(json.dumps(manifest, indent=2))
        return

    # One-shot mode: apply the manifest and save to the output file.
    driver = InMemoryCalcDriver(snapshot)
    driver.execute_manifest(manifest)
    summary_applied = len([a for a in manifest.get("actions", []) if a.get("type") in ("write_value", "formula", "highlight")])

    ext = output.suffix.lower()
    if ext == ".xlsx":
        snapshot.save_xlsx(str(output), sheet_name=active_sheet, formats=driver.formats)
    else:
        # CSV: save data; colors go to a sidecar.
        snapshot.save_csv(str(output), sheet_name=active_sheet)
        typer.echo(
            f"⚠ CSV format cannot store cell colors or formulas.\n"
            f"  • write_value changes are saved in {output.name}\n"
            f"  • Highlight colors → {output.stem}_highlights.json\n"
            f"  Tip: use --output result.xlsx to preserve everything in one file.",
            err=True,
        )
        if driver.formats:
            sidecar = output.parent / (output.stem + "_highlights.json")
            sidecar.write_text(
                json.dumps(
                    {cell: {"background": fmt.background} for cell, fmt in driver.formats.items()},
                    indent=2,
                ),
                encoding="utf-8",
            )

    typer.echo(json.dumps({"applied": summary_applied, "saved": str(output), "errors": []}))



@app.command("apply-manifest")
def apply_manifest(
    csv_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Save modified sheet to this CSV path. Highlights written to <output>_highlights.json."),
    ] = None,
    sheet_name: Annotated[str, typer.Option("--sheet", "-s")] = "Sheet1",
) -> None:
    """Apply a manifest against a CSV-backed in-memory sheet and print the summary.

    With --output, write_value and formula changes are saved back to a new CSV.
    Cell highlights (which cannot be stored in CSV) are written to a sidecar
    <output>_highlights.json file alongside the CSV.
    """
    snapshot = WorkbookSnapshot.from_file(str(csv_path), sheet_name=sheet_name)
    active_sheet = sheet_name if sheet_name in snapshot.sheets else next(iter(snapshot.sheets))
    driver = InMemoryCalcDriver(snapshot)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = driver.execute_manifest(manifest)

    if output is not None:
        ext = output.suffix.lower()
        if ext == ".xlsx":
            snapshot.save_xlsx(str(output), sheet_name=active_sheet, formats=driver.formats)
            typer.echo(f"Saved: {output}", err=True)
        else:
            snapshot.save_csv(str(output), sheet_name=active_sheet)
            if driver.formats:
                sidecar = output.parent / (output.stem + "_highlights.json")
                sidecar.write_text(
                    json.dumps({cell: {"background": fmt.background} for cell, fmt in driver.formats.items()}, indent=2),
                    encoding="utf-8",
                )
                typer.echo(f"Saved: {output}  |  Highlights: {sidecar}", err=True)
            else:
                typer.echo(f"Saved: {output}", err=True)

    typer.echo(json.dumps({"applied": summary.applied, "errors": summary.errors}))


@app.command()
def vision(
    image_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    purpose: Annotated[str, typer.Option("--purpose", "-p")] = "chart",
) -> None:
    """Prepare an image payload for Gemma 4 multimodal reasoning."""
    typer.echo(json.dumps(VisionInput.from_file(image_path, purpose=purpose).to_prompt_payload(), indent=2))


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name
