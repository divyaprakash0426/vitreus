"""Vitreus command-line interface.

Stdout is always machine-readable (JSON, or plain text for `ask`); progress, tables and
warnings go to stderr so the CLI composes cleanly with pipes and Nushell.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from core.agent import AgentError, SpreadsheetAgent
from core.backends import Backend, BackendError, FallbackBackend, make_backend, ollama_reachable
from core.config import BACKENDS, Settings, config_template, default_config_path, load_settings
from core.driver import ManifestSummary, WorkbookDriver, WorkbookSnapshot, diff_snapshots
from core.manifest import Manifest, ManifestValidationError, risky_formulas, validate_manifest
from core.reasoning import GemmaModelChoice
from core.vision import VisionError, VisionInput, encode_image, extract_table
from interfaces import ui

app = typer.Typer(
    help="Vitreus — local-first Gemma 4 agent for spreadsheet work and automation.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
calc_app = typer.Typer(help="Control a live LibreOffice Calc session over UNO.", no_args_is_help=True)
app.add_typer(calc_app, name="calc")

# ─── shared option types ─────────────────────────────────────────────────────

BackendOpt = Annotated[Optional[str], typer.Option("--backend", "-b", help="auto | ollama | google | openrouter | openai | fallback")]
ModelOpt = Annotated[Optional[str], typer.Option("--model", "-m", help="Override the model ID for the chosen backend")]
FastOpt = Annotated[bool, typer.Option("--fast", help="Use the drafter model (gemma4:e4b class) for lower latency")]
ApiKeyOpt = Annotated[Optional[str], typer.Option("--api-key", help="Google AI Studio key (or set GEMINI_API_KEY)", envvar="GEMINI_API_KEY")]
SheetOpt = Annotated[Optional[str], typer.Option("--sheet", "-s", help="Sheet to focus on (default: first / active)")]
AllSheetsOpt = Annotated[bool, typer.Option("--all-sheets", help="Show every sheet in the model context")]
ContextTokensOpt = Annotated[Optional[int], typer.Option("--context-tokens", help="Token budget for workbook context")]
ImageOpt = Annotated[Optional[list[Path]], typer.Option("--image", "-i", help="Attach image(s) (receipt, chart) for multimodal reasoning", exists=True, dir_okay=False)]
PortOpt = Annotated[Optional[int], typer.Option("--port", help="UNO socket port of the live Calc session (with --live)")]


# ─── helpers ────────────────────────────────────────────────────────────────


def _settings(
    backend: str | None = None,
    model: str | None = None,
    fast: bool = False,
    api_key: str | None = None,
    context_tokens: int | None = None,
    port: int | None = None,
) -> Settings:
    overrides: dict[str, Any] = {}
    if backend:
        if backend not in BACKENDS:
            _fail(f"Unknown backend '{backend}'", hint=f"choose one of: {', '.join(BACKENDS)}")
        overrides["backend"] = backend
    if model:
        overrides["model"] = model
    if fast:
        overrides["fast"] = True
    if api_key:
        overrides["gemini_api_key"] = api_key
    if context_tokens:
        overrides["context_tokens"] = context_tokens
    if port:
        overrides["calc_port"] = port
    return load_settings(overrides=overrides, env=os.environ)


def _fail(message: str, hint: str = "", code: int = 1) -> None:
    ui.error(message, hint)
    raise typer.Exit(code)


def _backend(settings: Settings) -> tuple[Backend, str]:
    try:
        backend, reason = make_backend(settings)
    except BackendError as exc:
        _fail(str(exc).split("\n")[0], hint=exc.hint)
    if isinstance(backend, FallbackBackend):
        ui.warn(f"No Gemma backend available — using the rule-based fallback planner ({reason}). Run `vitreus doctor` for details.")
    return backend, reason


def _uno_driver(settings: Settings):
    from core.uno_driver import UnoDriver

    return UnoDriver(port=settings.calc_port, python=settings.uno_python)


def _open_source(path: str | None, sheet: str | None, live: bool, settings: Settings) -> tuple[Any, WorkbookSnapshot, str, str | None]:
    """Return (driver, snapshot, source_name, active_sheet)."""
    if live:
        driver = _uno_driver(settings)
        if not driver.is_available():
            _fail(
                f"No LibreOffice Calc listener on port {settings.calc_port}",
                hint="start one with `vitreus calc launch [file]` (or `soffice --accept=\"socket,host=localhost,port=2002;urp;\"`)",
            )
        snapshot = driver.snapshot()
        title = driver.document_title() or "Calc document"
        snapshot.source = title
        active = sheet if sheet in snapshot.sheets else (snapshot.sheet_names[0] if snapshot.sheet_names else None)
        return driver, snapshot, title, active
    if path is None:
        _fail("Provide a workbook path, '-' for stdin, or --live")
    if path == "-":
        driver = WorkbookDriver.from_stdin(sheet_name=sheet or "Sheet1")
        return driver, driver.snapshot(), "stdin", driver.active_sheet
    file = Path(path)
    if not file.is_file():
        _fail(f"File not found: {file}")
    try:
        driver = WorkbookDriver.from_path(file, sheet_name=sheet)
    except Exception as exc:  # noqa: BLE001 - any loader failure is a user-facing error
        _fail(f"Could not open {file}: {exc}")
    return driver, driver.snapshot(), file.name, driver.active_sheet


def _load_images(paths: list[Path] | None) -> list[bytes]:
    images: list[bytes] = []
    for image_path in paths or []:
        try:
            images.append(encode_image(image_path)[0])
        except Exception as exc:  # noqa: BLE001
            _fail(f"Could not read image {image_path}: {exc}")
    return images


def _plan(
    query: str,
    source: str | None,
    sheet: str | None,
    live: bool,
    all_sheets: bool,
    images: list[Path] | None,
    settings: Settings,
) -> tuple[Any, WorkbookSnapshot, str, Manifest, SpreadsheetAgent]:
    backend, _reason = _backend(settings)
    driver, snapshot, source_name, active = _open_source(source, sheet, live, settings)
    focus = None if all_sheets or active is None else [active]
    agent = SpreadsheetAgent(backend, settings, snapshot, source_name=source_name, focus_sheets=focus)
    try:
        with ui.status(f"Reasoning with {backend.model} via {backend.name}…"):
            result = agent.run(query, images=_load_images(images))
    except (AgentError, BackendError) as exc:
        _fail(str(exc).split("\n")[0], hint=getattr(exc, "hint", ""))
    if result.tool_calls:
        ui.info(f"{result.steps} step(s), tools used: {', '.join(c['tool'] for c in result.tool_calls)}")
    _warn_risky(result.manifest)
    return driver, snapshot, source_name, result.manifest, agent


def _warn_risky(manifest: Manifest, prefix: str = "") -> None:
    for target, formula in risky_formulas(manifest):
        ui.warn(f"{prefix}{target}: formula reaches outside the workbook ({formula[:80]}). Review before applying.")


def _preview(manifest: Manifest, snapshot: WorkbookSnapshot) -> ManifestSummary:
    scratch = WorkbookDriver.from_snapshot(snapshot)
    summary = scratch.execute_manifest(manifest)
    ui.print_manifest(manifest)
    ui.print_diff(diff_snapshots(snapshot, scratch.snapshot()), scratch.formats)
    if summary.errors:
        for err in summary.errors:
            ui.warn(err)
    return summary


def _csv_warning(output: Path, manifest: Manifest) -> None:
    if output.suffix.lower() == ".csv" and any(a.type in {"highlight", "set_format", "add_chart", "add_note", "freeze_panes", "set_column_width"} for a in manifest.actions):
        ui.warn("CSV cannot store formatting: highlight colours go to a <name>_highlights.json sidecar; notes, charts, widths and freeze panes are dropped. Use an .xlsx output to keep them.")


def _emit(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _manifest_json(manifest: Manifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json", exclude_none=True)


# ─── analyze / ask / chat ───────────────────────────────────────────────────


@app.command()
def analyze(
    args: Annotated[list[str], typer.Argument(help='[FILE|-] "QUERY"  (FILE omitted with --live)')],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Apply the manifest and save here (.xlsx or .csv)")] = None,
    in_place: Annotated[bool, typer.Option("--in-place", help="Apply and overwrite the source file")] = False,
    preview: Annotated[bool, typer.Option("--preview", "-p", help="Show the cell diff on stderr; never write")] = False,
    live: Annotated[bool, typer.Option("--live", help="Read from and apply to the running LibreOffice Calc document")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt in --live mode")] = False,
    port: PortOpt = None,
    sheet: SheetOpt = None,
    all_sheets: AllSheetsOpt = False,
    image: ImageOpt = None,
    backend: BackendOpt = None,
    model: ModelOpt = None,
    fast: FastOpt = False,
    api_key: ApiKeyOpt = None,
    context_tokens: ContextTokensOpt = None,
) -> None:
    """Plan spreadsheet changes with Gemma and print an auditable JSON manifest.

    Examples:
      vitreus analyze budget.xlsx "highlight rows where Spent exceeds Budget"
      vitreus analyze budget.xlsx "add a Total row" --output budget_v2.xlsx --preview
      ls | to csv | vitreus analyze - "flag files over 1 MB" -o files.xlsx
      vitreus analyze --live "sort by Amount descending" --yes
    """
    if live:
        source, query = (None, args[0]) if len(args) == 1 else (args[0], args[1])
    elif len(args) == 2:
        source, query = args
    else:
        _fail('Usage: vitreus analyze <FILE|-> "<query>"  |  vitreus analyze --live "<query>"')
    if live and (output is not None or in_place):
        _fail("--live applies to the running Calc document; --output/--in-place are not used", hint="drop --live to write a file, or save from LibreOffice")
    settings = _settings(backend, model, fast, api_key, context_tokens, port)
    driver, snapshot, source_name, manifest, _agent = _plan(query, source, sheet, live, all_sheets, image, settings)

    if preview or live:
        _preview(manifest, snapshot)
    if preview:
        _emit(_manifest_json(manifest))
        return

    if live:
        if not manifest.actions:
            _emit({"applied": 0, "errors": [], "target": source_name, "summary": manifest.summary})
            return
        if not yes and not typer.confirm(f"Apply {len(manifest.actions)} action(s) to '{source_name}'?", err=True):
            ui.info("Aborted; nothing applied.")
            _emit(_manifest_json(manifest))
            raise typer.Exit(2)
        try:
            summary = driver.execute_manifest(manifest)
        except RuntimeError as exc:
            _fail(f"Live apply failed: {exc}", hint="check `vitreus calc status` and retry")
        ui.print_summary(summary, source_name)
        _emit({"applied": summary.applied, "errors": summary.errors, "target": source_name, "summary": manifest.summary})
        return

    target = output
    if in_place:
        if source in (None, "-"):
            _fail("--in-place needs a file path source")
        target = Path(source)
    if target is not None:
        summary = driver.execute_manifest(manifest)
        _csv_warning(target, manifest)
        written = driver.save(target)
        ui.print_summary(summary, str(target))
        _emit({"applied": summary.applied, "errors": summary.errors, "saved": str(target), "files": [str(p) for p in written], "summary": manifest.summary})
        return

    _emit(_manifest_json(manifest))


@app.command()
def ask(
    args: Annotated[list[str], typer.Argument(help='[FILE|-] "QUESTION"  (FILE omitted with --live)')],
    live: Annotated[bool, typer.Option("--live", help="Ask about the running LibreOffice Calc document")] = False,
    port: PortOpt = None,
    sheet: SheetOpt = None,
    all_sheets: AllSheetsOpt = False,
    image: ImageOpt = None,
    backend: BackendOpt = None,
    model: ModelOpt = None,
    fast: FastOpt = False,
    api_key: ApiKeyOpt = None,
    context_tokens: ContextTokensOpt = None,
) -> None:
    """Ask a question about a workbook; prints the answer only, never modifies anything."""
    if live:
        source, query = (None, args[0]) if len(args) == 1 else (args[0], args[1])
    elif len(args) == 2:
        source, query = args
    else:
        _fail('Usage: vitreus ask <FILE|-> "<question>"')
    settings = _settings(backend, model, fast, api_key, context_tokens, port)
    _driver, _snapshot, _name, manifest, _agent = _plan(query, source, sheet, live, all_sheets, image, settings)
    typer.echo(manifest.summary or "(no answer)")
    if manifest.actions:
        ui.info(f"{len(manifest.actions)} action(s) were proposed; run `vitreus analyze` to review and apply them.")


@app.command()
def chat(
    source: Annotated[Optional[str], typer.Argument(help="Workbook path (omit with --live)")] = None,
    live: Annotated[bool, typer.Option("--live", help="Work on the running LibreOffice Calc document")] = False,
    save: Annotated[Optional[Path], typer.Option("--save", help="Default path for /save")] = None,
    port: PortOpt = None,
    sheet: SheetOpt = None,
    all_sheets: AllSheetsOpt = False,
    backend: BackendOpt = None,
    model: ModelOpt = None,
    fast: FastOpt = False,
    api_key: ApiKeyOpt = None,
    context_tokens: ContextTokensOpt = None,
) -> None:
    """Interactive multi-turn session with /preview, /apply, /save."""
    from interfaces.repl import run_chat

    settings = _settings(backend, model, fast, api_key, context_tokens, port)
    backend_obj, _ = _backend(settings)
    driver, snapshot, source_name, active = _open_source(source, sheet, live, settings)
    focus = None if all_sheets or active is None else [active]
    agent = SpreadsheetAgent(backend_obj, settings, snapshot, source_name=source_name, focus_sheets=focus)
    run_chat(agent, driver, save_path=save, live=live)


# ─── apply-manifest / batch ─────────────────────────────────────────────────


@app.command("apply-manifest")
def apply_manifest(
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Workbook (.xlsx/.csv)")],
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Manifest JSON produced by analyze")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Save the modified workbook here")] = None,
    sheet: SheetOpt = None,
) -> None:
    """Apply a saved manifest to a workbook and print {"applied", "errors"}."""
    driver = WorkbookDriver.from_path(source, sheet_name=sheet)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = validate_manifest(raw, driver.sheet_names)
    except json.JSONDecodeError as exc:
        _fail(f"Manifest is not valid JSON: {exc}")
    except ManifestValidationError as exc:
        _fail("Manifest is invalid:\n  " + "\n  ".join(exc.errors))
    _warn_risky(manifest)
    summary = driver.execute_manifest(manifest)
    payload: dict[str, Any] = {"applied": summary.applied, "errors": summary.errors}
    if output is not None:
        _csv_warning(output, manifest)
        written = driver.save(output)
        payload["saved"] = str(output)
        payload["files"] = [str(p) for p in written]
        ui.print_summary(summary, str(output))
    _emit(payload)


@app.command()
def batch(
    query: Annotated[str, typer.Argument(help="Instruction applied to every file")],
    files: Annotated[list[Path], typer.Argument(help="Workbooks to process")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-d", help="Where to write results (as .xlsx)")] = Path("vitreus-out"),
    sheet: SheetOpt = None,
    all_sheets: AllSheetsOpt = False,
    backend: BackendOpt = None,
    model: ModelOpt = None,
    fast: FastOpt = False,
    api_key: ApiKeyOpt = None,
    context_tokens: ContextTokensOpt = None,
) -> None:
    """Run one instruction over many workbooks; prints one JSON line per file.

    Usage: vitreus batch "INSTRUCTION" FILE [FILE ...]
    """
    if Path(query).is_file():
        _fail(
            f"First argument must be the instruction, but '{query}' is a file",
            hint='usage: vitreus batch "INSTRUCTION" FILE [FILE ...]',
        )
    settings = _settings(backend, model, fast, api_key, context_tokens)
    backend_obj, _ = _backend(settings)
    output_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for file in files:
        entry: dict[str, Any] = {"file": str(file)}
        try:
            driver = WorkbookDriver.from_path(file, sheet_name=sheet)
            snapshot = driver.snapshot()
            focus = None if all_sheets else [driver.active_sheet]
            agent = SpreadsheetAgent(backend_obj, settings, snapshot, source_name=file.name, focus_sheets=focus)
            with ui.status(f"{file.name}: reasoning…"):
                result = agent.run(query)
            _warn_risky(result.manifest, prefix=f"{file.name} ")
            summary = driver.execute_manifest(result.manifest)
            target = output_dir / f"{file.stem}.xlsx"
            driver.save(target)
            entry.update({"applied": summary.applied, "errors": summary.errors, "saved": str(target), "summary": result.manifest.summary})
        except Exception as exc:  # noqa: BLE001 - keep going, report per file
            failures += 1
            entry["error"] = str(exc).split("\n")[0]
        typer.echo(json.dumps(entry, default=str))
    if failures:
        raise typer.Exit(1)


# ─── calc ───────────────────────────────────────────────────────────────────


@calc_app.command("launch")
def calc_launch(
    file: Annotated[Optional[Path], typer.Argument(help="Workbook to open (optional)")] = None,
    port: Annotated[Optional[int], typer.Option("--port", help="UNO socket port")] = None,
    headless: Annotated[bool, typer.Option("--headless", help="No window (for automation)")] = False,
) -> None:
    """Start LibreOffice Calc with a UNO listener so --live commands can connect."""
    from core.uno_driver import launch_calc

    settings = load_settings(overrides={"calc_port": port} if port else {}, env=os.environ)
    if not (shutil.which("soffice") or shutil.which("libreoffice")):
        _fail("LibreOffice (soffice) not found on PATH", hint="install it, e.g. `sudo pacman -S libreoffice-fresh`")
    if file is not None and not file.is_file():
        _fail(f"File not found: {file}")
    proc = launch_calc(str(file.resolve()) if file else None, port=settings.calc_port, headless=headless)
    ui.info(f"LibreOffice starting (pid {proc.pid}); listening on port {settings.calc_port}. Use `vitreus calc status` to check.")
    _emit({"pid": proc.pid, "port": settings.calc_port, "file": str(file) if file else None, "headless": headless})


@calc_app.command("status")
def calc_status(port: Annotated[Optional[int], typer.Option("--port", help="UNO socket port")] = None) -> None:
    """Report whether a live Calc document is reachable."""
    settings = load_settings(overrides={"calc_port": port} if port else {}, env=os.environ)
    driver = _uno_driver(settings)
    available = driver.is_available()
    payload: dict[str, Any] = {"available": available, "port": settings.calc_port}
    if available:
        payload["document"] = driver.document_title()
        payload["sheets"] = driver.sheet_names()
        payload["uno_python"] = getattr(driver, "python", None)
    else:
        payload["hint"] = "start Calc with `vitreus calc launch [file]`; set VITREUS_UNO_PYTHON if no Python can import uno"
    getattr(driver, "close", lambda: None)()
    _emit(payload)


# ─── vision ─────────────────────────────────────────────────────────────────


@app.command()
def vision(
    image_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    purpose: Annotated[str, typer.Option("--purpose", "-p", help="receipt | chart | table")] = "receipt",
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Write the extracted table to this .xlsx/.csv")] = None,
    sheet_name: Annotated[Optional[str], typer.Option("--sheet-name", help="Override the sheet name")] = None,
    backend: BackendOpt = None,
    model: ModelOpt = None,
    fast: FastOpt = False,
    api_key: ApiKeyOpt = None,
) -> None:
    """Extract a table from a receipt, chart or photographed table with Gemma's vision."""
    settings = _settings(backend, model, fast, api_key)
    backend_obj, _ = _backend(settings)
    if isinstance(backend_obj, FallbackBackend):
        _emit(VisionInput.from_file(image_path, purpose=purpose).to_prompt_payload())
        return
    try:
        with ui.status(f"Reading image with {backend_obj.model}…"):
            result = extract_table(backend_obj, image_path, purpose=purpose)
    except (VisionError, BackendError) as exc:
        _fail(str(exc).split("\n")[0], hint=getattr(exc, "hint", ""))
    name = sheet_name or result["sheet_name"]
    payload: dict[str, Any] = {"sheet_name": name, "summary": result["summary"], "rows": result["rows"]}
    if output is not None:
        driver = WorkbookDriver.from_snapshot(WorkbookSnapshot(sheets={name: result["rows"]}))
        written = driver.save(output)
        payload["saved"] = str(output)
        payload["files"] = [str(p) for p in written]
        ui.info(f"Wrote {len(result['rows'])} rows to {output}")
    _emit(payload)


