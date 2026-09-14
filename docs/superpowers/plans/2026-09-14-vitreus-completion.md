# Vitreus Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Vitreus as a local-first Gemma 4 spreadsheet agent: validated manifest v2, agentic planning loop with tools, REST backends (Ollama first, hosted Gemma optional), openpyxl and live-LibreOffice drivers, multimodal vision, and a full CLI/REPL/Nushell surface.

**Architecture:** `WorkbookDriver`/`UnoDriver` produce a `WorkbookSnapshot`; `ContextBuilder` compresses it into a token-budgeted prompt; `SpreadsheetAgent` runs a tool-augmented loop against a `Backend` and returns a pydantic `Manifest`; the same driver applies the manifest and reports a `ManifestSummary` plus a cell diff. CLI/REPL/Nushell are thin shells over this pipeline.

**Tech Stack:** Python ≥3.11, typer + rich (stderr UI), pydantic v2, httpx (REST for Ollama / Google AI Studio / OpenAI-compatible), openpyxl, Pillow, PyUNO via subprocess bridge, pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-vitreus-completion-design.md`

## Global Constraints

- Python `>=3.11`; run everything with `uv run ...` from the repo root.
- Core deps only: `pillow`, `pydantic`, `typer`, `httpx`, `openpyxl`. No vendor LLM SDKs. `dev` extra: `pytest`.
- stdout is machine-readable (JSON, or plain answer for `ask`); all UI/progress/warnings go to stderr.
- Default backend `auto` → order: ollama → google → openrouter → openai → fallback (with stderr notice).
- Model policy: primary `gemma4:31b`, drafter `gemma4:e4b`; per-backend IDs per spec §4.7 table.
- Never mutate the input file unless `--in-place`; live Calc never applies without confirmation or `--yes`.
- All ranges are `Sheet!A1` or `Sheet!A1:B2`; colours `#rrggbb`.
- Existing test names may be rewritten when the interface they test is replaced, but behaviour they assert (CSV sidecar, xlsx colours, fallback highlight range `Sheet1!A3:B3` for `Highlight rows that need review` on `Name,Score / Ada,91 / Linus,72`) must still hold.
- Commit after every task with the `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` trailer.

---

## File structure

| Path | Responsibility | Task |
|------|----------------|------|
| `pyproject.toml` | deps, script entry | 1 |
| `core/config.py` | `Settings`, `load_settings`, `detect_backend` | 1 |
| `core/manifest.py` | `Manifest`, `Action*`, `parse_json_object`, `validate_manifest`, `manifest_schema_text` | 2 |
| `core/driver.py` | `WorkbookSnapshot`, `WorkbookDriver`, `diff_snapshots`, `CellChange`, `ManifestSummary`, A1 helpers | 3 |
| `core/context.py` | `build_context(snapshot, budget_tokens)`, `describe_sheet`, `estimate_tokens` | 4 |
| `core/backends.py` | `Backend` protocol, `OllamaBackend`, `GoogleAIBackend`, `OpenAICompatibleBackend`, `FallbackBackend`, `BackendError`, `make_backend(settings)` | 5 |
| `core/fallback.py` | `plan_fallback(query, snapshot, sheet) -> dict` | 5 |
| `core/agent.py` | `SpreadsheetAgent`, `AgentResult`, tools | 6 |
| `core/reasoning.py` | compat: `GemmaModelChoice`, `VitreusReasoning` delegating to agent | 6 |
| `core/uno_bridge.py` | stdlib-only bridge script | 7 |
| `core/uno_driver.py` | `UnoDriver`, `find_uno_python`, `launch_calc` | 7 |
| `core/vision.py` | `VisionInput`, `encode_image`, `extraction_prompt`, `extract_table` | 8 |
| `interfaces/cli.py`, `interfaces/repl.py`, `interfaces/ui.py` | commands, chat loop, rich helpers | 9 |
| `scripts/calc.nu`, `scripts/setup_arch.sh`, `examples/*`, `README.md`, `AGENTS.md` | user surface & docs | 10 |

---

### Task 1: Dependencies and Settings

