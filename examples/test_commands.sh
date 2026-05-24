#!/usr/bin/env bash
# =============================================================================
# Vitreus — Test Commands Reference
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

sep() { echo; echo "─────────────────────────────────────────────────"; echo "▶ $*"; echo "─────────────────────────────────────────────────"; }


# ─── 1. MODELS ───────────────────────────────────────────────────────────────
sep "1. Show Gemma 4 model selection"
uv run vitreus models


# ─── 2. ANALYZE — fallback planner (no model required) ───────────────────────
sep "2a. Highlight rows with scores below 80 (needs review)"
uv run vitreus analyze "$CSV" "Highlight rows that need review"

sep "2b. Highlight rows that are under review or at risk"
uv run vitreus analyze "$CSV" "Highlight rows with Status Under Review or At Risk"

sep "2c. Highlight rows where spending exceeds budget (over budget)"
uv run vitreus analyze "$CSV" "Highlight rows that need review" --sheet Sheet1


# ─── 3. ANALYZE — local Ollama backend (requires: ollama pull gemma4:31b) ────
sep "3a. Ollama — summarise Q1 vs Q2 performance trends"
uv run vitreus analyze "$CSV" \
  "Summarise the Q1 vs Q2 performance trend for each person" \
  --backend ollama

sep "3b. Ollama — flag rows where Spent exceeds Budget"
uv run vitreus analyze "$CSV" \
  "Highlight all rows where the Spent column exceeds the Budget column" \
  --backend ollama

sep "3c. Ollama — write a review label into column Notes"
uv run vitreus analyze "$CSV" \
  "For rows with Score below 70, write 'Needs Improvement' into the Notes cell" \
  --backend ollama

sep "3d. Ollama — generate a SUM formula for total budget spent"
uv run vitreus analyze "$CSV" \
  "Add a SUM formula in the cell below the Spent column to total all spending" \
  --backend ollama

sep "3e. Ollama — use the lighter 4B drafter model"
uv run vitreus analyze "$CSV" \
  "Highlight rows that need review" \
  --backend ollama \
  --model gemma4:4b


# ─── 4. ANALYZE — Google AI Studio backend (requires: GEMINI_API_KEY) ────────
sep "4a. Google — identify top performers"
uv run vitreus analyze "$CSV" \
  "Highlight the top 3 performers by Score in green" \
  --backend google

sep "4b. Google — budget risk analysis"
uv run vitreus analyze "$CSV" \
  "Flag any row where Spent is more than 10 percent over Budget with a red highlight and write 'OVER BUDGET' in Notes" \
  --backend google

sep "4c. Google — custom model name override"
uv run vitreus analyze "$CSV" \
  "Summarise department-level spending" \
  --backend google \
  --model gemma-4-31b-it

sep "4d. Google — inline API key (without env var)"
# uv run vitreus analyze "$CSV" "Highlight at-risk rows" --backend google --api-key YOUR_KEY_HERE
echo "  (uncomment and set --api-key to test inline key)"


# ─── 5. APPLY-MANIFEST — pipe analyze output into apply-manifest ──────────────
sep "5a. Analyze → save manifest → apply it"
uv run vitreus analyze "$CSV" "Highlight rows that need review" \
  > /tmp/vitreus_manifest.json

echo "Manifest saved to /tmp/vitreus_manifest.json:"
cat /tmp/vitreus_manifest.json

echo
echo "Applying manifest:"
uv run vitreus apply-manifest "$CSV" /tmp/vitreus_manifest.json

sep "5b. Apply a hand-written write_value manifest"
cat > /tmp/manual_manifest.json << 'EOF'
{
  "actions": [
    {"type": "write_value", "cell": "Sheet1!K3", "value": "REVIEWED"},
    {"type": "write_value", "cell": "Sheet1!K9", "value": "FLAGGED"},
    {"type": "formula",     "cell": "Sheet1!J11", "formula": "=SUM(J2:J10)", "reason": "Total spending across all rows"}
  ]
}
EOF
uv run vitreus apply-manifest "$CSV" /tmp/manual_manifest.json

sep "5c. Apply a highlight-only manifest"
cat > /tmp/highlight_manifest.json << 'EOF'
{
  "actions": [
    {"type": "highlight", "range": "Sheet1!A2:K3", "color": "#f97316", "reason": "Alan Turing: over budget"},
    {"type": "highlight", "range": "Sheet1!A9:K9", "color": "#ef4444", "reason": "Dennis Ritchie: over budget and low score"}
  ]
}
EOF
uv run vitreus apply-manifest "$CSV" /tmp/highlight_manifest.json


