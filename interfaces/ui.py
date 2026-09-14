"""Terminal presentation helpers. Everything here writes to stderr so stdout stays machine-readable."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from rich.console import Console
from rich.table import Table

from core.driver import CellChange, CellFormat, ManifestSummary
from core.manifest import Manifest

console = Console(stderr=True, highlight=False)


def info(message: str) -> None:
    console.print(f"[dim]{message}[/dim]")


def warn(message: str) -> None:
    console.print(f"[yellow]warning:[/yellow] {message}")


def error(message: str, hint: str = "") -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    if hint:
        console.print(f"  [dim]hint:[/dim] {hint}")


@contextmanager
def status(message: str) -> Iterator[None]:
    """Spinner on interactive terminals; silent otherwise (keeps piped stderr clean)."""
    ctx = console.status(f"[cyan]{message}[/cyan]", spinner="dots") if console.is_terminal else nullcontext()
    with ctx:
        yield


def _fmt(value: Any) -> str:
    if value is None:
        return "[dim]∅[/dim]"
    return str(value)


def print_diff(changes: list[CellChange], formats: dict[str, CellFormat] | None = None, limit: int = 60) -> None:
    formats = formats or {}
    if not changes and not formats:
        console.print("[dim]No cell changes.[/dim]")
        return
    if changes:
        table = Table(title=f"{len(changes)} cell change{'s' if len(changes) != 1 else ''}", title_justify="left", show_lines=False)
        table.add_column("Sheet", style="cyan")
        table.add_column("Cell", style="bold")
        table.add_column("Before")
        table.add_column("After", style="green")
        for change in changes[:limit]:
            table.add_row(change.sheet, change.cell, _fmt(change.old), _fmt(change.new))
        if len(changes) > limit:
            table.add_row("…", f"+{len(changes) - limit} more", "", "")
        console.print(table)
    if formats:
        coloured = [(ref, fmt.background) for ref, fmt in formats.items() if fmt.background]
        if coloured:
            preview = ", ".join(f"{ref} [on {bg}]  [/on {bg}]" for ref, bg in coloured[:12])
            more = f" … +{len(coloured) - 12} more" if len(coloured) > 12 else ""
            console.print(f"[dim]Highlights ({len(coloured)} cells):[/dim] {preview}{more}")


def print_manifest(manifest: Manifest) -> None:
    if manifest.summary:
        console.print(f"[bold]{manifest.summary}[/bold]")
    if not manifest.actions:
        console.print("[dim]No actions proposed.[/dim]")
        return
    table = Table(title=f"{len(manifest.actions)} proposed action{'s' if len(manifest.actions) != 1 else ''}", title_justify="left")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Type", style="cyan")
    table.add_column("Target", style="bold")
    table.add_column("Detail")
    table.add_column("Reason", style="dim")
    for index, action in enumerate(manifest.actions, start=1):
        data = action.model_dump(exclude_none=True, exclude_defaults=True)
        target = data.pop("range", None) or data.pop("cell", None) or data.pop("sheet", None) or data.pop("name", "")
        data.pop("type", None)
        reason = data.pop("reason", "")
        detail = ", ".join(f"{k}={v}" for k, v in data.items())
        table.add_row(str(index), action.type, str(target), detail[:80], reason[:80])
    console.print(table)


def print_summary(summary: ManifestSummary, target: str = "") -> None:
    where = f" to {target}" if target else ""
    console.print(f"[green]Applied {summary.applied} action{'s' if summary.applied != 1 else ''}{where}.[/green]")
    for err in summary.errors:
        console.print(f"  [red]•[/red] {err}")