**Files:**
- Modify: `pyproject.toml`
- Create: `core/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Settings:
      backend: str = "auto"            # auto|ollama|google|openrouter|openai|fallback
      model: str | None = None         # explicit override
      fast: bool = False
      primary: str = "gemma4:31b"
      drafter: str = "gemma4:e4b"
      ollama_host: str = "http://localhost:11434"
      ollama_num_ctx: int = 32768
      gemini_api_key: str | None = None
      openrouter_api_key: str | None = None
      openai_api_key: str | None = None
      openai_base_url: str | None = None
      openai_model: str = "gemma-4-31b-it"
      context_tokens: int = 24000
      max_steps: int = 8
      calc_port: int = 2002
      uno_python: str | None = None
      def model_for(self, backend: str) -> str: ...
  def load_settings(overrides: dict | None = None, env: Mapping[str, str] | None = None, config_path: Path | None = None) -> Settings
  def detect_backend(settings: Settings, ollama_reachable: Callable[[str], bool]) -> tuple[str, str]  # (backend, reason)
  MODEL_IDS = {"ollama": {"primary": "gemma4:31b", "drafter": "gemma4:e4b"}, "google": {"primary": "gemma-4-31b-it", "drafter": "gemma-4-26b-a4b-it"}, "openrouter": {"primary": "google/gemma-4-31b-it", "drafter": "google/gemma-4-26b-a4b-it"}}
  def config_template() -> str
  def default_config_path() -> Path   # $XDG_CONFIG_HOME/vitreus/config.toml
  ```

- [ ] **Step 1: Write failing tests** (`tests/test_config.py`)

```python
from pathlib import Path
from core.config import Settings, load_settings, detect_backend, MODEL_IDS

def test_defaults_are_local_first():
    s = load_settings(env={})
    assert s.backend == "auto" and s.primary == "gemma4:31b" and s.drafter == "gemma4:e4b"

def test_env_overrides_toml_and_cli_overrides_env(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('backend = "google"\n[ollama]\nhost = "http://box:11434"\n', encoding="utf-8")
    s = load_settings(env={"VITREUS_BACKEND": "openrouter", "OPENROUTER_API_KEY": "k"}, config_path=cfg)
    assert s.backend == "openrouter" and s.ollama_host == "http://box:11434"
    s2 = load_settings(overrides={"backend": "ollama"}, env={"VITREUS_BACKEND": "openrouter"}, config_path=cfg)
    assert s2.backend == "ollama"

def test_detect_backend_prefers_ollama_when_reachable():
    s = load_settings(env={"GEMINI_API_KEY": "x"})
    assert detect_backend(s, ollama_reachable=lambda host: True)[0] == "ollama"

def test_detect_backend_falls_through_keys_then_fallback():
    assert detect_backend(load_settings(env={"GEMINI_API_KEY": "x"}), lambda h: False)[0] == "google"
    assert detect_backend(load_settings(env={"OPENROUTER_API_KEY": "x"}), lambda h: False)[0] == "openrouter"
    assert detect_backend(load_settings(env={"OPENAI_BASE_URL": "http://l:1234/v1"}), lambda h: False)[0] == "openai"
    assert detect_backend(load_settings(env={}), lambda h: False)[0] == "fallback"

def test_model_for_maps_policy_names_per_backend():
    s = load_settings(env={})
    assert s.model_for("google") == MODEL_IDS["google"]["primary"]
    assert load_settings(overrides={"fast": True}, env={}).model_for("openrouter") == "google/gemma-4-26b-a4b-it"
    assert load_settings(overrides={"model": "gemma4:26b"}, env={}).model_for("ollama") == "gemma4:26b"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_config.py -q` → FAIL (`ModuleNotFoundError: core.config`).
- [ ] **Step 3: Implement** `core/config.py` using `tomllib`; precedence overrides > env > toml > defaults. Env keys: `VITREUS_BACKEND`, `VITREUS_MODEL`, `VITREUS_FAST`, `OLLAMA_HOST`, `OLLAMA_NUM_CTX`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `VITREUS_CONTEXT_TOKENS`, `VITREUS_MAX_STEPS`, `VITREUS_CALC_PORT`, `VITREUS_UNO_PYTHON`. `model_for`: explicit `model` wins; else `MODEL_IDS[backend][drafter if fast else primary]`; `openai` backend uses `openai_model`.
- [ ] **Step 4: Update `pyproject.toml`**: dependencies `pillow>=11`, `pydantic>=2.10`, `typer>=0.15`, `httpx>=0.27`, `openpyxl>=3.1`; remove `integrations`; `dev=[pytest>=8.3]`; add `[tool.pytest.ini_options] markers = ["integration: requires LibreOffice"]`. Run `uv lock && uv sync --extra dev`.
- [ ] **Step 5: Run** `uv run pytest -q` → all pass. **Commit** `feat(config): add Settings with local-first backend detection`.

