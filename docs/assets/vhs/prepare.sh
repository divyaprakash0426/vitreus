#!/usr/bin/env bash
# Prepare a scratch environment for the showcase recordings.
#
#   docs/assets/vhs/prepare.sh && vhs docs/assets/vhs/demo.tape
#
# Creates /tmp/vitreus-demo with a `vitreus` wrapper (repo venv) and scratch copies of the example
# workbooks, so the tape never touches files in the repository. Model/API settings come from your
# environment: with no local Ollama, export GEMINI_API_KEY (or OPENROUTER_API_KEY) before recording.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../../.." && pwd)
demo=/tmp/vitreus-demo
rm -rf "$demo"
mkdir -p "$demo"

cp "$repo/examples/sample_workbook.csv" "$demo/budget.csv"
cp "$repo/examples/test_workbook.xlsx" "$demo/sales.xlsx"

cat > "$demo/vitreus" <<WRAP
#!/usr/bin/env bash
exec "$repo/.venv/bin/vitreus" "\$@"
WRAP
chmod +x "$demo/vitreus"

[ -x "$repo/.venv/bin/vitreus" ] || { echo "run 'uv sync' in $repo first" >&2; exit 1; }
echo "ready: $demo (PATH=$demo:\$PATH)"
