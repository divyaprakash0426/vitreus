*This is a submission for the [Gemma 4 Challenge: Write About Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06)*

# What I Learned Building a Local-First Spreadsheet Agent with Gemma 4

I built a small project called **Vitreus** to answer a practical question:

> What does a useful local-first AI agent look like when the data is not a chat history, but a spreadsheet?

Spreadsheets are deceptively hard. They look simple because they are rows and columns, but real spreadsheet work mixes:

- business rules,
- messy headers,
- formulas,
- visual formatting,
- multiple sheets,
- hidden assumptions,
- and private data.

That made the project a good test case for Gemma 4. I did not want to use the model as a novelty wrapper. I wanted Gemma 4 to do the part that is genuinely hard: read tabular context, understand the user's intent, and produce a safe action plan.

This post is the technical write-up behind that build: how I chose the Gemma 4 model, how I wired local and API backends, and the pattern I recommend if you want to let an LLM work with sensitive documents.

---

## The Core Idea: Reasoning Is Not Execution

The most important design decision came before any code:

**Gemma 4 should reason about the spreadsheet, but it should not directly mutate the spreadsheet.**

Instead of giving the model a tool like "edit cell" and letting it operate freely, Vitreus asks Gemma 4 to return a JSON manifest:

```json
{
  "model": {
    "primary": "gemma4:31b",
    "drafter": "gemma4:4b",
    "rationale": "Why this model and these actions were selected."
  },
  "actions": [
    {
      "type": "highlight",
      "range": "Sheet1!A3:K3",
      "color": "#f97316",
      "reason": "Spent exceeds Budget."
    },
    {
      "type": "write_value",
      "cell": "Sheet1!K3",
      "value": "OVER BUDGET",
      "reason": "The row needs review."
    }
  ]
}
```

The application then applies only the actions it understands:

- `highlight`
- `write_value`
- `formula`

This separation makes the system easier to trust. The model can still be creative and semantic, but the executor stays deterministic and testable.

---

## Why Gemma 4 31B Dense Was the Right Default

The Gemma 4 family spans different hardware and throughput needs:

| Gemma 4 variant | Best fit | How I think about it |
| :-- | :-- | :-- |
| 2B / 4B small models | Edge, browser, mobile, fast drafts | Great for low-latency helpers and constrained devices |
| 31B Dense | Local/server reasoning | Best fit when the task needs stronger reasoning over larger context |
| 26B MoE | High-throughput reasoning | Attractive when many requests need efficient expert routing |

For Vitreus, I picked **Gemma 4 31B Dense** as the primary model.

Why? Because spreadsheet work is context-heavy.

A spreadsheet request like this:

```text
Highlight all rows where Spent exceeds Budget, and for each over-budget row
write OVER BUDGET in the Notes column.
```

requires the model to:

1. Find the relevant columns.
2. Compare values row by row.
3. Preserve the row identity.
4. Produce valid spreadsheet ranges.
5. Write a clear reason for each action.
6. Return strict JSON without extra prose.

That is not just classification. It is structured reasoning over tabular data.

The 4B model still has a useful role. I treat it as a **drafter**: good for previews, edge use, or lightweight suggestions. But for the final workbook plan, the 31B Dense model is the safer default.

The model policy in Vitreus is explicit:

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

That rationale is not just documentation. It is returned in the manifest so the user can see which model policy was used.

---

## Running Gemma 4 Locally with Ollama

The local path is the preferred Vitreus path because spreadsheets often contain sensitive data: salaries, invoices, forecasts, customer exports, sales reports, and internal review notes.

Install dependencies:

```bash
uv sync --extra integrations
```

Pull the local model:

```bash
ollama pull gemma4:31b
```

Run Vitreus with local Gemma 4:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Summarise department-level spending risks" \
  --backend ollama
```

Use the smaller drafter model when you want a lighter local run:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows that need review" \
  --backend ollama \
  --model gemma4:4b
```

The backend adapter is deliberately tiny:

```python
class OllamaBackend:
    def __init__(self, model: str = "gemma4:31b"):
        self.model = model

    def call(self, prompt: str) -> str:
        from ollama import chat
        response = chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        return response.message.content
```