---

### Task 2: Manifest v2 schema and validation

**Files:**
- Create: `core/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Produces:
  ```python
  class ModelInfo(BaseModel): backend: str = "fallback"; primary: str; drafter: str; rationale: str = ""
  class Highlight(BaseModel): type: Literal["highlight"]; range: str; color: str = "#f97316"; reason: str = ""
  class WriteValue(BaseModel): type: Literal["write_value"]; cell: str; value: str | int | float | bool | None; reason: str = ""
  class WriteRange(BaseModel): type: Literal["write_range"]; range: str; values: list[list[Any]]; reason: str = ""
  class Formula(BaseModel): type: Literal["formula"]; cell: str; formula: str; reason: str = ""
  class FillFormula(BaseModel): type: Literal["fill_formula"]; range: str; formula: str; reason: str = ""
  class SetFormat(BaseModel): type: Literal["set_format"]; range: str; bold: bool|None; italic: bool|None; font_color: str|None; background: str|None; number_format: str|None; reason: str = ""
  class SetColumnWidth(BaseModel): type: Literal["set_column_width"]; sheet: str; column: str; width: float
  class FreezePanes(BaseModel): type: Literal["freeze_panes"]; sheet: str; cell: str
  class AddNote(BaseModel): type: Literal["add_note"]; cell: str; text: str
  class SortRange(BaseModel): type: Literal["sort_range"]; range: str; by_column: str; descending: bool = False; has_header: bool = True
  class InsertRows(BaseModel): type: Literal["insert_rows"]; sheet: str; at: int; count: int = 1
  class DeleteRows(BaseModel): type: Literal["delete_rows"]; sheet: str; at: int; count: int = 1
  class ClearRange(BaseModel): type: Literal["clear_range"]; range: str
  class AddSheet(BaseModel): type: Literal["add_sheet"]; name: str
  class AddChart(BaseModel): type: Literal["add_chart"]; sheet: str; chart_type: Literal["bar","line","pie","scatter"]; data_range: str; title: str = ""; anchor: str = "H2"
  Action = Annotated[Union[...all...], Field(discriminator="type")]
  class Manifest(BaseModel): summary: str = ""; actions: list[Action] = []; model: ModelInfo | None = None
  class ManifestValidationError(ValueError): errors: list[str]
  def parse_json_object(text: str) -> dict          # first balanced {...}, strips fences
  def validate_manifest(raw: dict, sheet_names: set[str]) -> Manifest   # range syntax, known sheet (add_sheet earlier counts), colour regex
  def manifest_schema_text() -> str                 # compact schema description for the system prompt
  ACTION_TYPES: tuple[str, ...]
  ```

- [ ] **Step 1: Failing tests** covering: parse fenced JSON and JSON with prose around it; every action type validates; `delete_sheet` rejected with message `Unsupported action type: delete_sheet`; range on unknown sheet rejected unless `add_sheet` precedes; bad colour `red` rejected; `summary`-only manifest valid with `actions=[]`; `model` optional; `manifest_schema_text()` lists all `ACTION_TYPES`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS. **Step 5: Commit** `feat(manifest): add pydantic manifest v2 with validation`.

---

### Task 3: WorkbookDriver (openpyxl) with the full action set

**Files:**
- Modify: `core/driver.py`
- Test: `tests/test_driver.py` (rewrite), `tests/test_output.py` (adjust imports only where needed)

**Interfaces:**
- Consumes: `Manifest`, `Action*` from Task 2.
- Produces:
  ```python
  @dataclass
  class WorkbookSnapshot: sheets: dict[str, list[list[Any]]]; source: str = ""
      from_csv / from_xlsx / from_file (existing) + from_csv_text(text, sheet_name)
      range_to_csv, range_to_json, to_csv, save_csv (existing)
      def dims(sheet) -> tuple[int, int]; def data_range(sheet) -> str  # "Sheet!A1:K11"
  @dataclass
  class CellChange: sheet: str; cell: str; old: Any; new: Any
  def diff_snapshots(before, after) -> list[CellChange]
  class WorkbookDriver:
      def __init__(self, workbook: openpyxl.Workbook, active_sheet: str, source: str = "")
      @classmethod from_path(path: str | Path, sheet_name: str | None = None, all_sheets=True) -> WorkbookDriver
      @classmethod from_csv_text(text: str, sheet_name="Sheet1")
      @classmethod from_snapshot(snapshot: WorkbookSnapshot)
      def snapshot(self) -> WorkbookSnapshot
      def execute_manifest(self, manifest: Manifest | dict) -> ManifestSummary
      def save(self, path: str | Path) -> list[Path]  # xlsx → [path]; csv → [path, sidecar?]
      @property formats -> dict[str, CellFormat]   # "Sheet!A1" → CellFormat(background=...)
  InMemoryCalcDriver = WorkbookDriver  (constructor also accepts a WorkbookSnapshot positional for compat)
  ```

- [ ] **Step 1: Failing tests**: highlight+write_value+formula on snapshot-built driver (`driver.snapshot().sheets["Sheet1"][1][2] == "pass"`, `driver.formats["Sheet1!B2"].background == "#16a34a"`); unsupported action reported without mutation; `write_range`, `fill_formula` with `{row}` and with relative shift (`=B2*2` on `C2:C4` → `=B4*2` at C4); `set_format` bold + number_format visible via openpyxl cell; `add_sheet` then write into it; `insert_rows`/`delete_rows` shift data; `sort_range` by column desc with header kept; `clear_range`; `add_note` → `ws["A2"].comment.text`; `set_column_width`; `freeze_panes`; `add_chart` → `len(ws._charts) == 1`; XLSX round-trip keeps a second sheet and pre-existing bold font; CSV save writes `_highlights.json` sidecar; `diff_snapshots` returns the changed cells only.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (CSV → `openpyxl.Workbook()` with coerced values; formats tracked from `PatternFill` on save and recorded in `self._formats` on highlight/set_format). **Step 4: Run whole suite** → PASS. **Step 5: Commit** `feat(driver): openpyxl-backed WorkbookDriver with 15 manifest actions and cell diff`.

---

### Task 4: Compact workbook context

**Files:**
- Create: `core/context.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `WorkbookSnapshot`.
- Produces:
  ```python
  def estimate_tokens(text: str) -> int                       # len//4 + 1
  def describe_sheet(snapshot, sheet) -> dict                 # {"rows","cols","data_range","columns":[{"letter","name","type","non_empty","min","max","mean","sample"}]}
  def sheet_rows_csv(snapshot, sheet, start_row=1, end_row=None) -> str   # header "row,A,B,..." then numbered rows
  def build_context(snapshot, budget_tokens=24000, sheets: list[str] | None = None) -> str
  ```
  Over budget → header + column summary + first 20 and last 5 rows + note "N rows omitted; use get_range tool".