# ─── models / doctor / config ───────────────────────────────────────────────


@app.command()
def models(backend: BackendOpt = None, api_key: ApiKeyOpt = None, fast: FastOpt = False) -> None:
    """Show the Gemma 4 model policy and the models available on the selected backend."""
    settings = _settings(backend, None, fast, api_key)
    choice = GemmaModelChoice.default()
    payload: dict[str, Any] = {"policy": {"primary": choice.primary, "drafter": choice.drafter, "rationale": choice.rationale}}
    try:
        backend_obj, reason = make_backend(settings)
        payload.update({"backend": backend_obj.name, "model": backend_obj.model, "reason": reason})
        try:
            payload["available"] = backend_obj.list_models()
        except BackendError as exc:
            payload["available"] = []
            payload["error"] = str(exc).split("\n")[0]
    except BackendError as exc:
        payload.update({"backend": settings.backend, "error": str(exc).split("\n")[0], "hint": exc.hint})
    _emit(payload)


@app.command()
def doctor() -> None:
    """Check Ollama, API keys, LibreOffice/UNO and Python deps; prints a JSON report."""
    import importlib.metadata

    from core.uno_driver import find_uno_python

    settings = load_settings(env=os.environ)
    report: dict[str, Any] = {}
    reachable = ollama_reachable(settings.ollama_host)
    ollama: dict[str, Any] = {"host": settings.ollama_host, "reachable": reachable, "models": []}
    if reachable:
        try:
            from core.backends import OllamaBackend

            ollama["models"] = OllamaBackend(settings.ollama_host, settings.primary).list_models()
            ollama["primary_pulled"] = settings.primary in ollama["models"]
            ollama["drafter_pulled"] = settings.drafter in ollama["models"]
        except BackendError as exc:
            ollama["error"] = str(exc)
    else:
        ollama["hint"] = "install Ollama, run `ollama serve`, then `ollama pull gemma4:31b` (or gemma4:e4b for small GPUs)"
    report["ollama"] = ollama
    report["api_keys"] = {
        "gemini": bool(settings.gemini_api_key),
        "openrouter": bool(settings.openrouter_api_key),
        "openai": bool(settings.openai_api_key or settings.openai_base_url),
    }
    try:
        _backend_obj, reason = make_backend(settings, ollama_probe=lambda host: reachable)
        report["selected_backend"] = {"backend": _backend_obj.name, "model": _backend_obj.model, "reason": reason}
    except BackendError as exc:
        report["selected_backend"] = {"backend": settings.backend, "error": str(exc)}
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    report["libreoffice"] = {"soffice": soffice, "uno_python": find_uno_python(settings.uno_python), "calc_port": settings.calc_port}
    report["config_file"] = {"path": str(default_config_path()), "exists": default_config_path().is_file()}
    report["python"] = sys.version.split()[0]
    for dist in ("openpyxl", "httpx", "pydantic", "typer", "pillow"):
        try:
            report[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            report[dist] = None
    _emit(report)


@app.command()
def config(
    init: Annotated[bool, typer.Option("--init", help="Write a commented config template")] = False,
    show: Annotated[bool, typer.Option("--show", help="Print the effective settings (keys masked)")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing config with --init")] = False,
) -> None:
    """Create or inspect ~/.config/vitreus/config.toml."""
    path = default_config_path()
    if init:
        if path.exists() and not force:
            _fail(f"{path} already exists", hint="use --force to overwrite, or --show to view effective settings")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(config_template(), encoding="utf-8")
        ui.info(f"Wrote {path}")
        _emit({"written": str(path)})
        return
    settings = load_settings(env=os.environ)
    payload = {k: v for k, v in settings.__dict__.items()}
    for key in ("gemini_api_key", "openrouter_api_key", "openai_api_key"):
        if payload.get(key):
            payload[key] = "••••" + str(payload[key])[-4:]
    payload["config_file"] = str(path)
    payload["config_file_exists"] = path.is_file()
    _emit(payload)
    if not show:
        ui.info("Use `vitreus config --init` to create a config file.")


if __name__ == "__main__":
    app()
