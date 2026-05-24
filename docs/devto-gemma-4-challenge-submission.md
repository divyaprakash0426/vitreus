*This is a submission for the [Gemma 4 Challenge: Build with Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06)*

# Vitreus: Local-First Spreadsheet Intelligence with Gemma 4

**TL;DR:** Vitreus is a spreadsheet agent that lets you ask natural-language questions of CSV and XLSX workbooks, then uses Gemma 4 to return an auditable JSON action manifest. The manifest can highlight rows, write values, and add formulas; Vitreus then applies those changes to a CSV snapshot or a real `.xlsx` file with colors and formulas preserved.

I built it because spreadsheets are where a lot of real business logic lives: budgets, project trackers, sales forecasts, invoices, HR reviews, and messy exported reports. But the moment you ask an AI assistant to "just update the sheet," you run into a trust problem: what exactly did it change, and why?

Vitreus answers that by splitting the job in two:

1. **Gemma 4 reasons about the workbook.**
2. **A deterministic driver applies only structured, reviewable actions.**

The model never mutates the workbook directly.

---

## What I Built

Vitreus is a local-first spreadsheet intelligence tool for developers, analysts, and teams who want AI help inside sensitive workbook workflows without giving the model unrestricted control.

The current project includes:

| Capability | Status | Why it matters |
| :-- | :-- | :-- |
| CSV workbook snapshots | Working | Fast, portable test format for spreadsheet data |
| XLSX input and output | Working | Preserves cell values, formulas, and highlight colors |
| One-shot `analyze --output` flow | Working | No separate "generate JSON" and "apply JSON" steps |
| JSON action manifests | Working | Every model action is inspectable before execution |
| Local Gemma 4 via Ollama | Supported | Private local inference path |
| Google AI Studio backend | Supported | API-key path for users without local GPU access |
| Deterministic fallback planner | Working | CI and demos can run without a model |
| Chart/receipt image payload prep | Working | Foundation for multimodal spreadsheet workflows |
| Bash and Nushell command references | Working | Easy manual testing on Linux/Nushell systems |

At a high level:

```text
CSV/XLSX workbook
    |
    v
WorkbookSnapshot
    |
    v
compact JSON sheet context
    |
    v
Gemma 4 planner
    |
    v
JSON manifest: highlight / write_value / formula
    |
    v
InMemoryCalcDriver
    |
    v
CSV + sidecar JSON, or XLSX with colors/formulas
```

This is not a chatbot bolted onto a spreadsheet. It is a small, testable agent pipeline where the model is responsible for reasoning and the application is responsible for safe execution.

---

## Demo

### Demo 1: Ask Gemma 4 to find budget problems

Input file: `examples/sample_workbook.csv`

It contains employee/project rows with columns like:

```csv
Name,Department,Q1_Target,Q1_Actual,Q2_Target,Q2_Actual,Score,Status,Budget,Spent,Notes
Ada Lovelace,Research,120000,128000,130000,135000,94,On Track,200000,184000,
Alan Turing,Security,90000,87000,95000,91000,72,Under Review,110000,135000,
...
```

Command:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight all rows where Spent exceeds Budget, and for each over-budget row write OVER BUDGET in the Notes column" \
  --backend google
```

Actual output from the live API-key run:

```json
{
  "model": {
    "primary": "gemma4:31b",
    "drafter": "gemma4:4b",
    "rationale": "Identified rows where Spent exceeds Budget: Alan Turing (Row 3) and Dennis Ritchie (Row 9). Applied highlights to these rows and updated the Notes column to 'OVER BUDGET'."
  },
  "actions": [
    {
      "type": "highlight",
      "range": "Sheet1!A3:K3",
      "color": "#f97316",
      "reason": "Spent (135000) exceeds Budget (110000)"
    },
    {
      "type": "write_value",
      "cell": "Sheet1!K3",
      "value": "OVER BUDGET",
      "reason": "Spent exceeds Budget"
    },
    {
      "type": "highlight",
      "range": "Sheet1!A9:K9",
      "color": "#f97316",
      "reason": "Spent (108000) exceeds Budget (90000)"
    },
    {
      "type": "write_value",
      "cell": "Sheet1!K9",
      "value": "OVER BUDGET",
      "reason": "Spent exceeds Budget"
    }
  ]
}
```

This is the core Vitreus pattern: Gemma 4 does the semantic reasoning, but the output is still machine-checkable.

### Demo 2: One command, real XLSX output

CSV is useful, but CSV cannot store background colors or Excel formulas. So Vitreus supports one-shot XLSX export:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows where Spent exceeds Budget in orange, write OVER BUDGET in the Notes column" \
  --backend google \
  --output /tmp/vitreus_result.xlsx
```