- [ ] **Step 1: Failing tests**: describe types (`int`/`float`/`text`/`empty`/`mixed`) and stats; csv rows are numbered from 1 and columns lettered; small sheet is fully included; a 5,000-row sheet with budget 2,000 tokens includes the omission note and `row,5001`-free tail; multi-sheet context lists every sheet.
- [ ] **Step 2–5:** FAIL → implement → PASS → commit `feat(context): token-budgeted workbook context builder`.

---

### Task 5: REST backends and fallback planner

**Files:**
- Create: `core/backends.py`, `core/fallback.py`
- Rewrite: `tests/test_backends.py`; Create: `tests/test_fallback.py`

**Interfaces:**
- Consumes: `Settings`, `MODEL_IDS`.
- Produces:
  ```python
  Message = dict[str, str]   # {"role": "system"|"user"|"assistant", "content": str}
  class BackendError(RuntimeError): hint: str
  class Backend(Protocol):
      name: str; model: str
      def chat(self, messages: list[Message], images: list[bytes] | None = None) -> str
      def list_models(self) -> list[str]
  class OllamaBackend(host, model, num_ctx, client: httpx.Client | None = None)   # POST /api/chat stream=false, options.num_ctx; images base64 on last user msg; GET /api/tags
  class GoogleAIBackend(api_key, model, client=None)   # POST v1beta/models/{m}:generateContent?key=; systemInstruction; inline_data image parts
  class OpenAICompatibleBackend(base_url, api_key, model, name="openai", client=None, extra_headers=None)  # POST {base}/chat/completions; image_url data: URIs; GET /models
  class FallbackBackend(): name="fallback"; chat() raises BackendError (agent bypasses it)
  def ollama_reachable(host, timeout=1.0) -> bool
  def make_backend(settings: Settings) -> tuple[Backend, str]   # resolves auto, returns (backend, reason)
  ```
  `core/fallback.py`: `plan_fallback(query: str, snapshot, sheet: str) -> dict` — rules: "exceeds/over/greater than" between two named numeric columns → highlight rows + optional `write_value` when query says `write X in <Column>`; else legacy "<80 score/amount/total" review rule; else `actions: []` with summary explaining fallback.

