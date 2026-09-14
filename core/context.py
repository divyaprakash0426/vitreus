"""Compress a WorkbookSnapshot into a token-budgeted prompt context ("Deep Context")."""

from __future__ import annotations

import csv
import io
from typing import Any

from core.driver import WorkbookSnapshot, column_name

HEAD_ROWS = 20
TAIL_ROWS = 5
SAMPLE_VALUES = 3


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def _kind(value: Any) -> str:
    if value is None or value == "":
        return "empty"
    if isinstance(value, bool):
        return "text"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str) and value.startswith("="):
        return "formula"
    return "text"


def describe_sheet(snapshot: WorkbookSnapshot, sheet: str) -> dict[str, Any]:
    rows = snapshot.sheets.get(sheet, [])
    n_rows, n_cols = snapshot.dims(sheet)
    header = rows[0] if rows else []
    columns: list[dict[str, Any]] = []
    for c in range(n_cols):
        name = str(header[c]) if c < len(header) and header[c] != "" else ""
        values = [row[c] for row in rows[1:] if c < len(row)]
        kinds = {_kind(v) for v in values} - {"empty"}
        numeric = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not kinds:
            col_type = "empty"
        elif kinds <= {"int"}:
            col_type = "int"
        elif kinds <= {"int", "float"}:
            col_type = "float"
        elif len(kinds) == 1:
            col_type = next(iter(kinds))
        else:
            col_type = "mixed"
        info: dict[str, Any] = {
            "letter": column_name(c),
            "name": name,
            "type": col_type,
            "non_empty": sum(1 for v in values if _kind(v) != "empty"),
        }
        if numeric and col_type in {"int", "float", "mixed"}:
            info["min"] = _tidy(min(numeric))
            info["max"] = _tidy(max(numeric))
            info["mean"] = round(sum(numeric) / len(numeric), 2)
        if col_type in {"text", "mixed", "formula"}:
            seen: list[str] = []
            for v in values:
                if _kind(v) != "empty" and str(v) not in seen:
                    seen.append(str(v))
                if len(seen) >= SAMPLE_VALUES:
                    break
            info["sample"] = seen
        columns.append(info)
    return {"sheet": sheet, "rows": n_rows, "cols": n_cols, "data_range": snapshot.data_range(sheet), "columns": columns}


def _tidy(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 4)


def sheet_rows_csv(snapshot: WorkbookSnapshot, sheet: str, start_row: int = 1, end_row: int | None = None) -> str:
    """CSV with a leading `row` column and lettered headers; rows are 1-based inclusive."""
    rows = snapshot.sheets.get(sheet, [])
    _, n_cols = snapshot.dims(sheet)
    end_row = len(rows) if end_row is None else min(end_row, len(rows))
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["row"] + [column_name(c) for c in range(n_cols)])
    for r in range(max(start_row, 1), end_row + 1):
        row = rows[r - 1]
        writer.writerow([r] + list(row) + [""] * (n_cols - len(row)))
    return buffer.getvalue()


def _column_summary(info: dict[str, Any]) -> str:
    parts = [f"{info['letter']} {info['name'] or '(unnamed)'} ({info['type']}"]
    if "min" in info:
        parts[0] += f", min {info['min']}, max {info['max']}, mean {info['mean']}"
    if info.get("sample"):
        parts[0] += ", e.g. " + ", ".join(repr(s) for s in info["sample"])
    parts[0] += f", {info['non_empty']} non-empty)"
    return parts[0]


def build_context(snapshot: WorkbookSnapshot, budget_tokens: int = 24000, sheets: list[str] | None = None) -> str:
    all_names = list(snapshot.sheets)
    chosen = [name for name in (sheets or all_names) if name in snapshot.sheets] or all_names
    header = f"# Workbook: {snapshot.source or 'workbook'} ({len(all_names)} sheet{'s' if len(all_names) != 1 else ''}: {', '.join(all_names)})"
    parts = [header]
    hidden = [name for name in all_names if name not in chosen]
    if hidden:
        parts.append(f"Other sheets (not shown): {', '.join(hidden)}")

    per_sheet_budget = max(budget_tokens // max(len(chosen), 1), 200)
    for name in chosen:
        info = describe_sheet(snapshot, name)
        section = [
            f'## Sheet "{name}" — {info["rows"]} rows x {info["cols"]} columns, data range {info["data_range"]}',
            "Columns: " + "; ".join(_column_summary(col) for col in info["columns"]) if info["columns"] else "Columns: (none)",
        ]
        if info["rows"]:
            full = sheet_rows_csv(snapshot, name)
            if estimate_tokens(full) <= per_sheet_budget:
                section.append("Rows (row number, then cells by column letter):")
                section.append(full.rstrip("\n"))
            else:
                head_end = min(HEAD_ROWS + 1, info["rows"])
                tail_start = max(info["rows"] - TAIL_ROWS + 1, head_end + 1)
                omitted = max(tail_start - head_end - 1, 0)
                section.append(f"Rows (first {head_end} and last {info['rows'] - tail_start + 1} shown; {omitted} rows omitted — use the get_range tool for specific rows):")
                section.append(sheet_rows_csv(snapshot, name, 1, head_end).rstrip("\n"))
                if tail_start <= info["rows"]:
                    tail = sheet_rows_csv(snapshot, name, tail_start, info["rows"]).splitlines()[1:]
                    section.append("...")
                    section.append("\n".join(tail))
        parts.append("\n".join(section))
    return "\n\n".join(parts)
