from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any


CELL_RE = re.compile(r"^(?P<sheet>[^!]+)!(?P<start>[A-Z]+[0-9]+)(?::(?P<end>[A-Z]+[0-9]+))?$")


@dataclass(frozen=True)
class CellFormat:
    background: str | None = None


@dataclass(frozen=True)
class ManifestSummary:
    applied: int
    errors: list[str] = field(default_factory=list)


@dataclass
class WorkbookSnapshot:
    sheets: dict[str, list[list[Any]]]

    @classmethod
    def from_csv(cls, path: str, sheet_name: str = "Sheet1") -> "WorkbookSnapshot":
        with open(path, newline="", encoding="utf-8") as handle:
            rows = [[_coerce_value(value) for value in row] for row in csv.reader(handle)]
        return cls(sheets={sheet_name: rows})

    def to_csv(self, sheet_name: str = "Sheet1") -> str:
        """Return the sheet as a CSV string (all rows, all columns)."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerows(self.sheets.get(sheet_name, []))
        return buffer.getvalue()

    def save_csv(self, path: str, sheet_name: str = "Sheet1") -> None:
        """Write the sheet back to a CSV file on disk."""
        with open(path, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(self.sheets.get(sheet_name, []))

    def range_to_csv(self, range_name: str) -> str:
        rows = self._slice(range_name)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerows(rows)
        return buffer.getvalue()

    def range_to_json(self, range_name: str) -> str:
        parsed = _parse_range(range_name)
        rows = self._slice(range_name)
        if not rows or parsed.sheet not in self.sheets:
            return "[]"
        sheet = self.sheets[parsed.sheet]
        header_row = sheet[0][parsed.start_col : parsed.end_col + 1]
        headers = [str(header) for header in header_row]
        data_rows = rows if parsed.start_row > 0 else rows[1:]
        records = [dict(zip(headers, row, strict=False)) for row in data_rows]
        return json.dumps(records)

    def _slice(self, range_name: str) -> list[list[Any]]:
        parsed = _parse_range(range_name)
        sheet = self.sheets.get(parsed.sheet)
        if sheet is None:
            raise KeyError(f"Unknown sheet: {parsed.sheet}")
        result: list[list[Any]] = []
        for row in sheet[parsed.start_row : parsed.end_row + 1]:
            result.append(row[parsed.start_col : parsed.end_col + 1])
        return result


@dataclass(frozen=True)
class ParsedRange:
    sheet: str
    start_col: int
    start_row: int
    end_col: int
    end_row: int


class InMemoryCalcDriver:
    def __init__(self, snapshot: WorkbookSnapshot):
        self.snapshot = snapshot
        self.formats: dict[str, CellFormat] = {}

    def get_sheet_data(self, range_name: str, output: str = "json") -> str:
        if output == "json":
            return self.snapshot.range_to_json(range_name)
        if output == "csv":
            return self.snapshot.range_to_csv(range_name)
        raise ValueError(f"Unsupported output format: {output}")

    def execute_manifest(self, manifest: dict[str, Any]) -> ManifestSummary:
        applied = 0
        errors: list[str] = []
        for action in manifest.get("actions", []):
            action_type = action.get("type")
            try:
                if action_type == "highlight":
                    self._highlight(action)
                elif action_type == "write_value":
                    self._write(action["cell"], action.get("value", ""))
                elif action_type == "formula":
                    self._write(action["cell"], action["formula"])
                else:
                    errors.append(f"Unsupported action type: {action_type}")
                    continue
                applied += 1
            except (KeyError, ValueError, IndexError) as exc:
                errors.append(f"{action_type}: {exc}")
        return ManifestSummary(applied=applied, errors=errors)

    def _highlight(self, action: dict[str, Any]) -> None:
        parsed = _parse_range(action["range"])
        color = str(action.get("color", "#f97316"))
        for row in range(parsed.start_row, parsed.end_row + 1):
            for col in range(parsed.start_col, parsed.end_col + 1):
                self.formats[f"{parsed.sheet}!{_column_name(col)}{row + 1}"] = CellFormat(background=color)

    def _write(self, cell: str, value: Any) -> None:
        parsed = _parse_range(cell)
        self._ensure_cell(parsed.sheet, parsed.start_row, parsed.start_col)
        self.snapshot.sheets[parsed.sheet][parsed.start_row][parsed.start_col] = value

    def _ensure_cell(self, sheet: str, row_index: int, col_index: int) -> None:
        rows = self.snapshot.sheets.setdefault(sheet, [])
        while len(rows) <= row_index:
            rows.append([])
        for row in rows:
            while len(row) <= col_index:
                row.append("")


class VitreusDriver:
    def __init__(self, port: int = 2002):
        self.port = port
        self.doc = self._connect()

    def _connect(self) -> Any:
        try:
            import uno  # type: ignore[import-not-found]
            from unotools import CalcDocument  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "LibreOffice UNO integration requires PyUNO and unotools. "
                "Install LibreOffice SDK packages and start Calc with --accept socket support."
            ) from exc
        raise NotImplementedError("UNO connection wiring is environment-specific; use InMemoryCalcDriver for tests.")


def _parse_range(range_name: str) -> ParsedRange:
    match = CELL_RE.match(range_name)
    if not match:
        raise ValueError(f"Invalid Calc range: {range_name}")
    start_col, start_row = _split_cell(match.group("start"))
    end_cell = match.group("end") or match.group("start")
    end_col, end_row = _split_cell(end_cell)
    return ParsedRange(
        sheet=match.group("sheet"),
        start_col=min(start_col, end_col),
        start_row=min(start_row, end_row),
        end_col=max(start_col, end_col),
        end_row=max(start_row, end_row),
    )


def _split_cell(cell: str) -> tuple[int, int]:
    letters = "".join(char for char in cell if char.isalpha())
    digits = "".join(char for char in cell if char.isdigit())
    return _column_index(letters), int(digits) - 1


def _column_index(letters: str) -> int:
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def _coerce_value(value: str) -> Any:
    if value == "":
        return ""
    try:
        integer = int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value
    return integer