- [ ] **Step 1: Failing tests** with `httpx.MockTransport`: Ollama request body has `model`, `stream False`, `options.num_ctx`, images list; Google body has `systemInstruction` and `inline_data.mime_type`; OpenAI body has `messages` with `image_url` part and Authorization header; HTTP 404 from Ollama → `BackendError` whose `hint` contains `ollama pull`; connection error → `BackendError` hint contains `ollama serve`; `make_backend` with backend `auto` and unreachable Ollama + `GEMINI_API_KEY` → `GoogleAIBackend`; `plan_fallback("Highlight rows where Spent exceeds Budget and write OVER BUDGET in Notes", ...)` on sample CSV → 2 highlights on rows 3 and 9 + 2 write_value at `K3`,`K9`; legacy review rule still yields `Sheet1!A3:B3`.
- [ ] **Step 2–5:** FAIL → implement → PASS → commit `feat(backends): httpx REST backends (ollama, google, openai-compatible) and rule-based fallback`.

---

### Task 6: Agent loop

**Files:**
- Create: `core/agent.py`
- Rewrite: `core/reasoning.py` (compat shim), `tests/test_reasoning.py`; Create: `tests/test_agent.py`

**Interfaces:**
- Consumes: `Backend`, `build_context`, `describe_sheet`, `sheet_rows_csv`, `validate_manifest`, `parse_json_object`, `plan_fallback`, `Settings`.
- Produces:
  ```python
  @dataclass
  class AgentResult: manifest: Manifest; steps: int; tool_calls: list[dict]; raw_replies: list[str]
  class SpreadsheetAgent:
      def __init__(self, backend: Backend, settings: Settings, snapshot: WorkbookSnapshot, source_name: str = "")
      def run(self, query: str, images: list[bytes] | None = None) -> AgentResult
      def refresh(self, snapshot: WorkbookSnapshot) -> None     # chat mode after apply
      def reset(self) -> None
      messages: list[Message]                                    # persisted across run() calls
  SYSTEM_PROMPT: str
  TOOLS = {"list_sheets", "describe_sheet", "get_range", "find"}
  ```
  `core/reasoning.py` keeps `GemmaModelChoice.default()` (primary `gemma4:31b`, drafter `gemma4:e4b`, rationale containing "31B Dense" and "long-context workbook reasoning") and `VitreusReasoning(backend=None).plan_action_sync(query, sheet_context_json, sheet_name)` returning a dict, implemented via `SpreadsheetAgent`/`plan_fallback`; `parse_manifest` → `parse_json_object`.

- [ ] **Step 1: Failing tests** with a `ScriptedBackend(replies: list[str])`: (a) direct manifest reply → validated, `model.backend == "scripted"`; (b) tool call `{"tool":"get_range","args":{"range":"Sheet1!A1:B2"}}` then manifest → `tool_calls` length 1 and second request contains `"observation"`; (c) invalid manifest then valid → `steps == 2` and the retry message contains `Unsupported action type`; (d) unknown tool → observation error, loop continues; (e) exceeding `max_steps` raises `AgentError`; (f) `FallbackBackend` → uses `plan_fallback` without calling chat; (g) chat mode: second `run()` sees prior assistant message. Reasoning compat tests (existing 4) still pass with `gemma4:e4b` drafter.
- [ ] **Step 2–5:** FAIL → implement → PASS → commit `feat(agent): tool-augmented planning loop with validation retries`.

---

### Task 7: LibreOffice UNO bridge and UnoDriver

**Files:**
- Create: `core/uno_bridge.py`, `core/uno_driver.py`
- Test: `tests/test_uno_driver.py`, `tests/integration/test_uno_live.py`

