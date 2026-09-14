# Vitreus showcase tape
# From the repo root:
#   docs/assets/vhs/prepare.sh            # scratch workbooks + wrapper in /tmp/vitreus-demo
#   vhs docs/assets/vhs/demo.tape
#
# The tape only touches copies in /tmp/vitreus-demo. Model settings come from the environment:
# the published recording used Google AI Studio (VITREUS_BACKEND=google, GEMINI_API_KEY set)
# because the recording machine had no GPU; with Ollama running, drop VITREUS_BACKEND and the
# same commands run fully local on gemma4:31b / gemma4:e4b.

Output docs/assets/showcase/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1400
Set Height 820
Set Padding 16
Set WindowBar Colorful
Set Theme "Catppuccin Macchiato"
Set TypingSpeed 40ms

Hide
Type "export PATH=/tmp/vitreus-demo:$PATH && cd /tmp/vitreus-demo && rm -f plan.json budget-reviewed.xlsx && clear"
Enter
Show

# 1. Plan: the model proposes a manifest; the UI goes to stderr, the JSON to stdout (here: a file)
Type `vitreus analyze budget.csv "Highlight rows where Spent exceeds Budget and write OVER in their Status" --preview --fast > plan.json`
Sleep 600ms
Enter
Wait+Screen@90s /Highlights:/
Sleep 2.5s
Screenshot docs/assets/showcase/preview.png
Sleep 2s

# 2. Apply the reviewed manifest to a workbook
Type "clear"
Enter
Type "vitreus apply-manifest budget.csv plan.json -o budget-reviewed.xlsx"
Sleep 500ms
Enter
Wait+Screen@30s /"saved"/
Sleep 3s

# 3. Live LibreOffice Calc: open a workbook headlessly and let the agent edit it in place
Type "clear"
Enter
Type "vitreus calc launch sales.xlsx --headless --port 2201"
Sleep 400ms
Enter
Wait+Screen@60s /"headless": true/
Sleep 1s
Type "sleep 5 && clear"
Enter
Sleep 6s
Type `vitreus analyze --live --port 2201 --sheet Sales "Highlight reps with quota attainment below 90% and write REVIEW in their Status" --fast --yes > /dev/null`
Sleep 600ms
Enter
Wait+Screen@120s /Applied 12 actions/
Sleep 3.5s
Screenshot docs/assets/showcase/live.png

# 4. Ask a question with the primary Gemma 4 31B model
Type "clear"
Enter
Type `vitreus ask budget.csv "Which department is most over budget in total, and by how much?"`
Sleep 500ms
Enter
Wait+Screen@120s /Research/
Sleep 5s
