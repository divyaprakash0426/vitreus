#!/usr/bin/env nu

# Vitreus Nushell integration.
# Load for one session from the repo root with: use scripts/calc.nu *
# To load automatically, add that same line to your config.nu.

def pipeline-to-csv [command_name: string] {
  let input = $in

  if (($input == null) or ($input | is-empty)) {
    error make {msg: $"($command_name) expects non-empty pipeline input. Try: open data.csv | ($command_name) \"highlight rows that need review\""}
  }

  # Nu renders filesizes/durations as "1.0 kB"/"2sec" in CSV; give the model plain numbers instead.
  $input
  | update cells {|value|
      match ($value | describe) {
        'filesize' => ($value | into int)
        'duration' => ($value | into int)
        'datetime' => ($value | format date '%Y-%m-%d %H:%M:%S')
        _ => $value
      }
    }
  | to csv
}

export def --wrapped "vitreus sheet" [
  query: string
  ...rest: string
] {
  $in | pipeline-to-csv "vitreus sheet" | ^vitreus analyze - $query ...$rest
}

export def --wrapped "vitreus ask" [
  question: string
  ...rest: string
] {
  $in | pipeline-to-csv "vitreus ask" | ^vitreus ask - $question ...$rest
}

export def --wrapped "vitreus live" [
  query: string
  ...rest: string
] {
  ^vitreus analyze --live $query ...$rest
}

export def --wrapped "vitreus table" [
  query: string
  ...rest: string
] {
  $in | pipeline-to-csv "vitreus table" | ^vitreus analyze - $query --preview ...$rest | from json
}
