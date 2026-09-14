# Vitreus completion design

Date: 2026-09-14
Status: approved (autopilot; user instructed "complete the project")

## 1. Goal

Turn Vitreus from a prototype (single-shot prompt, CSV-only driver, stubbed
LibreOffice bridge) into a complete **local-first Gemma 4 spreadsheet agent
for spreadsheet work and automation**.

Primary product: a local agent running Gemma 4 through Ollama.
Secondary: hosted Gemma 4 (Google AI Studio, OpenRouter) or any
OpenAI-compatible endpoint, selectable but never required.

## 2. Current state (facts)

- `core/reasoning.py`: one prompt, whole sheet dumped as JSON records, no row
  numbers, no validation, no retries, model asked to echo model metadata.
- `core/driver.py`: `WorkbookSnapshot` (CSV/XLSX read), `InMemoryCalcDriver`
  (3 actions), `VitreusDriver` raises `NotImplementedError`.
- `save_xlsx` creates a new workbook and drops every other sheet and all
  existing formatting.
- Backends: Ollama SDK and google-genai SDK only; `--backend fallback` default.
- `vision.py` prepares metadata only; no multimodal call.
- `scripts/calc.nu` is a two-line wrapper; `gui_overlay.py` is a stub.
- 37 passing tests. Real Gemma 4 31B via Google AI Studio returns a correct
  manifest for the sample workbook (verified 2026-09-14, ~44 s).
- Environment: LibreOffice 26.2 with system PyUNO (Python 3.14); project venv
  is Python 3.13 so `import uno` is unavailable inside the venv. Ollama not
  installed here; `GEMINI_API_KEY` and `OPENROUTER_API_KEY` available. Both
  Google AI Studio and OpenRouter expose `gemma-4-31b-it` and
  `gemma-4-26b-a4b-it` (OpenRouter also has `:free` variants).

## 3. Decisions and assumptions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Default backend is `auto`: Ollama if reachable → Google if `GEMINI_API_KEY` → OpenRouter if `OPENROUTER_API_KEY` → OpenAI-compatible if `OPENAI_BASE_URL` → deterministic `fallback` with a stderr notice. | Local-first by default, cloud only when local is absent, never silently. |
| D2 | All backends speak REST through `httpx`; no vendor SDKs. | One code path to test with a mock transport; `uv sync` alone is enough for every backend. |
| D3 | Manifest v2 is a pydantic model. Vitreus stamps `model`; the LLM returns `summary` + `actions` only. | The model should not be asked to echo config. Validation errors become retry feedback. |
| D4 | Agent loop uses a prompt-level tool protocol (`{"tool": ..., "args": ...}`), not vendor function-calling. | Works identically on Ollama, Google, OpenRouter, llama.cpp. |
| D5 | `WorkbookDriver` (openpyxl-backed) replaces `InMemoryCalcDriver` for files; `InMemoryCalcDriver` stays as an alias. | XLSX round-trips must preserve other sheets and formatting. |
| D6 | Live Calc uses a JSON-over-stdio bridge subprocess run by a Python that can `import uno` (auto-discovered). | Venv Python ≠ system Python with PyUNO; the bridge isolates that. |
| D7 | `pydantic-ai`, `ollama`, `google-genai` extras are removed. `openpyxl` and `httpx` become core deps. | YAGNI; XLSX and HTTP are core features. |
| D8 | Model policy stays: primary `gemma4:31b`, drafter `gemma4:e4b` (Ollama tag), with per-backend model-ID mapping. `--fast` selects the drafter. | Matches AGENTS.md policy and real Ollama tags. |
| D9 | No GUI overlay. `gui_overlay.py` is deleted; live feedback goes to the terminal (rich) and to Calc itself. | Not in scope; removing dead code. |

## 4. Architecture

