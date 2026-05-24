#!/usr/bin/env nu

# Pipe CSV data into Vitreus from Nushell:
# open scores.csv | save -f /tmp/vitreus.csv; vitreus-analyze /tmp/vitreus.csv "Highlight rows that need review"

def "vitreus-analyze" [csv_path: path, query: string] {
  uv run vitreus analyze $csv_path $query
}

def "vitreus-models" [] {
  uv run vitreus models
}
