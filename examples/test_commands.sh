#!/usr/bin/env bash
# Vitreus command walkthrough for bash.
# Run from the repo root: bash examples/test_commands.sh

set -euo pipefail

CSV="examples/sample_workbook.csv"
XLSX="examples/test_workbook.xlsx"
TMP_DIR="/tmp/vitreus-examples"
MANIFEST="$TMP_DIR/fallback-manifest.json"
run_live=0
run_chat=0

section() {
  printf '\n== %s ==\n' "$*"
}

have_ollama_model() {
  command -v ollama >/dev/null 2>&1 \
    && ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -Fxq "gemma4:31b"
}

mkdir -p "$TMP_DIR"

# (a) Doctor, models, and config.
section "Doctor, models, config"
uv run vitreus doctor
uv run vitreus models --backend fallback
uv run vitreus config --show

# (b) Offline fallback demo. These commands require no model or API key.
section "Offline fallback demo"
uv run vitreus analyze "$CSV" \
  "Highlight rows where Spent exceeds Budget" \
  --backend fallback \
  --preview > "$MANIFEST"
uv run vitreus ask "$CSV" \
  "Highlight rows where Spent exceeds Budget" \
  --backend fallback

# (c) Local Ollama usage. This is the primary backend when gemma4:31b is present.
section "Local Ollama usage"
if have_ollama_model; then
  uv run vitreus analyze "$CSV" \
    "Highlight rows where Spent exceeds Budget and explain the budget risk" \
    --backend ollama
  uv run vitreus ask "$CSV" \
    "Which department is most over budget?" \
    --backend ollama
  uv run vitreus analyze "$CSV" \
    "Highlight rows where Score is below 80" \
    --backend ollama \
    --fast
else
  echo "Skipping Ollama examples; run scripts/setup_arch.sh or ollama pull gemma4:31b."
fi

# (d) Optional API backends.
section "Optional API backends"
if [ -n "${GEMINI_API_KEY:-}" ]; then
  uv run vitreus analyze "$CSV" \
    "Highlight the top 3 performers by Score in green" \
    --backend google
else
  echo "Skipping Google AI Studio example; set GEMINI_API_KEY."
fi

if [ -n "${OPENROUTER_API_KEY:-}" ]; then
  uv run vitreus analyze "$CSV" \
    "Flag departments where spending exceeds budget" \
    --backend openrouter
else
  echo "Skipping OpenRouter example; set OPENROUTER_API_KEY."
fi

if [ -n "${OPENAI_API_KEY:-}" ]; then
  uv run vitreus analyze "$CSV" \
    "Summarize rows needing review" \
    --backend openai
else
  echo "Skipping OpenAI-compatible example; set OPENAI_API_KEY and optionally OPENAI_BASE_URL."
fi

# (e) Preview vs apply vs in-place.
section "Preview, apply, and in-place"
uv run vitreus analyze "$CSV" \
  "Highlight rows where Spent exceeds Budget" \
  --backend fallback \
  --preview > "$MANIFEST"
uv run vitreus apply-manifest "$CSV" "$MANIFEST" \
  --output "$TMP_DIR/applied.xlsx"
cp "$CSV" "$TMP_DIR/in-place.csv"
uv run vitreus analyze "$TMP_DIR/in-place.csv" \
  "Highlight rows where Spent exceeds Budget" \
  --backend fallback \
  --in-place
uv run vitreus analyze "$CSV" \
  "Highlight rows where Spent exceeds Budget" \
  --backend fallback \
  --output "$TMP_DIR/from-csv.xlsx"

# (f) stdin/pipeline usage and Nushell wrappers.
section "stdin and pipeline"
cat "$CSV" | uv run vitreus analyze - \
  "Highlight rows where Spent exceeds Budget" \
  --backend fallback \
  --preview
echo "Nushell direct pipeline:"
echo "  ls | to csv | uv run vitreus analyze - \"highlight files over 1 MB\" --backend fallback"
echo "Nushell wrappers:"
echo "  use scripts/calc.nu *"
echo "  ls | vitreus sheet \"highlight files over 1 MB\" -o files.xlsx"
echo "  open budget.csv | vitreus ask \"which department is over budget?\""
echo "  vitreus live \"flag negative margins\" --yes"
echo "  open examples/sample_workbook.csv | vitreus table \"Highlight rows where Spent exceeds Budget\" --backend fallback"

# (g) Batch.
section "Batch"
uv run vitreus batch \
  "Highlight rows where Spent exceeds Budget" \
  "$CSV" \
  --backend fallback \
  --output-dir "$TMP_DIR/batch"

# (h) Vision.
section "Vision"
if [ -n "${GEMINI_API_KEY:-}" ]; then
  echo "Example with your own image:"
  echo "  uv run vitreus vision receipt.jpg --purpose receipt --output receipt.xlsx --backend google"
else
  echo "Skipping vision execution; provide an image and set GEMINI_API_KEY or use a vision-capable local backend."
  echo "  uv run vitreus vision chart.png --purpose chart --output chart.xlsx"
  echo "  uv run vitreus vision table.png --purpose table --output table.xlsx"
fi

# (i) Live LibreOffice Calc.
section "Live LibreOffice"
if [ "$run_live" = "1" ] && command -v soffice >/dev/null 2>&1; then
  uv run vitreus calc launch "$XLSX" --headless --port 2002
  sleep 6  # give soffice time to open the UNO listener
  uv run vitreus calc status --port 2002
  uv run vitreus analyze --live \
    "Highlight rows where Q2_Target exceeds Q2_Actual" \
    --sheet Sales \
    --backend fallback \
    --yes \
    --port 2002
else
  echo "Skipping live Calc execution by default; set run_live=1 in this script and install libreoffice-fresh."
  echo "  uv run vitreus calc launch examples/test_workbook.xlsx --headless --port 2002"
  echo "  uv run vitreus calc status --port 2002"
  echo "  uv run vitreus analyze --live \"Highlight rows where Q2_Target exceeds Q2_Actual\" --sheet Sales --backend fallback --yes --port 2002"
fi

# (j) Chat.
section "Chat"
if [ "$run_chat" = "1" ] && { have_ollama_model || [ -n "${GEMINI_API_KEY:-}" ]; }; then
  echo "Starting chat; press Ctrl-D or type the CLI's exit command when done."
  uv run vitreus chat "$CSV" --backend auto
else
  echo "Skipping interactive chat; set run_chat=1 in this script and install gemma4:31b or set GEMINI_API_KEY."
  echo "  uv run vitreus chat examples/sample_workbook.csv --backend ollama"
fi

echo
echo "Vitreus command walkthrough completed."