The result is a real Excel workbook. Open it in LibreOffice Calc or Excel and the highlighted rows are actually colored.

### Demo 3: XLSX in, XLSX out

I also created a larger workbook for testing:

```text
examples/test_workbook.xlsx
├── Sales        25 data rows, quota and commission formulas
├── Expenses     24 data rows, annual budget/actual formulas
└── HR_Reviews   18 data rows, rating/bonus formulas
```

Command:

```bash
uv run vitreus analyze examples/test_workbook.xlsx \
  "In the Expenses sheet, highlight rows where Annual_Actual exceeds Annual_Budget" \
  --backend google \
  --sheet Expenses \
  --output /tmp/vitreus_expenses_result.xlsx
```

Recent smoke-test result:

```json
{"applied": 1, "saved": "/tmp/vitreus_xlsx_test.xlsx", "errors": []}
```

### Recording the demo

I included repeatable command scripts for terminal recording:

```bash
bash examples/test_commands.sh
```

or, for Nushell:

```nu
nu examples/test_commands.nu
```

For a DEV post video, I would record these scenes with `asciinema`:

```bash
asciinema rec vitreus-demo.cast
bash examples/test_commands.sh
exit
asciinema play vitreus-demo.cast
asciinema upload vitreus-demo.cast
```

Suggested video flow:

1. Show `uv run vitreus models`.
2. Run the over-budget CSV example and show the JSON manifest.
3. Run `--output /tmp/vitreus_result.xlsx`.
4. Open the XLSX result in LibreOffice Calc and show the highlighted rows.
5. Run the multi-sheet XLSX example with `--sheet Expenses`.

---

## Code

Repository:

```text
https://github.com/divyaprakash0426/vitreus
```

Important files:

| File | Responsibility |
| :-- | :-- |
| `core/driver.py` | Workbook snapshots, CSV/XLSX loading, XLSX saving, manifest execution |
| `core/reasoning.py` | Gemma 4 model policy, Ollama backend, Google AI Studio backend, manifest parsing |
| `core/vision.py` | Image metadata and multimodal prompt payload preparation |
| `interfaces/cli.py` | Typer CLI commands: `models`, `analyze`, `apply-manifest`, `vision` |
| `examples/sample_workbook.csv` | Small CSV test dataset |
| `examples/test_workbook.xlsx` | Larger multi-sheet XLSX test workbook |
| `examples/test_commands.sh` | Bash demo/test command reference |
| `examples/test_commands.nu` | Nushell demo/test command reference |
| `tests/` | 37 automated tests covering backends, CLI, driver, output, and vision |

Try it:

```bash
git clone https://github.com/divyaprakash0426/vitreus.git
cd vitreus

uv sync --extra dev
uv run pytest -q
uv run vitreus models
```

Run with Google AI Studio:

```bash
uv sync --extra integrations
export GEMINI_API_KEY="your_key_here"

uv run vitreus analyze examples/sample_workbook.csv \
  "Flag rows where Spent exceeds Budget and write OVER BUDGET in Notes" \
  --backend google
```

Run locally with Ollama:

```bash
uv sync --extra integrations
ollama pull gemma4:31b

uv run vitreus analyze examples/sample_workbook.csv \
  "Summarise department-level spending risks" \
  --backend ollama
```

Use the lighter local model:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows that need review" \
  --backend ollama \
  --model gemma4:4b
```

---

## How I Used Gemma 4

Vitreus is designed around **Gemma 4 31B Dense** as the primary model.

Spreadsheet intelligence is a long-context reasoning task. A useful spreadsheet agent needs to:

1. Read many rows without losing the column semantics.
2. Understand user intent expressed in plain English.
3. Compare related fields like `Budget` and `Spent`.
4. Decide which cells or rows need attention.
5. Generate valid spreadsheet references like `Sheet1!A3:K3`.
6. Explain why each action is needed.
7. Return strict JSON instead of prose.

That is why I chose the 31B Dense model as the default planner. It is the best fit for "read this workbook, understand the pattern, and produce a reliable action plan."

The project still supports smaller Gemma 4 models as a deliberate secondary path:

| Model family | Role in Vitreus | Why |
| :-- | :-- | :-- |
| Gemma 4 31B Dense | Primary planner | Best fit for long-context workbook reasoning |
| Gemma 4 4B | Drafter / edge assistant | Lower latency for quick previews and constrained hardware |
| Gemma 4 26B MoE | Future throughput path | Useful when many independent workbook requests need efficient routing |

The model policy is encoded directly in the project:

```python
@dataclass(frozen=True)
class GemmaModelChoice:
    primary: str
    drafter: str
    rationale: str

    @classmethod
    def default(cls) -> "GemmaModelChoice":
        return cls(
            primary="gemma4:31b",
            drafter="gemma4:4b",
            rationale=(
                "Gemma 4 31B Dense is the default because Vitreus needs local, "
                "long-context workbook reasoning and stronger multimodal planning; "
                "Gemma 4 4B remains useful as a low-latency drafter on edge hardware."
            ),
        )
