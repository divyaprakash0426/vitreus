"""Interactive multi-turn session: plan, preview, apply, save."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.agent import AgentError, SpreadsheetAgent
from core.backends import BackendError
from core.driver import WorkbookDriver, WorkbookSnapshot, diff_snapshots
from core.manifest import Manifest

HELP = """Commands:
  <question or instruction>  ask Gemma to analyse or plan changes
  /preview                   show the cell diff the last manifest would produce
  /apply                     apply the last manifest to the workbook (or live Calc doc)
  /save [path]               save the workbook (xlsx/csv); live docs save in place
  /manifest                  print the last manifest as JSON
  /reset                     clear the conversation
  /help                      this message
  /quit                      exit"""


def _format_manifest(manifest: Manifest) -> str:
    lines = [manifest.summary or "(no summary)"]
    for index, action in enumerate(manifest.actions, start=1):
        data = action.model_dump(exclude_none=True, exclude_defaults=True)
        target = data.pop("range", None) or data.pop("cell", None) or data.pop("sheet", None) or data.pop("name", "")
        data.pop("type", None)
        reason = data.pop("reason", "")
        detail = ", ".join(f"{k}={v}" for k, v in data.items())
        suffix = f" — {reason}" if reason else ""
        lines.append(f"  {index}. {action.type} {target} {detail}{suffix}".rstrip())
    if manifest.actions:
        lines.append("Type /preview to see the diff, /apply to apply.")
    return "\n".join(lines)


def _preview(manifest: Manifest, snapshot: WorkbookSnapshot) -> str:
    scratch = WorkbookDriver.from_snapshot(snapshot)
    summary = scratch.execute_manifest(manifest)
    changes = diff_snapshots(snapshot, scratch.snapshot())
    lines = [f"Preview: {len(changes)} cell change(s), {summary.applied} action(s) ok, {len(summary.errors)} error(s)"]
    for change in changes[:60]:
        lines.append(f"  {change.sheet}!{change.cell}: {change.old!r} -> {change.new!r}")
    if len(changes) > 60:
        lines.append(f"  … +{len(changes) - 60} more")
    for ref, fmt in list(scratch.formats.items())[:20]:
        if fmt.background:
            lines.append(f"  {ref}: highlight {fmt.background}")
    lines.extend(f"  error: {err}" for err in summary.errors)
    return "\n".join(lines)


def run_chat(
    agent: SpreadsheetAgent,
    driver: Any,
    save_path: str | Path | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    live: bool = False,
) -> None:
    """Run the REPL until /quit or EOF. `driver` is a WorkbookDriver or UnoDriver."""
    last: Manifest | None = None
    output_fn(f"Vitreus chat — {agent.backend.name}/{agent.backend.model} on {agent.source_name}. Type /help for commands.")
    while True:
        try:
            line = input_fn("vitreus> ").strip()
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            return
        if not line:
            continue
        if line in {"/quit", "/exit", "/q"}:
            return
        if line == "/help":
            output_fn(HELP)
            continue
        if line == "/reset":
            agent.reset()
            last = None
            output_fn("Conversation cleared.")
            continue
        if line == "/manifest":
            output_fn(json.dumps(last.model_dump(mode="json", exclude_none=True), indent=2) if last else "Nothing planned yet.")
            continue
        if line == "/preview":
            if last is None:
                output_fn("Nothing to preview yet — ask for a change first.")
                continue
            output_fn(_preview(last, agent.snapshot))
            continue
        if line == "/apply":
            if last is None:
                output_fn("Nothing to apply yet — ask for a change first.")
                continue
            try:
                summary = driver.execute_manifest(last)
            except RuntimeError as exc:
                output_fn(f"Apply failed: {exc}")
                continue
            where = " to the live Calc document" if live else ""
            output_fn(f"Applied {summary.applied} action(s){where}." + (" Errors: " + "; ".join(summary.errors) if summary.errors else ""))
            agent.refresh(driver.snapshot())
            last = None
            continue
        if line.startswith("/save"):
            target = line[5:].strip() or (str(save_path) if save_path else None)
            try:
                if live:
                    saved = driver.save(target)
                    output_fn(f"Saved {saved or 'document'}.")
                elif target:
                    written = driver.save(target)
                    output_fn("Saved " + ", ".join(str(p) for p in written))
                else:
                    output_fn("Usage: /save <path.xlsx|path.csv>")
            except Exception as exc:  # noqa: BLE001 - surface any save failure to the user
                output_fn(f"Save failed: {exc}")
            continue
        if line.startswith("/"):
            output_fn(f"Unknown command {line.split()[0]}. Type /help.")
            continue
        try:
            result = agent.run(line)
        except (AgentError, BackendError) as exc:
            output_fn(f"Error: {exc}")
            continue
        last = result.manifest
        output_fn(_format_manifest(last))
