# Vitreus

<p align="center">
  <img src="docs/assets/cover.png" alt="Vitreus cover image" width="720">
</p>

**Vitreus is a local-first spreadsheet intelligence agent powered by Gemma 4.** It reads CSV or XLSX workbooks, turns the sheet into compact structured context, asks Gemma 4 to plan changes, and returns an auditable JSON manifest before applying anything to a workbook.

The model does the reasoning. Vitreus does the execution.

```text
CSV/XLSX workbook
    -> WorkbookSnapshot
    -> Gemma 4 prompt context
    -> JSON manifest
    -> deterministic CSV/XLSX writer
```

## Why Vitreus?

Spreadsheets often contain budgets, HR reviews, project trackers, invoices, and exported business reports. Letting an AI assistant directly mutate those files is risky, so Vitreus uses a safer two-step design:

1. **Gemma 4 reasons over the workbook** and emits a structured action manifest.
2. **Vitreus applies only supported actions** such as `highlight`, `write_value`, and `formula`.

That makes every change inspectable, reproducible, and easier to trust.

## Features

| Capability | Status |
| :-- | :-- |
| CSV input | Supported |
| XLSX input | Supported |
| XLSX output with highlight colors and formulas | Supported |
| CSV output with highlight sidecar JSON | Supported |
| Local Gemma 4 via Ollama | Supported |
| Google AI Studio API backend | Supported |
| Deterministic fallback mode | Supported |
| Image payload prep for charts/receipts | Supported |
| Bash and Nushell command references | Included |

## Model policy

Vitreus defaults to **Gemma 4 31B Dense** because workbook reasoning benefits from stronger long-context understanding over tabular data. The lighter **Gemma 4 4B** model is still useful as a drafter or edge-device option.

```bash
uv run vitreus models
```

## Install

```bash
uv sync --extra dev
uv run pytest
```

For model integrations:

```bash
uv sync --extra integrations
```

## Quick demo: Google AI Studio backend

Use this if you already have a `GEMINI_API_KEY` in your environment.

```bash
export GEMINI_API_KEY=your_key_here
```

Inspect the included XLSX workbook:

```bash
uv run vitreus analyze examples/test_workbook.xlsx \
  "In the Expenses sheet, highlight rows where Annual_Actual exceeds Annual_Budget" \
  --backend google \
  --sheet Expenses
```

Generate a real modified workbook:

```bash
uv run vitreus analyze examples/test_workbook.xlsx \
  "In the Expenses sheet, highlight rows where Annual_Actual exceeds Annual_Budget in orange and write OVER BUDGET in the Notes column" \
  --backend google \
  --sheet Expenses \
  --output /tmp/vitreus-demo-output.xlsx
```

Open the result:

```bash
libreoffice --calc /tmp/vitreus-demo-output.xlsx
```

## Local Gemma 4 with Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:31b
uv sync --extra integrations

uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows where Spent exceeds Budget" \
  --backend ollama
```

Use the lighter model when needed:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows that need review" \
  --backend ollama \
  --model gemma4:4b
```

## Fallback mode

Fallback mode uses a deterministic built-in planner, so it works without an API key, GPU, or Ollama installation.

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows that need review"
```

## CSV vs XLSX output

CSV is portable, but it cannot store cell colors or formulas as spreadsheet formatting. Vitreus handles that explicitly:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows where Spent exceeds Budget and write OVER BUDGET in Notes" \
  --output /tmp/vitreus-result.csv
```

This writes:

```text
/tmp/vitreus-result.csv
/tmp/vitreus-result_highlights.json
```

For colors and formulas in one file, write XLSX:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows where Spent exceeds Budget and write OVER BUDGET in Notes" \
  --backend google \
  --output /tmp/vitreus-result.xlsx
```

## Applying a saved manifest

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows that need review" \
  > /tmp/manifest.json

uv run vitreus apply-manifest examples/sample_workbook.csv \
  /tmp/manifest.json \
  --output /tmp/reviewed.xlsx
```

## Vision payloads

Vitreus includes image metadata preparation for future multimodal spreadsheet workflows such as receipt review and chart interpretation.

```bash
uv run vitreus vision chart.png --purpose chart
uv run vitreus vision receipt.jpg --purpose receipt
```

## Example files

| File | Purpose |
| :-- | :-- |
| `examples/sample_workbook.csv` | Small CSV workbook for quick testing |
| `examples/test_workbook.xlsx` | Larger workbook with `Sales`, `Expenses`, and `HR_Reviews` sheets |
| `examples/test_commands.sh` | Bash command reference |
| `examples/test_commands.nu` | Nushell command reference |
| `docs/devto-gemma-4-challenge-submission.md` | Build with Gemma 4 DEV submission |
| `docs/devto-gemma-4-write-about-submission.md` | Write About Gemma 4 DEV submission |

## Development

```bash
uv sync --extra dev
uv run pytest -q
```

The core test suite does not require LibreOffice, Ollama, or cloud credentials. Optional integrations are loaded only when their backend paths are invoked.