```
                 ┌───────────────┐
 CSV / XLSX ───▶ │ WorkbookDriver│──┐
 stdin (-)       └───────────────┘  │ snapshot()          ┌──────────────┐
                                    ├───────────────────▶ │ ContextBuilder│
 live Calc ────▶ ┌───────────────┐  │                     └──────┬───────┘
 (UNO bridge)    │  UnoDriver    │──┘                            │ compact context
                 └───────────────┘                               ▼
                        ▲                                 ┌──────────────┐   ┌───────────┐
                        │ execute_manifest()              │  Agent loop  │◀─▶│  Backend  │
                        │                                 │ (tools+retry)│   │ ollama /  │
                 ┌──────┴────────┐   validated Manifest   └──────┬───────┘   │ google /  │
                 │  Manifest v2  │◀───────────────────────────────┘           │ openrouter│
                 │  (pydantic)   │                                            │ openai /  │
                 └───────────────┘                                            │ fallback  │
                                                                              └───────────┘
```

### 4.1 Modules (`core/`)

| Module | Responsibility |
|--------|----------------|
| `config.py` | `Settings` from CLI > env > `~/.config/vitreus/config.toml` > defaults. Backend auto-detection. |
| `backends.py` | `Backend` protocol: `chat(messages, images=None) -> str`, `name`, `model`. Implementations: `OllamaBackend`, `GoogleAIBackend`, `OpenAICompatibleBackend` (used for OpenRouter and generic), `FallbackBackend`. `list_models()` where the API allows. |
| `manifest.py` | Pydantic `Manifest`, `Action` union, `validate_manifest(raw, snapshot) -> Manifest`, JSON-schema text for the prompt, `parse_json_object(text)`. |
| `context.py` | `WorkbookContext.build(snapshot, budget_tokens)`: per-sheet dims, column letters/names/inferred types/stats, numbered CSV rows or head/tail sample when over budget. |
| `agent.py` | `SpreadsheetAgent.run(query, snapshot, images) -> Manifest`. System prompt, tool protocol, max steps, validation-retry, conversation memory for chat mode. Tools: `list_sheets`, `describe_sheet`, `get_range`, `find`. |
| `driver.py` | `WorkbookSnapshot` (read model, range helpers), `WorkbookDriver` (openpyxl), `diff_snapshots`, `ManifestSummary`, A1 helpers. |
| `uno_driver.py` | `UnoDriver`: finds a UNO-capable Python, launches `uno_bridge.py`, JSON request/response; `launch_calc(file)`; `is_available()`. |
| `uno_bridge.py` | Standalone script (stdlib only). Commands: `ping`, `snapshot`, `execute`, `save`, `open`. Runs under system/LibreOffice Python. |
| `vision.py` | `VisionInput` (existing) + `encode_image()` and receipt/chart extraction prompt builders. |
| `fallback.py` | Deterministic rule-based planner (moved from reasoning.py, extended to compare two numeric columns named in the query). |
| `reasoning.py` | Thin compatibility layer: `VitreusReasoning`, `GemmaModelChoice` kept for existing callers; delegates to `agent.py`. |

### 4.2 Manifest v2

```json
{
  "summary": "Two rows exceed budget; highlighted and annotated.",
  "actions": [
    {"type": "highlight", "range": "Sheet1!A3:K3", "color": "#ef4444", "reason": "Spent 135000 > Budget 110000"},
    {"type": "write_value", "cell": "Sheet1!K3", "value": "OVER BUDGET"},
    {"type": "write_range", "range": "Sheet1!L1:L3", "values": [["Flag"], ["x"], ["y"]]},
    {"type": "formula", "cell": "Sheet1!J12", "formula": "=SUM(J2:J11)", "reason": "Total spent"},
    {"type": "fill_formula", "range": "Sheet1!L2:L11", "formula": "=J{row}-I{row}", "reason": "Variance per row"},
    {"type": "set_format", "range": "Sheet1!A1:K1", "bold": true, "background": "#e5e7eb", "number_format": null, "font_color": null, "italic": null},
    {"type": "set_column_width", "sheet": "Sheet1", "column": "A", "width": 22},
    {"type": "freeze_panes", "sheet": "Sheet1", "cell": "A2"},
    {"type": "add_note", "cell": "Sheet1!J3", "text": "Reviewed by Vitreus"},
    {"type": "sort_range", "range": "Sheet1!A1:K11", "by_column": "G", "descending": true, "has_header": true},
    {"type": "insert_rows", "sheet": "Sheet1", "at": 2, "count": 1},
    {"type": "delete_rows", "sheet": "Sheet1", "at": 5, "count": 2},
    {"type": "clear_range", "range": "Sheet1!K2:K11"},
    {"type": "add_sheet", "name": "Summary"},
    {"type": "add_chart", "sheet": "Sheet1", "chart_type": "bar", "data_range": "Sheet1!A1:B11", "title": "Q1 by person", "anchor": "M2"}
  ],
  "model": {"backend": "ollama", "primary": "gemma4:31b", "drafter": "gemma4:e4b", "rationale": "..."}
}
```