```

The prompt requires JSON only:

```text
You are Vitreus, a spreadsheet intelligence agent running gemma4:31b.
Analyze the spreadsheet data below and respond with ONLY a valid JSON manifest.

Task: Highlight rows where Spent exceeds Budget.

Required JSON response shape:
{
  "model": {"primary": "gemma4:31b", "drafter": "gemma4:4b", "rationale": "..."},
  "actions": [
    {
      "type": "highlight|write_value|formula",
      "range": "Sheet1!A1:B2",
      "cell": "Sheet1!C2",
      "value": "...",
      "formula": "=SUM(A1:A10)",
      "color": "#f97316",
      "reason": "why this action is needed"
    }
  ]
}
```

That contract is the heart of the project. Gemma 4 is not asked to "edit a spreadsheet." It is asked to produce a plan that Vitreus can inspect and execute.

---

## How It Works Internally

### 1. WorkbookSnapshot: turn sheets into model context

Vitreus reads CSV and XLSX files into a simple in-memory representation:

```python
@dataclass
class WorkbookSnapshot:
    sheets: dict[str, list[list[Any]]]
```

The snapshot can load:

```python
WorkbookSnapshot.from_csv("scores.csv")
WorkbookSnapshot.from_xlsx("workbook.xlsx", sheet_name="Expenses")
WorkbookSnapshot.from_file("workbook.xlsx", sheet_name="Sales")
```

Then it exports the requested range as compact JSON:

```json
[
  {"Name": "Alan Turing", "Budget": 110000, "Spent": 135000},
  {"Name": "Dennis Ritchie", "Budget": 90000, "Spent": 108000}
]
```

This gives Gemma 4 useful semantic structure: headers become keys, rows become records, and the model does not have to infer everything from raw cell coordinates.

### 2. Backends: local-first, cloud-optional

Vitreus supports three execution modes:

| Backend | Command | Use case |
| :-- | :-- | :-- |
| Fallback | default | CI, demos, no model required |
| Ollama | `--backend ollama` | Local Gemma 4 inference |
| Google AI Studio | `--backend google` | API-key run when local GPU is unavailable |

The backends are small adapter classes:

```python
class OllamaBackend:
    def call(self, prompt: str) -> str:
        from ollama import chat
        response = chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        return response.message.content

class GoogleAIBackend:
    def call(self, prompt: str) -> str:
        from google import genai
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(model=self.model, contents=prompt)
        return response.text
```

The lazy imports are intentional. The core package can be installed and tested without Ollama, Google GenAI, LibreOffice, or cloud credentials.

### 3. Manifest execution: structured actions only

The executor supports three action types:

```json
{"type": "highlight", "range": "Sheet1!A3:K3", "color": "#f97316", "reason": "..."}
{"type": "write_value", "cell": "Sheet1!K3", "value": "OVER BUDGET"}
{"type": "formula", "cell": "Sheet1!J11", "formula": "=SUM(J2:J10)", "reason": "..."}
```

Unsupported action types are rejected instead of silently ignored. This keeps the model inside a narrow, auditable capability boundary.

### 4. CSV vs XLSX: the boring detail that mattered

CSV cannot store background colors or formulas as spreadsheet formulas. Early testing made that painfully obvious: a manifest could say "highlight this row," but a CSV output could only store text.

So Vitreus handles both formats explicitly:

| Output | Behavior |
| :-- | :-- |
| `.csv` | Saves values and writes highlights to `<name>_highlights.json` |
| `.xlsx` | Saves values, formulas, and real cell background colors |

That means users get a clear warning for CSV:

```text
CSV format cannot store cell colors or formulas.
write_value changes are saved in result.csv
Highlight colors -> result_highlights.json
Tip: use --output result.xlsx to preserve everything in one file.
```

And they get real spreadsheet formatting when they choose XLSX.

---

## The Technical Problems That Shaped the Project

### Problem 1: "AI changed my spreadsheet" is not good enough

If a spreadsheet agent directly mutates a workbook, the user has to trust a black box.

The fix was the manifest contract. Every action contains:

- the action type,
- the exact cell or range,
- the value/formula/color,
- and the reason.

That makes it possible to log, review, diff, test, or reject model output before execution.

### Problem 2: Local-first should not mean "local-only"

My preferred path is Ollama with `gemma4:31b`, but not every developer has a GPU available. I hit this myself while testing away from my GPU profile.

So Vitreus supports both:

```bash
# Local
uv run vitreus analyze examples/sample_workbook.csv "..." --backend ollama