**Interfaces:**
- Consumes: `Manifest` JSON (dict form), `ManifestSummary`, `WorkbookSnapshot`.
- Produces:
  ```python
  def find_uno_python(explicit: str | None = None) -> str | None   # tries explicit, $VITREUS_UNO_PYTHON, /usr/bin/python3, python3, /usr/lib/libreoffice/program/python, /opt/libreoffice*/program/python
  def launch_calc(file: str | None, port: int = 2002, headless: bool = False) -> subprocess.Popen
  class UnoDriver:
      def __init__(self, host="localhost", port=2002, python: str | None = None, bridge_script: Path | None = None)
      def is_available(self) -> bool                     # python found and ping ok
      def snapshot(self) -> WorkbookSnapshot
      def execute_manifest(self, manifest) -> ManifestSummary
      def save(self, path: str | None = None) -> str     # store / storeToURL for xlsx/ods/csv
      def document_title(self) -> str
      def close(self) -> None
  ```
  Bridge protocol (stdin/stdout, one JSON per line): `{"cmd":"ping"}` → `{"ok":true,"doc":"title"}`; `{"cmd":"snapshot"}` → `{"ok":true,"sheets":{...}}`; `{"cmd":"execute","manifest":{...}}` → `{"ok":true,"applied":n,"errors":[...]}`; `{"cmd":"save","path":...}`; `{"cmd":"open","path":...}`. Errors: `{"ok":false,"error":"..."}`. The bridge connects with `uno.getComponentContext()` → `UnoUrlResolver` → `uno:socket,host=%s,port=%d;urp;StarOffice.ComponentContext`, uses `Desktop.CurrentComponent` (or opens `path`). Colour → `int(hex,16)`; bold → `CharWeight=150`; `number_format` → `NumberFormats.queryKey/addNew`; note → `Annotations.insertNew`; sort → `createSortDescriptor` with `SortFields`; rows → `Rows.insertByIndex/removeByIndex`; chart → `Charts.addNewByName` with `Rectangle` at anchor and `Diagram` type `com.sun.star.chart.BarDiagram|LineDiagram|PieDiagram|XYDiagram`; width → `Columns.getByIndex().Width` (1/100 mm ≈ width*256); freeze → `CurrentController.freezeAtPosition(col,row)`.

- [ ] **Step 1: Failing unit tests** using a fake bridge script written to `tmp_path` that echoes canned responses: `is_available()` true; `snapshot()` parses sheets; `execute_manifest()` returns `ManifestSummary(applied=2, errors=[])`; bridge error → `RuntimeError`; `find_uno_python()` returns `None` when no candidate imports `uno` (monkeypatch candidates).
- [ ] **Step 2: Integration test** (`@pytest.mark.integration`, skipped unless `shutil.which("soffice")` and `find_uno_python()`): launch `soffice --headless --norestore --accept=socket,host=localhost,port=2199;urp;` with a copy of `examples/test_workbook.xlsx`, wait for ping, snapshot has 3 sheets, execute highlight+write_value+formula+add_note, save to `tmp/out.xlsx`, reload with openpyxl and assert value + fill colour; terminate soffice.
- [ ] **Step 3–5:** implement → `uv run pytest tests/test_uno_driver.py tests/integration -q -m "integration or not integration"` PASS → commit `feat(uno): LibreOffice Calc live driver via PyUNO bridge subprocess`.

---

### Task 8: Multimodal vision

**Files:**
- Modify: `core/vision.py`
- Test: `tests/test_vision.py`

**Interfaces:**
- Produces:
  ```python
  def encode_image(path, max_side=1600) -> tuple[bytes, str]     # (jpeg/png bytes, mime)
  def extraction_prompt(purpose: str) -> str                      # receipt|chart|table
  def extract_table(backend: Backend, image_path, purpose="receipt") -> dict   # {"summary": str, "sheet_name": str, "rows": [[...]]}
  ```
  Model must reply `{"sheet_name": "...", "rows": [[header...], [...]], "summary": "..."}`; parsed with `parse_json_object`.

- [ ] **Step 1: Failing tests**: `encode_image` downsizes a 4000px image to ≤1600; `extract_table` with `ScriptedBackend` receives one image and returns rows; existing metadata test remains.
- [ ] **Step 2–5:** → commit `feat(vision): multimodal receipt/chart/table extraction`.

---

### Task 9: CLI, REPL and UI helpers

**Files:**
- Rewrite: `interfaces/cli.py`; Create: `interfaces/repl.py`, `interfaces/ui.py`
- Rewrite/extend: `tests/test_cli.py`, `tests/test_output.py`; Create: `tests/test_repl.py`