Rules: every `range`/`cell` must be `Sheet!A1[:B2]` with a known sheet
(`add_sheet` may create one earlier in the same manifest). Colors are
`#rrggbb`. Unknown action types fail validation; the agent gets the error
back and retries (max 2). A question with no edits returns `actions: []`
and the answer in `summary`.

### 4.3 Agent loop

1. System prompt: role, guardrails from AGENTS.md, manifest schema, tool
   protocol, "respond with exactly one JSON object".
2. User turn: task + `WorkbookContext` text (+ images).
3. Loop up to 8 steps: parse first JSON object in the reply.
   - `{"tool": name, "args": {...}}` → run tool on the snapshot, append
     `{"observation": ...}` as the next user turn.
   - Otherwise validate as a manifest. On failure append the validation
     errors and ask for a corrected manifest (max 2 retries).
4. Stamp `model` and return.

Chat mode keeps the message list across turns and refreshes the context
when the workbook changes after an apply.

### 4.4 Drivers

`WorkbookDriver`:
- `from_path(path, sheet=None)`: XLSX → `openpyxl.load_workbook`; CSV → new
  workbook with one sheet named after the file stem (or `--sheet`); `-` →
  CSV from stdin.
- `snapshot()` → `WorkbookSnapshot` (values; formulas kept as strings).
- `execute_manifest(manifest) -> ManifestSummary` implementing all actions.
- `save(path)`: `.xlsx` writes the workbook; `.csv` writes the active sheet
  and a `<stem>_highlights.json` sidecar when formats exist (existing
  behaviour preserved).

`UnoDriver`:
- `is_available()`, `connect(host, port)`, `snapshot()`,
  `execute_manifest()`, `save(path=None)`, `launch(file, port)`.
- Bridge protocol: newline-delimited JSON; one request → one response.
- Implements the same action set via UNO (`CellBackColor`, `setFormula`,
  `CharWeight`, `NumberFormat`, `Annotations`, `sort`, `insertByIndex`,
  `removeByIndex`, `Charts.addNewByName`, `Columns.Width`, `freezeAtPosition`).

`diff_snapshots(before, after)` → `[CellChange(sheet, cell, old, new)]` used
for `--preview` and the live-apply confirmation table.

### 4.5 CLI (`interfaces/cli.py`, `interfaces/repl.py`)

| Command | Purpose |
|---------|---------|
| `analyze <file\|-> "<query>"` | Plan; print manifest JSON (stdout). `--output` applies and saves. `--preview` prints a diff table (stderr). `--live` reads/applies in the running Calc doc (asks for confirmation unless `--yes`). `--image` attaches images. `--all-sheets`, `--sheet`, `--backend`, `--model`, `--fast`, `--context-tokens`. |
| `ask <file\|-> "<question>"` | Same pipeline, prints `summary` only, never applies. |
| `chat <file\|--live>` | REPL: multi-turn; `/apply`, `/preview`, `/save <path>`, `/reset`, `/quit`. |
| `apply-manifest <file> <manifest.json> --output` | Existing behaviour, now for all actions and XLSX round-trip. |
| `batch "<query>" <files...> --output-dir` | Same query over many files (automation). |
| `calc launch [file] [--port]` / `calc status` | Start LibreOffice with UNO listener; report connection/model info. |
| `vision <image> --purpose receipt\|chart\|table [--output]` | Real multimodal extraction into a table/workbook; without a backend prints the payload as today. |
| `models` | Policy + live model list from the selected backend. |
| `doctor` | Ollama reachability, pulled models, API keys present, LibreOffice/UNO python, openpyxl. |
| `config [--init] [--show]` | Write/print `~/.config/vitreus/config.toml`. |

