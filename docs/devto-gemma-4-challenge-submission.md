*This is a submission for the [Gemma 4 Challenge: Build with Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06)*

# Vitreus: Local-First Agentic Spreadsheet Intelligence with Gemma 4

**TL;DR:** Vitreus lets you talk to spreadsheet data locally. It turns LibreOffice Calc ranges, CSV snapshots, charts, and receipt images into structured context for Gemma 4, then returns auditable JSON manifests that can highlight cells, write values, or add formulas without sending private workbook data to a third-party service.

## What I Built

Vitreus is a local-first AI agent for spreadsheet intelligence. The goal is to bridge the gap between dense workbook data and natural-language workflows without giving up privacy.

The project includes:

- A workbook snapshot layer that exports spreadsheet ranges to CSV or JSON context.
- A manifest executor for spreadsheet actions such as `highlight`, `write_value`, and `formula`.
- A Gemma 4 reasoning orchestrator that produces auditable action manifests.
- A multimodal image-prep pipeline for receipt and chart inputs.
- A Typer CLI for terminal-first workflows.
- Nushell and Arch Linux setup helpers for local development.

The current build supports CSV-backed local workflows out of the box and keeps LibreOffice UNO, Ollama, PydanticAI, and Google AI Studio behind adapter seams so they can be enabled without changing the core behavior.

## Demo

Local CLI smoke test:

```bash
uv sync --extra dev
uv run vitreus models
uv run vitreus analyze scores.csv "Highlight rows that need review"
```

Example input:

```csv
Name,Score
Ada,91
Linus,72
```

Example output:

```json
{
  "model": {
    "primary": "gemma4:31b",
    "drafter": "gemma4:4b",
    "rationale": "Gemma 4 31B Dense is the default because Vitreus needs local, long-context workbook reasoning and stronger multimodal planning; Gemma 4 4B remains useful as a low-latency drafter on edge hardware."
  },
  "actions": [
    {
      "type": "highlight",
      "range": "Sheet1!A3:B3",
      "color": "#f97316",
      "reason": "Score is below the review threshold of 80."
    }
  ]
}
```

That manifest can be reviewed, logged, and applied by the spreadsheet driver. The model never gets permission to mutate the workbook directly.

## Code

Repository: `https://github.com/divyaprakash0426/vitreus`

Core files:

- `core/driver.py` - spreadsheet snapshots, range export, and manifest execution.
- `core/reasoning.py` - Gemma 4 model selection, prompt payloads, manifest parsing, and planning.
- `core/vision.py` - image metadata and multimodal prompt preparation.
- `interfaces/cli.py` - command-line interface.
- `AGENTS.md` - system prompt, model policy, and manifest contract.

## How I Used Gemma 4

Vitreus is designed around **Gemma 4 31B Dense** as the primary model.

I chose the 31B Dense model because spreadsheet intelligence is a long-context reasoning problem. A useful spreadsheet agent needs to inspect many rows, understand headers, infer outliers, reason about formulas, and explain why a cell should be changed. Smaller edge models are attractive for latency, but the main planning step benefits from the stronger dense model.

Gemma 4 sits at the center of the workflow:

1. Vitreus extracts workbook ranges into compact JSON or CSV context.
2. The prompt includes the user request, model-selection rationale, and a strict response contract.
3. Gemma 4 returns a JSON action manifest instead of free-form instructions.
4. The driver applies only supported manifest actions after they can be inspected.
5. For chart or receipt workflows, Vitreus prepares image metadata and task-specific multimodal instructions for Gemma 4.

The project also makes room for **Gemma 4 4B** as a drafter model. That model is useful for fast previews, mobile/edge deployment, or lightweight command suggestions, while the 31B Dense model remains responsible for final workbook reasoning.

## Why Local-First Matters

Spreadsheets often contain payroll data, invoices, customer exports, forecasts, and internal operating metrics. Vitreus treats those files as private by default:

- Local CSV workflows run without network calls.
- Ollama is the preferred inference target.
- Cloud endpoints are optional and must be configured explicitly.
- The model returns a manifest; it does not directly control the spreadsheet.

That design makes the system safer to audit and easier to adapt for teams that cannot upload workbook data to external tools.

## Trade-offs and Limitations

The current implementation is intentionally adapter-first. CSV-backed workflows are working now, while full live LibreOffice Calc control depends on PyUNO and a running Calc socket. The deterministic fallback planner keeps tests and demos reproducible, but production usage should connect the reasoning seam to an actual Gemma 4 runtime through Ollama or a Google AI Studio compatible endpoint.

The upside is that each integration boundary is small and testable: workbook extraction, model planning, image preparation, and manifest execution can evolve independently.

## What Gemma 4 Unlocks

Gemma 4 turns Vitreus from a spreadsheet scripting tool into a reasoning layer. Instead of writing brittle macros for every workbook shape, users can ask for outcomes:

- "Highlight expense rows that need review."
- "Explain the spike in this chart."
- "Turn this receipt photo into spreadsheet-ready rows."
- "Suggest formulas for the missing forecast column."

The model does the semantic work, while Vitreus keeps execution structured, local, and auditable.

<!-- Add a cover image before publishing. A good visual: a LibreOffice Calc sheet with a translucent Gemma 4 manifest overlay. -->