# ─── 6. ONE-SHOT OUTPUT — analyze + apply + save in a single command ─────────
sep "6a. One-shot: analyze CSV → save as annotated XLSX"
uv run vitreus analyze "$CSV" \
  "Highlight rows where Spent exceeds Budget in orange, write OVER BUDGET in the Notes column" \
  --backend google \
  --output /tmp/vitreus_result.xlsx
echo "  Saved to /tmp/vitreus_result.xlsx — open in LibreOffice or Excel to see colors."

sep "6b. One-shot: analyze CSV → save as CSV (with _highlights.json sidecar)"
uv run vitreus analyze "$CSV" \
  "Highlight the top performer row in green" \
  --output /tmp/vitreus_result.csv 2>&1 || true
echo "  Written: /tmp/vitreus_result.csv  +  /tmp/vitreus_result_highlights.json"

sep "6c. One-shot: analyze XLSX → save as XLSX (round-trip)"
uv run vitreus analyze "$XLSX" \
  "In the Sales sheet, highlight any rep whose Quota_Attainment is below 80% in red" \
  --backend google \
  --output /tmp/vitreus_sales_result.xlsx
echo "  Saved to /tmp/vitreus_sales_result.xlsx"

sep "6d. One-shot: analyze XLSX with a specific sheet"
uv run vitreus analyze "$XLSX" \
  "In the Expenses sheet, highlight rows where Annual_Actual exceeds Annual_Budget" \
  --backend google \
  --sheet Expenses \
  --output /tmp/vitreus_expenses_result.xlsx
echo "  Saved to /tmp/vitreus_expenses_result.xlsx"


# ─── 7. VISION — multimodal image payload ─────────────────────────────────────
sep "7. Vision — prepare a chart image payload (replace path with real image)"
# uv run vitreus vision path/to/chart.png --purpose chart
# uv run vitreus vision path/to/receipt.jpg --purpose receipt
echo "  Usage examples (replace with a real image path):"
echo "    uv run vitreus vision path/to/chart.png --purpose chart"
echo "    uv run vitreus vision path/to/receipt.jpg --purpose receipt"
echo "    uv run vitreus vision path/to/screenshot.png --purpose screenshot"


# ─── 8. COMBINED PIPELINE — analyze with Ollama, then apply ───────────────────
sep "8. Full pipeline: Ollama analyze → apply manifest"
uv run vitreus analyze "$CSV" \
  "Highlight rows where Score is below 70 and flag them for immediate review" \
  --backend ollama \
  > /tmp/pipeline_manifest.json 2>/dev/null || {
  echo "  (Ollama not running — skipped. Start ollama and pull gemma4:31b to test this.)"
  cat > /tmp/pipeline_manifest.json << 'EOF'
{"actions": [{"type": "highlight","range": "Sheet1!A3:K3","color": "#ef4444","reason": "Score 65 — below 70"}]}
EOF
}
uv run vitreus apply-manifest "$CSV" /tmp/pipeline_manifest.json


echo
echo "═══════════════════════════════════════════════════════════"
echo "  All test commands completed."
echo "  Tip: pipe any analyze output to 'jq .' for pretty printing."
echo "  Tip: export GEMINI_API_KEY=<key> before running section 4-6."
echo "  Tip: open .xlsx results in LibreOffice Calc to see colors."
echo "═══════════════════════════════════════════════════════════"

# =============================================================================
# Vitreus — Test Commands Reference
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

sep() { echo; echo "─────────────────────────────────────────────────"; echo "▶ $*"; echo "─────────────────────────────────────────────────"; }


# ─── 1. MODELS ───────────────────────────────────────────────────────────────
sep "1. Show Gemma 4 model selection"
uv run vitreus models


# ─── 2. ANALYZE — fallback planner (no model required) ───────────────────────
sep "2a. Highlight rows with scores below 80 (needs review)"
uv run vitreus analyze "$CSV" "Highlight rows that need review"

sep "2b. Highlight rows that are under review or at risk"
uv run vitreus analyze "$CSV" "Highlight rows with Status Under Review or At Risk"

sep "2c. Highlight rows where spending exceeds budget (over budget)"
uv run vitreus analyze "$CSV" "Highlight rows that need review" --sheet Sheet1


# ─── 3. ANALYZE — local Ollama backend (requires: ollama pull gemma4:31b) ────
sep "3a. Ollama — summarise Q1 vs Q2 performance trends"
uv run vitreus analyze "$CSV" \
  "Summarise the Q1 vs Q2 performance trend for each person" \
  --backend ollama

sep "3b. Ollama — flag rows where Spent exceeds Budget"
uv run vitreus analyze "$CSV" \
  "Highlight all rows where the Spent column exceeds the Budget column" \
  --backend ollama

