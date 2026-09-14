# Vitreus chat (REPL) screenshot tape — uses the primary Gemma 4 31B model.
# From the repo root, after docs/assets/vhs/prepare.sh:
#   vhs docs/assets/vhs/chat.tape
# The GIF it writes (chat-scratch.gif) is a by-product; delete it and keep only the screenshot.

Output docs/assets/showcase/chat-scratch.gif

Set Shell "bash"
Set FontSize 15
Set Width 1400
Set Height 820
Set Padding 16
Set WindowBar Colorful
Set Theme "Catppuccin Macchiato"
Set TypingSpeed 40ms

Hide
Type "export PATH=/tmp/vitreus-demo:$PATH && cd /tmp/vitreus-demo && rm -f budget-reviewed.xlsx && clear"
Enter
Show

Type "vitreus chat budget.csv"
Enter
Wait+Screen@30s /vitreus>/
Sleep 1s

Type "Which rows are over budget, and by how much?"
Sleep 400ms
Enter
Wait+Screen@120s /Dennis Ritchie/
Sleep 1.5s

Type "Add a Variance column after Notes with Spent minus Budget for every row, and bold the header row"
Sleep 400ms
Enter
Wait+Screen@120s /preview to see the diff/
Sleep 1.5s

Type "/preview"
Enter
Wait+Screen@30s /L11/
Sleep 1.5s

Type "/apply"
Enter
Wait+Screen@30s /Applied 3 action/
Sleep 800ms

Type "/save budget-reviewed.xlsx"
Enter
Wait+Screen@30s /Saved budget-reviewed.xlsx/
Sleep 2s
Screenshot docs/assets/showcase/chat.png
Sleep 1s
