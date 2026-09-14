# Vitreus command walkthrough for Nushell.
# Run from the repo root: nu examples/test_commands.nu

use ../scripts/calc.nu *

let csv = "examples/sample_workbook.csv"
let xlsx = "examples/test_workbook.xlsx"
let tmp_dir = "/tmp/vitreus-examples-nu"
let manifest = ($tmp_dir | path join "fallback-manifest.json")
let run_live = false
let run_chat = false

def section [label: string] {
  print ""
  print $"== ($label) =="
}

def has-env [name: string] {
  let value = ($env | get --optional $name)
  ($value != null) and (($value | into string | is-not-empty))
}

def have-ollama-model [] {
  if (which ollama | is-empty) {
    false
  } else {
    let models = (ollama list | complete)
    if ($models.exit_code != 0) {
      false
    } else {
      $models.stdout | lines | skip 1 | any {|line| ($line | split row --regex '\s+' | first) == "gemma4:31b" }
    }
  }
}

mkdir $tmp_dir

# (a) Doctor, models, and config.
section "Doctor, models, config"
uv run vitreus doctor
uv run vitreus models --backend fallback
uv run vitreus config --show

# (b) Offline fallback demo. These commands require no model or API key.
section "Offline fallback demo"
uv run vitreus analyze $csv "Highlight rows where Spent exceeds Budget" --backend fallback --preview | save --force $manifest
uv run vitreus ask $csv "Highlight rows where Spent exceeds Budget" --backend fallback

# (c) Local Ollama usage. This is the primary backend when gemma4:31b is present.
section "Local Ollama usage"
if (have-ollama-model) {
  uv run vitreus analyze $csv "Highlight rows where Spent exceeds Budget and explain the budget risk" --backend ollama
  uv run vitreus ask $csv "Which department is most over budget?" --backend ollama
  uv run vitreus analyze $csv "Highlight rows where Score is below 80" --backend ollama --fast
} else {
  print "Skipping Ollama examples; run scripts/setup_arch.sh or ollama pull gemma4:31b."
}

# (d) Optional API backends.
section "Optional API backends"
if (has-env "GEMINI_API_KEY") {
  uv run vitreus analyze $csv "Highlight the top 3 performers by Score in green" --backend google
} else {
  print "Skipping Google AI Studio example; set GEMINI_API_KEY."
}

if (has-env "OPENROUTER_API_KEY") {
  uv run vitreus analyze $csv "Flag departments where spending exceeds budget" --backend openrouter
} else {
  print "Skipping OpenRouter example; set OPENROUTER_API_KEY."
}

if (has-env "OPENAI_API_KEY") {
  uv run vitreus analyze $csv "Summarize rows needing review" --backend openai
} else {
  print "Skipping OpenAI-compatible example; set OPENAI_API_KEY and optionally OPENAI_BASE_URL."
}

# (e) Preview vs apply vs in-place.
section "Preview, apply, and in-place"
uv run vitreus analyze $csv "Highlight rows where Spent exceeds Budget" --backend fallback --preview | save --force $manifest
uv run vitreus apply-manifest $csv $manifest --output ($tmp_dir | path join "applied.xlsx")
cp $csv ($tmp_dir | path join "in-place.csv")
uv run vitreus analyze ($tmp_dir | path join "in-place.csv") "Highlight rows where Spent exceeds Budget" --backend fallback --in-place
uv run vitreus analyze $csv "Highlight rows where Spent exceeds Budget" --backend fallback --output ($tmp_dir | path join "from-csv.xlsx")

# (f) stdin/pipeline usage and Nushell wrappers.
section "stdin and pipeline"
open $csv | to csv | uv run vitreus analyze - "Highlight rows where Spent exceeds Budget" --backend fallback --preview
ls | to csv | uv run vitreus analyze - "highlight files over 1 MB" --backend fallback --preview
if (which vitreus | is-empty) {
  print "Skipping calc.nu wrapper execution; put the vitreus binary on PATH to run these:"
  print "  use scripts/calc.nu *"
  print "  ls | vitreus sheet \"highlight files over 1 MB\" -o files.xlsx"
  print "  open budget.csv | vitreus ask \"which department is over budget?\""
  print "  vitreus live \"flag negative margins\" --yes"
  print "  open examples/sample_workbook.csv | vitreus table \"Highlight rows where Spent exceeds Budget\" --backend fallback"
} else {
  open $csv | vitreus table "Highlight rows where Spent exceeds Budget" --backend fallback
}

# (g) Batch.
section "Batch"
uv run vitreus batch "Highlight rows where Spent exceeds Budget" $csv --backend fallback --output-dir ($tmp_dir | path join "batch")

# (h) Vision.
section "Vision"
if (has-env "GEMINI_API_KEY") {
  print "Example with your own image:"
  print "  uv run vitreus vision receipt.jpg --purpose receipt --output receipt.xlsx --backend google"
} else {
  print "Skipping vision execution; provide an image and set GEMINI_API_KEY or use a vision-capable local backend."
  print "  uv run vitreus vision chart.png --purpose chart --output chart.xlsx"
  print "  uv run vitreus vision table.png --purpose table --output table.xlsx"
}

# (i) Live LibreOffice Calc.
section "Live LibreOffice"
if ($run_live and ((which soffice | is-empty) == false)) {
  uv run vitreus calc launch $xlsx --headless --port 2002
  sleep 6sec  # give soffice time to open the UNO listener
  uv run vitreus calc status --port 2002
  uv run vitreus analyze --live "Highlight rows where Q2_Target exceeds Q2_Actual" --sheet Sales --backend fallback --yes --port 2002
} else {
  print "Skipping live Calc execution by default; set run_live = true in this script and install libreoffice-fresh."
  print "  uv run vitreus calc launch examples/test_workbook.xlsx --headless --port 2002"
  print "  uv run vitreus calc status --port 2002"
  print "  uv run vitreus analyze --live \"Highlight rows where Q2_Target exceeds Q2_Actual\" --sheet Sales --backend fallback --yes --port 2002"
}

# (j) Chat.
section "Chat"
if ($run_chat and ((have-ollama-model) or (has-env "GEMINI_API_KEY"))) {
  print "Starting chat; press Ctrl-D or type the CLI's exit command when done."
  uv run vitreus chat $csv --backend auto
} else {
  print "Skipping interactive chat; set run_chat = true in this script and install gemma4:31b or set GEMINI_API_KEY."
  print "  uv run vitreus chat examples/sample_workbook.csv --backend ollama"
}

print ""
print "Vitreus command walkthrough completed."