Stdout stays machine-readable JSON (or plain answer text for `ask`); all
progress, warnings and tables go to stderr via `rich`.

### 4.6 Nushell (`scripts/calc.nu`)

```nu
ls | vitreus sheet "highlight files over 1 MB" -o files.xlsx   # Nu table → xlsx
open budget.csv | vitreus ask "which department is over budget?"
vitreus live "flag negative margins"                           # current Calc doc
```

Implemented as `def --wrapped` commands that `to csv` the pipeline input and
call `vitreus analyze - ...`.

### 4.7 Config

`~/.config/vitreus/config.toml`:

```toml
backend = "auto"            # auto | ollama | google | openrouter | openai | fallback
[models]
primary = "gemma4:31b"
drafter = "gemma4:e4b"
[ollama]
host = "http://localhost:11434"
num_ctx = 32768
[openai]
base_url = "http://localhost:1234/v1"   # LM Studio / llama.cpp / vLLM
model = "gemma-4-31b-it"
[agent]
context_tokens = 24000
max_steps = 8
[calc]
port = 2002
```

Env: `VITREUS_BACKEND`, `VITREUS_MODEL`, `OLLAMA_HOST`, `GEMINI_API_KEY`,
`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `VITREUS_UNO_PYTHON`.

Per-backend model mapping for the policy names:

| Policy | Ollama | Google AI Studio | OpenRouter |
|--------|--------|------------------|------------|
| primary | `gemma4:31b` | `gemma-4-31b-it` | `google/gemma-4-31b-it` |
| drafter | `gemma4:e4b` | `gemma-4-26b-a4b-it` | `google/gemma-4-26b-a4b-it` |

## 5. Error handling

- Backend unreachable → `BackendError` with an actionable hint (`ollama
  serve`, `ollama pull gemma4:31b`, set key). Exit code 2.
- Invalid model JSON after retries → exit code 3, raw reply saved to
  `~/.cache/vitreus/last_reply.txt` for inspection.
- Manifest actions referencing unknown sheets/ranges are rejected at
  validation; individual driver failures are reported in
  `ManifestSummary.errors` and never abort the remaining actions.
- Live mode never applies without a confirmation (or `--yes`); a diff is
  shown first. Openpyxl saves always go to `--output`, never over the input
  unless `--in-place` is passed.

## 6. Testing

- Unit tests with `httpx.MockTransport` for every backend (request shape,
  image encoding, num_ctx, error mapping).
- Manifest validation tests: each action type, bad ranges, unknown sheet,
  retry feedback text.
- Context builder: dims, types, stats, budget truncation, row numbering.
- Agent loop: fake backend scripted replies (tool call → manifest; invalid →
  corrected).
- `WorkbookDriver`: every action on CSV-origin and XLSX-origin workbooks;
  XLSX round-trip preserves other sheets/styles; CSV sidecar.
- `UnoDriver`: fake bridge script for protocol; real integration test marked
  `@pytest.mark.integration`, skipped unless `soffice` and a UNO Python exist
  (this machine has both, so it runs here).
- CLI: typer `CliRunner` for every command, stdin `-`, preview, batch.
- Live smoke: real Gemma 4 through Google AI Studio and OpenRouter on
  `examples/sample_workbook.csv` (manual, documented in `examples/`).

## 7. Out of scope

GUI overlay, speculative decoding with the drafter, Excel COM, Google
Sheets API, scheduled jobs (users can cron `vitreus batch`).