sep "3c. Ollama — write a review label into column Notes"
uv run vitreus analyze "$CSV" \
  "For rows with Score below 70, write 'Needs Improvement' into the Notes cell" \
  --backend ollama

sep "3d. Ollama — generate a SUM formula for total budget spent"
uv run vitreus analyze "$CSV" \
  "Add a SUM formula in the cell below the Spent column to total all spending" \
  --backend ollama

sep "3e. Ollama — use the lighter 4B drafter model"
uv run vitreus analyze "$CSV" \
  "Highlight rows that need review" \
  --backend ollama \
  --model gemma4:4b


# ─── 4. ANALYZE — Google AI Studio backend (requires: GEMINI_API_KEY) ────────
sep "4a. Google — identify top performers"
uv run vitreus analyze "$CSV" \
  "Highlight the top 3 performers by Score in green" \
  --backend google

sep "4b. Google — budget risk analysis"
uv run vitreus analyze "$CSV" \
  "Flag any row where Spent is more than 10 percent over Budget with a red highlight and write 'OVER BUDGET' in Notes" \
  --backend google

sep "4c. Google — custom model name override"
uv run vitreus analyze "$CSV" \
  "Summarise department-level spending" \
  --backend google \
  --model gemma-4-31b-it

sep "4d. Google — inline API key (without env var)"
# uv run vitreus analyze "$CSV" "Highlight at-risk rows" --backend google --api-key YOUR_KEY_HERE
echo "  (uncomment and set --api-key to test inline key)"


# ─── 5. APPLY-MANIFEST — pipe analyze output into apply-manifest ──────────────
sep "5a. Analyze → save manifest → apply it"
uv run vitreus analyze "$CSV" "Highlight rows that need review" \
  > /tmp/vitreus_manifest.json

echo "Manifest saved to /tmp/vitreus_manifest.json:"
cat /tmp/vitreus_manifest.json

echo
echo "Applying manifest:"
uv run vitreus apply-manifest "$CSV" /tmp/vitreus_manifest.json

sep "5b. Apply a hand-written write_value manifest"
cat > /tmp/manual_manifest.json << 'EOF'
{
  "actions": [
    {"type": "write_value", "cell": "Sheet1!K3", "value": "REVIEWED"},
    {"type": "write_value", "cell": "Sheet1!K9", "value": "FLAGGED"},
    {"type": "formula",     "cell": "Sheet1!J11", "formula": "=SUM(J2:J10)", "reason": "Total spending across all rows"}
  ]
}
EOF
uv run vitreus apply-manifest "$CSV" /tmp/manual_manifest.json

sep "5c. Apply a highlight-only manifest"
cat > /tmp/highlight_manifest.json << 'EOF'
{
  "actions": [
    {"type": "highlight", "range": "Sheet1!A2:K3", "color": "#f97316", "reason": "Alan Turing: over budget"},
    {"type": "highlight", "range": "Sheet1!A9:K9", "color": "#ef4444", "reason": "Dennis Ritchie: over budget and low score"}
  ]
}
EOF
uv run vitreus apply-manifest "$CSV" /tmp/highlight_manifest.json


# ─── 6. VISION — multimodal image payload ─────────────────────────────────────
sep "6. Vision — prepare a chart image payload (replace path with real image)"
# uv run vitreus vision path/to/chart.png --purpose chart
# uv run vitreus vision path/to/receipt.jpg --purpose receipt
echo "  Usage examples (replace with a real image path):"
echo "    uv run vitreus vision path/to/chart.png --purpose chart"
echo "    uv run vitreus vision path/to/receipt.jpg --purpose receipt"
echo "    uv run vitreus vision path/to/screenshot.png --purpose screenshot"


# ─── 7. COMBINED PIPELINE — analyze with Ollama, then apply ───────────────────
sep "7. Full pipeline: Ollama analyze → apply manifest"
uv run vitreus analyze "$CSV" \
  "Highlight rows where Score is below 70 and flag them for immediate review" \
  --backend ollama \
  > /tmp/pipeline_manifest.json 2>/dev/null || {
  echo "  (Ollama not running — skipped. Start ollama and pull gemma4:31b to test this.)"
  cat > /tmp/pipeline_manifest.json << 'EOF'
{"actions": [{"type": "highlight","range": "Sheet1!A3:K3","color": "#ef4444","reason": "Score 65 — below 70"}]}
EOF
}
uv run vitreus apply-manifest "$CSV" /tmp/pipeline_manifest.json


echo
echo "═══════════════════════════════════════════════════════════"
echo "  All test commands completed."
echo "  Tip: pipe any analyze output to 'jq .' for pretty printing."
echo "  Tip: export GEMINI_API_KEY=<key> before running section 4."
echo "═══════════════════════════════════════════════════════════"
