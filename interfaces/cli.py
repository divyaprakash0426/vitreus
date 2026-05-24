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
) -> None:
    """Analyze a CSV snapshot and print a JSON action manifest."""
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

    snapshot = WorkbookSnapshot.from_csv(str(csv_path), sheet_name=sheet_name)
    max_row = len(snapshot.sheets[sheet_name])
    max_col = len(snapshot.sheets[sheet_name][0]) if max_row else 1
    context = snapshot.range_to_json(f"{sheet_name}!A1:{_column_name(max_col - 1)}{max_row}")
    manifest = VitreusReasoning(backend=selected_backend).plan_action_sync(query, context, sheet_name=sheet_name)
    typer.echo(json.dumps(manifest, indent=2))



@app.command("apply-manifest")
def apply_manifest(
    csv_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Apply a manifest against a CSV-backed in-memory sheet and print the summary."""
    snapshot = WorkbookSnapshot.from_csv(str(csv_path))
    driver = InMemoryCalcDriver(snapshot)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = driver.execute_manifest(manifest)
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
