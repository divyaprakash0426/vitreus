# =============================================================================
# Vitreus - Test Commands (Nushell)
# =============================================================================
# Run from the repo root:  nu examples/test_commands.nu
# Prerequisites:
#   uv sync --extra dev               (always)
#   uv sync --extra integrations      (for --backend ollama / google)
#   ollama pull gemma4:31b            (for --backend ollama)
#   $env.GEMINI_API_KEY = "<key>"     (for --backend google)
# =============================================================================

let csv = "examples/sample_workbook.csv"
let xlsx = "examples/test_workbook.xlsx"

def sep [label: string] {
    print ""
    print "-------------------------------------------------"
    print $"> ($label)"
    print "-------------------------------------------------"
}

sep "1. Show Gemma 4 model selection"
uv run vitreus models

sep "2a. Fallback planner - highlight rows with scores below 80"
uv run vitreus analyze $csv "Highlight rows that need review"

sep "2b. Fallback planner - parse manifest as a Nu table"
uv run vitreus analyze $csv "Highlight rows that need review" | from json | get actions

sep "3a. Ollama - summarize Q1 vs Q2 performance"
uv run vitreus analyze $csv "Summarise the Q1 vs Q2 performance trend for each person" --backend ollama

sep "3b. Ollama - flag over-budget rows"
uv run vitreus analyze $csv "Highlight all rows where Spent exceeds Budget" --backend ollama

sep "3c. Ollama - use the 4B drafter model"
uv run vitreus analyze $csv "Highlight rows that need review" --backend ollama --model gemma4:4b

sep "4a. Google AI Studio - identify top performers"
uv run vitreus analyze $csv "Highlight the top 3 performers by Score in green" --backend google

sep "4b. Google AI Studio - budget risk analysis"
uv run vitreus analyze $csv "Flag rows where Spent exceeds Budget by more than 10 percent with red highlight and write OVER BUDGET in Notes" --backend google

sep "4c. Google AI Studio - inline API key example"
# uv run vitreus analyze $csv "Highlight at-risk rows" --backend google --api-key YOUR_KEY_HERE
print "  (uncomment and set --api-key to test inline key)"

sep "5a. Analyze -> save manifest -> apply"
uv run vitreus analyze $csv "Highlight rows that need review" | save --force /tmp/vitreus_manifest.json
uv run vitreus apply-manifest $csv /tmp/vitreus_manifest.json | from json

sep "5b. Hand-written manifest"
{
  actions: [
    {type: "write_value", cell: "Sheet1!K3", value: "REVIEWED"},
    {type: "write_value", cell: "Sheet1!K9", value: "FLAGGED"},
    {type: "formula", cell: "Sheet1!J11", formula: "=SUM(J2:J10)", reason: "Total spending"}
  ]
} | to json | save --force /tmp/manual_manifest.json
uv run vitreus apply-manifest $csv /tmp/manual_manifest.json | from json

sep "6a. One-shot output - CSV input to annotated XLSX"
uv run vitreus analyze $csv \
  "Highlight rows where Spent exceeds Budget in orange, write OVER BUDGET in Notes" \
  --backend google \
  --output /tmp/vitreus_result.xlsx
print "  Saved to /tmp/vitreus_result.xlsx - open in LibreOffice to see colors."

sep "6b. One-shot output - CSV input to CSV with highlights sidecar"
uv run vitreus analyze $csv "Highlight the top performer row in green" --output /tmp/vitreus_result.csv
print "  Written: /tmp/vitreus_result.csv + /tmp/vitreus_result_highlights.json"

sep "6c. One-shot output - XLSX input to XLSX output"
uv run vitreus analyze $xlsx \
  "In the Sales sheet, highlight reps with Quota_Attainment below 80 percent in red" \
  --backend google \
  --output /tmp/vitreus_sales_result.xlsx
print "  Saved to /tmp/vitreus_sales_result.xlsx"

sep "6d. One-shot output - XLSX specific sheet"
uv run vitreus analyze $xlsx \
  "Highlight rows where Annual_Actual exceeds Annual_Budget" \
  --backend google \
  --sheet Expenses \
  --output /tmp/vitreus_expenses_result.xlsx
print "  Saved to /tmp/vitreus_expenses_result.xlsx"

sep "7. Vision payload examples"
# uv run vitreus vision path/to/chart.png --purpose chart | from json
# uv run vitreus vision path/to/receipt.jpg --purpose receipt | from json
print "  uv run vitreus vision path/to/chart.png --purpose chart | from json"
print "  uv run vitreus vision path/to/receipt.jpg --purpose receipt | from json"

print ""
print "All test commands completed."
