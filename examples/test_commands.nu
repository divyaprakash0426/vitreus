# =============================================================================
# Vitreus — Test Commands (Nushell)
# =============================================================================
# Run from the repo root:  nu examples/test_commands.nu
# Prerequisites:
#   uv sync --extra dev               (always)
#   uv sync --extra integrations      (for --backend ollama / google)
#   ollama pull gemma4:31b            (for --backend ollama)
#   $env.GEMINI_API_KEY = "<key>"     (for --backend google)
# =============================================================================

let csv = "examples/sample_workbook.csv"

def sep [label: string] {
    print ""
    print $"─────────────────────────────────────────────────"
    print $"▶ ($label)"
    print $"─────────────────────────────────────────────────"
}


# ─── 1. MODELS ───────────────────────────────────────────────────────────────
sep "1. Show Gemma 4 model selection"
uv run vitreus models


# ─── 2. ANALYZE — fallback planner (no model required) ───────────────────────
sep "2a. Highlight rows with scores below 80 (needs review)"
uv run vitreus analyze $csv "Highlight rows that need review"

sep "2b. Highlight with explicit sheet name"
uv run vitreus analyze $csv "Highlight rows that need review" --sheet Sheet1

sep "2c. Parse manifest as structured Nu table"
uv run vitreus analyze $csv "Highlight rows that need review"
  | from json
  | get actions


# ─── 3. ANALYZE — local Ollama backend ───────────────────────────────────────
sep "3a. Ollama — summarise Q1 vs Q2 performance"
uv run vitreus analyze $csv "Summarise the Q1 vs Q2 performance trend for each person" --backend ollama

sep "3b. Ollama — flag over-budget rows"
uv run vitreus analyze $csv "Highlight all rows where Spent exceeds Budget" --backend ollama

sep "3c. Ollama — write review labels"
uv run vitreus analyze $csv "For rows with Score below 70, write Needs Improvement into the Notes cell" --backend ollama

sep "3d. Ollama — generate SUM formula"
uv run vitreus analyze $csv "Add a SUM formula below the Spent column to total all spending" --backend ollama

sep "3e. Ollama — use 4B drafter model"
uv run vitreus analyze $csv "Highlight rows that need review" --backend ollama --model gemma4:4b


# ─── 4. ANALYZE — Google AI Studio backend ───────────────────────────────────
sep "4a. Google — identify top performers"
uv run vitreus analyze $csv "Highlight the top 3 performers by Score in green" --backend google

sep "4b. Google — budget risk analysis"
uv run vitreus analyze $csv "Flag rows where Spent exceeds Budget by more than 10 percent with red highlight and write OVER BUDGET in Notes" --backend google

sep "4c. Google — inline API key"
# uv run vitreus analyze $csv "Highlight at-risk rows" --backend google --api-key YOUR_KEY_HERE
print "  (uncomment and set --api-key to test inline key)"


# ─── 5. APPLY-MANIFEST ───────────────────────────────────────────────────────
sep "5a. Analyze → save manifest → apply"
uv run vitreus analyze $csv "Highlight rows that need review" | save --force /tmp/vitreus_manifest.json
uv run vitreus apply-manifest $csv /tmp/vitreus_manifest.json | from json

sep "5b. Hand-written write_value manifest"
{
  actions: [
    {type: "write_value", cell: "Sheet1!K3", value: "REVIEWED"},
    {type: "write_value", cell: "Sheet1!K9", value: "FLAGGED"},
    {type: "formula",     cell: "Sheet1!J11", formula: "=SUM(J2:J10)", reason: "Total spending"}
  ]
} | to json | save --force /tmp/manual_manifest.json
uv run vitreus apply-manifest $csv /tmp/manual_manifest.json | from json

sep "5c. Highlight-only manifest"
{
  actions: [
    {type: "highlight", range: "Sheet1!A2:K3", color: "#f97316", reason: "Over budget"},
    {type: "highlight", range: "Sheet1!A9:K9", color: "#ef4444", reason: "Over budget and low score"}
  ]
} | to json | save --force /tmp/highlight_manifest.json
uv run vitreus apply-manifest $csv /tmp/highlight_manifest.json | from json


# ─── 6. VISION ───────────────────────────────────────────────────────────────
sep "6. Vision — image payload (replace path with a real image)"
# uv run vitreus vision path/to/chart.png --purpose chart | from json
# uv run vitreus vision path/to/receipt.jpg --purpose receipt | from json
print "  Usage: uv run vitreus vision path/to/chart.png --purpose chart | from json"
print "  Usage: uv run vitreus vision path/to/receipt.jpg --purpose receipt | from json"


# ─── 7. FULL PIPELINE — Ollama analyze → apply ───────────────────────────────
sep "7. Full pipeline: Ollama → apply"
try {
  uv run vitreus analyze $csv "Highlight rows where Score is below 70" --backend ollama
    | save --force /tmp/pipeline_manifest.json
} catch {
  print "  Ollama not running — using fallback manifest."
  {actions: [{type: "highlight", range: "Sheet1!A3:K3", color: "#ef4444", reason: "Score 65"}]}
    | to json | save --force /tmp/pipeline_manifest.json
}
uv run vitreus apply-manifest $csv /tmp/pipeline_manifest.json | from json


print ""
print "═══════════════════════════════════════════════════════════"
print "  All test commands completed."
print "  Tip: pipe analyze output through '| from json | get actions' for tables."
print "  Tip: set \$env.GEMINI_API_KEY = '<key>' before running section 4."
print "═══════════════════════════════════════════════════════════"