**Interfaces:**
- Consumes: everything above.
- Produces (`interfaces/ui.py`): `console = rich.console.Console(stderr=True)`, `print_diff(changes: list[CellChange])`, `print_summary(summary: ManifestSummary)`, `status(msg)` context manager (spinner when TTY).
- Commands per spec §4.5. Shared helper `_open_source(path_or_dash, sheet, live, settings) -> tuple[Driver, WorkbookSnapshot, str]`. `analyze` flow: build agent → run → if `--preview` or `--live` compute diff on a `WorkbookDriver.from_snapshot` copy and print → apply per target → print JSON `{"applied","errors","saved","summary"}` on stdout (manifest JSON when no output/live).
- REPL (`interfaces/repl.py`): `run_chat(agent, driver, save_path)`; loop reads lines; `/apply` executes last manifest and refreshes agent; `/preview` prints diff; `/save <path>`; `/reset`; `/quit`. Testable via injected `input_fn`/`output_fn`.

- [ ] **Step 1: Failing tests**: `analyze` fallback prints manifest with `Sheet1!A3:B3`; `analyze -` reads CSV from stdin; `analyze --output x.xlsx` saves colours (existing test_output assertions); `--preview` prints a diff table on stderr and does not write; `ask` prints only the summary; `apply-manifest` legacy behaviour; `batch` writes one output per input in `--output-dir`; `models` shows policy and (mocked) backend list; `doctor` exit 0 with JSON report; `config --init` writes template; `vision --purpose receipt --output out.xlsx` with mocked backend writes rows; `calc status` reports unavailable cleanly when no bridge; REPL scripted session applies and saves.
- [ ] **Step 2–5:** → commit `feat(cli): analyze/ask/chat/batch/calc/doctor/config commands with preview and live mode`.

---

### Task 10: Scripts, examples, docs

**Files:**
- Rewrite: `scripts/calc.nu`, `scripts/setup_arch.sh`, `examples/test_commands.sh`, `examples/test_commands.nu`, `README.md`, `AGENTS.md`
- Delete: `interfaces/gui_overlay.py`
- Create: `examples/manifests/over_budget.json`

- [ ] `calc.nu`: `export def --wrapped "vitreus sheet" [query: string, ...rest]` piping `$in | to csv` to `^uv run vitreus analyze - $query ...rest`; `vitreus ask`, `vitreus live`, `vitreus table` (Nu table → xlsx via `analyze - "" --output`). Verify with `nu -c 'use scripts/calc.nu *; [[a b]; [1 2]] | vitreus sheet "highlight b" | from json'`.
- [ ] README: local-first quick start (Ollama), then hosted options (Google/OpenRouter/OpenAI-compatible), manifest v2 table, CLI reference, live Calc, Nushell, automation (`batch`, cron), architecture diagram, doctor.
- [ ] AGENTS.md: manifest v2 contract, tool protocol, drafter `gemma4:e4b`.
- [ ] Commit `docs: complete README, agent guide, Nushell integration and examples`.

---

### Task 11: Verification

- [ ] `uv run pytest -q` (unit) and `uv run pytest -q -m integration` (LibreOffice) both green.
- [ ] Real smoke: `uv run vitreus analyze examples/sample_workbook.csv "Highlight rows where Spent exceeds Budget in red and write OVER BUDGET in Notes; add a Variance column = Spent - Budget" --backend google --output /tmp/v.xlsx --preview` and the same with `--backend openrouter`; inspect with openpyxl.
- [ ] Real live: `uv run vitreus calc launch examples/test_workbook.xlsx` then `uv run vitreus analyze --live "highlight Expenses rows over budget" --backend google --yes`.
- [ ] `uv run vitreus doctor`, `uv run vitreus models --backend google`.
- [ ] Dispatch code-review agent on the branch diff; fix findings; final commit.

## Self-review

- Spec coverage: §4.1 modules → Tasks 1–8; §4.2 → Task 2/3/7; §4.3 → Task 6; §4.4 → Tasks 3/7; §4.5 → Task 9; §4.6 → Task 10; §4.7 → Task 1; §5 error handling → Tasks 5/6/9; §6 testing → each task + Task 11. D9 (delete overlay) → Task 10.
- Type consistency: `ManifestSummary(applied, errors)` reused unchanged; `WorkbookSnapshot.sheets` shape unchanged; `Backend.chat(messages, images)` used by agent and vision; `Settings.model_for` used by `make_backend`.