This keeps the dependency boundary clean. The rest of the project does not need to know whether the model is local or remote.

---

## Running Gemma 4 with an API Key

Local inference is ideal for privacy, but it is not always practical. I was not always running in my GPU profile while testing, so I also added a Google AI Studio backend.

Set the key:

```bash
export GEMINI_API_KEY="your_key_here"
```

Run with the cloud backend:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight the top 3 performers by Score in green" \
  --backend google
```

Or pass the key inline:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Flag rows where Spent exceeds Budget" \
  --backend google \
  --api-key "$GEMINI_API_KEY"
```

The adapter:

```python
class GoogleAIBackend:
    def __init__(self, api_key: str, model: str = "gemma-4-31b-it"):
        self.api_key = api_key
        self.model = model

    def call(self, prompt: str) -> str:
        from google import genai
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(model=self.model, contents=prompt)
        return response.text
```

This gives users two deployment modes:

| Mode | Command | When to use |
| :-- | :-- | :-- |
| Local | `--backend ollama` | Sensitive data, local GPU/CPU available |
| API key | `--backend google` | No local model available, quick testing |

The prompt and manifest contract stay the same in both modes.

---

## The Prompt Contract

The prompt is intentionally strict. It tells Gemma 4 that it is a spreadsheet intelligence agent and that the output must be JSON only:

```text
You are Vitreus, a spreadsheet intelligence agent running gemma4:31b.
Analyze the spreadsheet data below and respond with ONLY a valid JSON manifest
(no markdown, no explanation).

Task: Highlight rows where Spent exceeds Budget.

Sheet data:
[
  {
    "Name": "Alan Turing",
    "Budget": 110000,
    "Spent": 135000,
    "Notes": ""
  }
]

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

The response is parsed as JSON:

```python
def parse_manifest(content: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else content
    return json.loads(candidate)
```

In a production system I would harden this further with schema validation, but even this first version shows the important pattern: the LLM output is data, not authority.

---

## CSV Taught Me a Product Lesson

The first version worked with CSV files. That was useful for tests, but then a practical issue surfaced:

**CSV cannot store colors.**

A manifest can say:

```json
{"type": "highlight", "range": "Sheet1!A3:K3", "color": "#f97316"}
```

But if the output is CSV, there is nowhere to put that color.

So Vitreus handles the limitation explicitly:

```text
CSV output:
  result.csv
  result_highlights.json

XLSX output:
  result.xlsx with values, formulas, and cell fills
```

That led to the one-shot output flow:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows where Spent exceeds Budget in orange, write OVER BUDGET in Notes" \
  --backend google \
  --output /tmp/vitreus_result.xlsx
```

No separate "generate manifest" and "apply manifest" commands required.

The command still uses the manifest internally; it just applies it immediately and writes the output workbook.

---

## XLSX Made It Feel Real

CSV is a good interchange format. XLSX is what spreadsheet users actually expect.

The current Vitreus snapshot layer can now load Excel workbooks:

```python
WorkbookSnapshot.from_xlsx("examples/test_workbook.xlsx", sheet_name="Expenses")
WorkbookSnapshot.from_xlsx("examples/test_workbook.xlsx", all_sheets=True)
WorkbookSnapshot.from_file("examples/test_workbook.xlsx", sheet_name="Sales")
```

And the CLI can round-trip XLSX:

```bash
uv run vitreus analyze examples/test_workbook.xlsx \
  "In the Expenses sheet, highlight rows where Annual_Actual exceeds Annual_Budget" \
  --backend google \
  --sheet Expenses \
  --output /tmp/vitreus_expenses_result.xlsx
```

The generated test workbook has three sheets:

```text
examples/test_workbook.xlsx
├── Sales
├── Expenses
└── HR_Reviews
```

This mattered because it moved the project from "LLM over CSV" toward a more realistic spreadsheet workflow.

---

## What Gemma 4 Is Good At in This Pattern

From this project, I found Gemma 4 most useful for:

### 1. Header-aware reasoning

The user does not have to say "compare column I and column J." They can say:

```text
Find rows where Spent exceeds Budget.
```

Gemma 4 maps that request to the right fields.

### 2. Spreadsheet reference generation

The output needs actual ranges:

```text
Sheet1!A3:K3
```

This is small but important. If the model cannot translate semantic findings back to spreadsheet coordinates, it cannot drive a workbook.

### 3. Explanations attached to actions

Every non-obvious action can include a `reason`:

```json
{
  "reason": "Spent (135000) exceeds Budget (110000)"
}
```

That makes the manifest useful for audit logs and review UIs.

### 4. Flexible user intent

The same pipeline can handle:

```text
Highlight the top 3 performers by Score in green.
```

or:

```text
Add a SUM formula below the Spent column.
```

or:

```text
In the Expenses sheet, highlight rows where Annual_Actual exceeds Annual_Budget.
```

The executor is narrow, but the language interface is flexible.

---

## Where I Would Use Each Gemma 4 Variant

If you are deciding which Gemma 4 model to use, here is the mental model I ended up with:

### Use 2B / 4B when latency and hardware matter most

Good for:

- browser or mobile helpers,
- preview suggestions,
- small table summaries,
- command suggestions,
- offline edge workflows.

In Vitreus, the 4B model is the drafter path.

### Use 31B Dense when reasoning quality matters most

Good for:

- long-context document analysis,
- spreadsheet reasoning,
- multi-step planning,
- structured JSON generation,
- local-first professional tools.

This is the default Vitreus model.

### Use 26B MoE when throughput matters

Good for:

- many independent requests,
- server workloads,
- high-volume classification/routing,
- batch analysis where expert routing can improve efficiency.

I did not make MoE the default because Vitreus is currently optimized around careful workbook reasoning, not high-throughput request serving. But it is an obvious future backend option.

---

## Design Checklist for LLMs Working on Private Files

If you are building something similar with Gemma 4, I recommend this checklist:

1. **Do not let the model directly mutate private files.**
2. **Make the model return structured data.**
3. **Keep action types small and explicit.**
4. **Require reasons for destructive or non-obvious actions.**
5. **Make local inference the default path when privacy matters.**
6. **Offer an API-key path for users without local hardware.**
7. **Test the executor without requiring the model.**
8. **Tell users when the output format cannot preserve an action.**
9. **Prefer reviewable manifests over invisible automation.**

The model should be powerful, but the boundary around it should be boring.

That is a compliment. Boring boundaries are what make AI tools safe enough to use.

---

## Try the Pattern Yourself

Clone and run:

```bash
git clone https://github.com/divyaprakash0426/vitreus.git
cd vitreus
uv sync --extra dev
uv run pytest -q
uv run vitreus models
```

Run without any model:

```bash
uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight rows that need review"
```

Run with Google AI Studio:

```bash
uv sync --extra integrations
export GEMINI_API_KEY="your_key_here"

uv run vitreus analyze examples/sample_workbook.csv \
  "Highlight all rows where Spent exceeds Budget and write OVER BUDGET in Notes" \
  --backend google
```

Run with local Ollama:

```bash
uv sync --extra integrations
ollama pull gemma4:31b

uv run vitreus analyze examples/sample_workbook.csv \
  "Summarise budget risks by department" \
  --backend ollama
```

Write a real XLSX file:

```bash
uv run vitreus analyze examples/test_workbook.xlsx \
  "In the Sales sheet, highlight reps whose Quota_Attainment is below 80 percent" \
  --backend google \
  --sheet Sales \
  --output /tmp/vitreus_sales_review.xlsx
```

---

## Final Thought

The most interesting thing about Gemma 4 for me is not just that it can run locally or reason over longer context. It is that those capabilities change the shape of applications developers can build.

With a strong local model, a spreadsheet assistant does not have to be a SaaS upload box. It can be:

- local-first,
- auditable,
- scriptable,
- privacy-aware,
- and still useful.

That is the direction I want AI tooling to move: powerful models at the center, but surrounded by software engineering boundaries that users can understand.

Vitreus is my first pass at that pattern for spreadsheets.

<!-- Cover image idea: "Gemma 4 as a reasoning layer between a spreadsheet and a JSON manifest" architecture diagram. -->
