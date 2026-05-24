#!/usr/bin/env bash
# =============================================================================
# Vitreus - Test Commands Reference
# =============================================================================
# Run from the repo root:  bash examples/test_commands.sh
# Prerequisites:
#   uv sync --extra dev               (always)
#   uv sync --extra integrations      (for --backend ollama / google)
#   ollama pull gemma4:31b            (for --backend ollama)
#   export GEMINI_API_KEY=<your key>  (for --backend google)
# =============================================================================

set -euo pipefail
CSV="examples/sample_workbook.csv"
XLSX="examples/test_workbook.xlsx"

sep() {
  echo
  echo "-------------------------------------------------"
  echo "> $*"
  echo "-------------------------------------------------"
}

sep "1. Show Gemma 4 model selection"
uv run vitreus models

sep "2a. Fallback planner - highlight rows with scores below 80"
uv run vitreus analyze "$CSV" "Highlight rows that need review"

sep "2b. Fallback planner - explicit sheet name"
uv run vitreus analyze "$CSV" "Highlight rows that need review" --sheet Sheet1

sep "3a. Ollama - summarize Q1 vs Q2 performance trends"
uv run vitreus analyze "$CSV" \
  "Summarise the Q1 vs Q2 performance trend for each person" \
  --backend ollama

sep "3b. Ollama - flag rows where Spent exceeds Budget"
uv run vitreus analyze "$CSV" \
  "Highlight all rows where the Spent column exceeds the Budget column" \
  --backend ollama

sep "3c. Ollama - use the lighter 4B drafter model"
uv run vitreus analyze "$CSV" \
  "Highlight rows that need review" \
  --backend ollama \
  --model gemma4:4b

sep "4a. Google AI Studio - identify top performers"
uv run vitreus analyze "$CSV" \
  "Highlight the top 3 performers by Score in green" \
  --backend google

sep "4b. Google AI Studio - budget risk analysis"
uv run vitreus analyze "$CSV" \
  "Flag any row where Spent is more than 10 percent over Budget with a red highlight and write OVER BUDGET in Notes" \
  --backend google

sep "4c. Google AI Studio - inline API key example"
# uv run vitreus analyze "$CSV" "Highlight at-risk rows" --backend google --api-key YOUR_KEY_HERE
echo "  (uncomment and set --api-key to test inline key)"

sep "5a. Analyze -> save manifest -> apply it"
uv run vitreus analyze "$CSV" "Highlight rows that need review" > /tmp/vitreus_manifest.json
uv run vitreus apply-manifest "$CSV" /tmp/vitreus_manifest.json

sep "5b. Apply a hand-written manifest"
cat > /tmp/manual_manifest.json <<'EOF'
{
  "actions": [
    {"type": "write_value", "cell": "Sheet1!K3", "value": "REVIEWED"},
    {"type": "write_value", "cell": "Sheet1!K9", "value": "FLAGGED"},
    {"type": "formula", "cell": "Sheet1!J11", "formula": "=SUM(J2:J10)", "reason": "Total spending across all rows"}
  ]
}
EOF
uv run vitreus apply-manifest "$CSV" /tmp/manual_manifest.json

sep "6a. One-shot output - CSV input to annotated XLSX"
uv run vitreus analyze "$CSV" \
  "Highlight rows where Spent exceeds Budget in orange, write OVER BUDGET in the Notes column" \
  --backend google \
  --output /tmp/vitreus_result.xlsx
echo "  Saved to /tmp/vitreus_result.xlsx - open in LibreOffice or Excel to see colors."

sep "6b. One-shot output - CSV input to CSV with highlights sidecar"
uv run vitreus analyze "$CSV" \
  "Highlight the top performer row in green" \
  --output /tmp/vitreus_result.csv 2>&1 || true
echo "  Written: /tmp/vitreus_result.csv + /tmp/vitreus_result_highlights.json"

sep "6c. One-shot output - XLSX input to XLSX output"
uv run vitreus analyze "$XLSX" \
  "In the Sales sheet, highlight any rep whose Quota_Attainment is below 80% in red" \
  --backend google \
  --output /tmp/vitreus_sales_result.xlsx
echo "  Saved to /tmp/vitreus_sales_result.xlsx"

sep "6d. One-shot output - XLSX specific sheet"
uv run vitreus analyze "$XLSX" \
  "In the Expenses sheet, highlight rows where Annual_Actual exceeds Annual_Budget" \
  --backend google \
  --sheet Expenses \
  --output /tmp/vitreus_expenses_result.xlsx
echo "  Saved to /tmp/vitreus_expenses_result.xlsx"

sep "7. Vision payload examples"
# uv run vitreus vision path/to/chart.png --purpose chart
# uv run vitreus vision path/to/receipt.jpg --purpose receipt
echo "  uv run vitreus vision path/to/chart.png --purpose chart"
echo "  uv run vitreus vision path/to/receipt.jpg --purpose receipt"

echo
echo "All test commands completed."