# API key
uv run vitreus analyze examples/sample_workbook.csv "..." --backend google
```

The model interface stays the same. Only the backend changes.

### Problem 3: Multi-sheet XLSX files are the real spreadsheet format

CSV was useful for early tests, but real workbooks have sheets, formulas, styles, and business structure.

The latest version added:

```python
WorkbookSnapshot.from_xlsx(path, sheet_name="Expenses")
WorkbookSnapshot.from_xlsx(path, all_sheets=True)
WorkbookSnapshot.from_file(path, sheet_name="Sales")
```

The CLI now accepts `.xlsx` as input:

```bash
uv run vitreus analyze examples/test_workbook.xlsx \
  "In the Sales sheet, highlight reps below quota" \
  --sheet Sales \
  --output /tmp/sales_review.xlsx
```

### Problem 4: Tests need to run without secret keys or local models

The project has 37 automated tests. They cover:

- backend adapter construction,
- CLI flags,
- missing API key behavior,
- manifest parsing,
- CSV save behavior,
- XLSX values,
- XLSX formulas,
- XLSX cell colors,
- XLSX input loading,
- and the multi-sheet test workbook shape.

The deterministic fallback planner is not a replacement for Gemma 4. It exists so the execution pipeline can be tested without depending on a network call or a local model.

---

## Why This Is a Good Gemma 4 Use Case

Gemma 4 is doing real work here. It is not decorative.

The model is responsible for the part that is hard to encode as rules:

- understanding workbook headers,
- mapping natural-language requests to spreadsheet operations,
- comparing values across columns,
- deciding which rows need attention,
- generating formulas,
- and explaining each action.

The surrounding application does the parts software should do:

- loading files,
- constraining the action schema,
- validating JSON,
- applying known operations,
- preserving output formats,
- and keeping the workflow auditable.

That division is what makes the project useful. Gemma 4 supplies reasoning; Vitreus supplies guardrails.

---

## Current Limitations

Vitreus is already useful for CSV/XLSX workflows, but there are areas I would keep improving:

| Area | Current state | Next step |
| :-- | :-- | :-- |
| LibreOffice live control | Adapter planned from blueprint | Wire PyUNO to a running Calc socket |
| Multimodal receipts/charts | Payload prep implemented | Feed images into Gemma 4 multimodal backend |
| Multi-sheet reasoning | Sheet-specific input works | Add whole-workbook summarization |
| Formula safety | Formula strings are written | Add formula linting and policy controls |
| Review UI | Terminal-first | Add a small manifest review screen |

The design intentionally keeps these as separable layers. The workbook reader, reasoning engine, and manifest executor can evolve independently.

---

## What I Learned

The biggest lesson was that a good spreadsheet agent is less about "letting AI use Excel" and more about designing a trustworthy boundary between reasoning and execution.

Gemma 4 is capable enough to understand messy tabular context and produce useful spreadsheet plans. But the application still needs to say:

- here is the allowed action vocabulary,
- here is the exact JSON shape,
- here is how output will be applied,
- and here is what happens when a format cannot represent an action.

That is the difference between an impressive demo and a tool I would trust with a real workbook.

---

## Acknowledgements

Built with:

- Gemma 4 31B Dense as the primary reasoning model
- Gemma 4 4B as the drafter/edge model path
- Ollama for local model execution
- Google AI Studio for API-key testing
- Typer for the CLI
- openpyxl for XLSX input/output
- pytest for the test suite
- LibreOffice Calc as the target spreadsheet environment

<!-- Cover image idea: a LibreOffice Calc sheet with two highlighted rows and a side panel showing the JSON manifest Gemma 4 produced. -->
