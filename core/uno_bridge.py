"""JSON-over-stdio bridge for applying Vitreus manifests through PyUNO.

This module is intentionally stdlib-only and importable without PyUNO. The
runtime `uno` import happens inside functions so the project venv can import
the pure helper functions while the bridge script itself runs under a
UNO-capable system Python.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([0-9]+)$")
_RANGE_RE = re.compile(
    r"^(?P<sheet>[^!]+)!(?P<start>\$?[A-Za-z]{1,3}\$?[0-9]+)(?::(?P<end>\$?[A-Za-z]{1,3}\$?[0-9]+))?$"
)
_REF_RE = re.compile(r"(?<![A-Za-z0-9_\"])(\$?)([A-Za-z]{1,3})(\$?)([0-9]+)(?![0-9A-Za-z_(])")


def _json_response(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def _col_index(letters: str) -> int:
    value = 0
    for char in letters.replace("$", "").upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"Invalid column: {letters}")
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _split_cell(cell: str) -> tuple[int, int]:
    match = _CELL_RE.match(str(cell).strip())
    if not match:
        raise ValueError(f"Invalid cell: {cell}")
    return _col_index(match.group(1)), int(match.group(2)) - 1


def _parse_range(ref: str) -> tuple[str, int, int, int, int]:
    match = _RANGE_RE.match(str(ref).strip())
    if not match:
        raise ValueError(f"Invalid Calc range: {ref}")
    start_col, start_row = _split_cell(match.group("start"))
    end_col, end_row = _split_cell(match.group("end") or match.group("start"))
    return (
        match.group("sheet"),
        min(start_col, end_col),
        min(start_row, end_row),
        max(start_col, end_col),
        max(start_row, end_row),
    )


def _parse_sheet_cell(ref: str) -> tuple[str, int, int]:
    sheet, start_col, start_row, end_col, end_row = _parse_range(ref)
    if (start_col, start_row) != (end_col, end_row):
        raise ValueError(f"Expected a single cell, got range: {ref}")
    return sheet, start_col, start_row


def _hex_to_int(color: str) -> int:
    text = str(color).strip()
    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
        raise ValueError(f"Invalid #rrggbb color: {color}")
    return int(text.lstrip("#"), 16)


def _shift_formula(formula: str, row_offset: int) -> str:
    if row_offset == 0:
        return formula

    def repl(match: re.Match[str]) -> str:
        col_abs, col, row_abs, row = match.groups()
        if row_abs:
            return match.group(0)
        return f"{col_abs}{col}{row_abs}{max(int(row) + row_offset, 1)}"

    return _REF_RE.sub(repl, formula)


def _normalize_formula(formula: str) -> str:
    """Calc's Formula API uses ';' between arguments; models often emit Excel-style ','."""
    if not formula.startswith("="):
        return formula
    out: list[str] = []
    in_string = False
    for char in formula:
        if char == '"':
            in_string = not in_string
        elif char == "," and not in_string:
            char = ";"
        out.append(char)
    return "".join(out)


def _fill_formula_for_row(formula: str, row_number: int, first_row_number: int | None = None) -> str:
    if "{row}" in formula:
        return formula.replace("{row}", str(row_number))
    if first_row_number is None:
        return formula
    return _shift_formula(formula, row_number - first_row_number)


def _filter_for(path_or_suffix: str) -> str:
    suffix = str(path_or_suffix).lower()
    if not suffix.startswith("."):
        suffix = Path(suffix).suffix.lower()
    filters = {
        ".xlsx": "Calc MS Excel 2007 XML",
        ".ods": "calc8",
        ".csv": "Text - txt - csv (StarCalc)",
    }
    try:
        return filters[suffix]
    except KeyError as exc:
        raise ValueError(f"Unsupported save extension: {suffix or path_or_suffix}") from exc


def _path_to_url(path: str) -> str:
    return Path(path).expanduser().resolve().as_uri()


def _url_to_path(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return url
    return unquote(parsed.path)


def _convert_value(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if value is None:
        return ""
    return value


def _make_property(uno_module: Any, name: str, value: Any) -> Any:
    prop = uno_module.createUnoStruct("com.sun.star.beans.PropertyValue")
    prop.Name = name
    prop.Value = value
    return prop


def _locale(uno_module: Any) -> Any:
    return uno_module.createUnoStruct("com.sun.star.lang.Locale")


def _rectangle(uno_module: Any, x: int, y: int, width: int, height: int) -> Any:
    rect = uno_module.createUnoStruct("com.sun.star.awt.Rectangle")
    rect.X = int(x)
    rect.Y = int(y)
    rect.Width = int(width)
    rect.Height = int(height)
    return rect


def _is_spreadsheet_doc(component: Any) -> bool:
    return component is not None and hasattr(component, "Sheets")


class UnoBridge:
    def __init__(self, host: str, port: int, open_path: str | None = None):
        import uno

        self.uno = uno
        self.host = host
        self.port = port
        self.desktop = self._connect_desktop()
        self.doc = None
        if open_path:
            self.doc = self._open_document(open_path)

    def _connect_desktop(self) -> Any:
        local_ctx = self.uno.getComponentContext()
        resolver = local_ctx.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local_ctx)
        context = resolver.resolve(f"uno:socket,host={self.host},port={self.port};urp;StarOffice.ComponentContext")
        service_manager = context.ServiceManager
        return service_manager.createInstanceWithContext("com.sun.star.frame.Desktop", context)

    def _open_document(self, path: str) -> Any:
        props = (
            _make_property(self.uno, "Hidden", False),
            _make_property(self.uno, "ReadOnly", False),
        )
        doc = self.desktop.loadComponentFromURL(_path_to_url(path), "_blank", 0, props)
        if not _is_spreadsheet_doc(doc):
            raise RuntimeError(f"Opened document is not a Calc spreadsheet: {path}")
        self.doc = doc
        return doc

    def _current_document(self) -> Any:
        if _is_spreadsheet_doc(self.doc):
            return self.doc
        current = self.desktop.getCurrentComponent()
        if _is_spreadsheet_doc(current):
            self.doc = current
            return current
        components = self.desktop.Components.createEnumeration()
        while components.hasMoreElements():
            component = components.nextElement()
            if _is_spreadsheet_doc(component):
                self.doc = component
                return component
        raise RuntimeError("No Calc document is open")

    def _sheet_names(self) -> list[str]:
        sheets = self._current_document().Sheets
        return [sheets.getElementNames()[i] for i in range(len(sheets.getElementNames()))]

    def ping(self) -> dict[str, Any]:
        doc = self._current_document()
        return {"ok": True, "doc": getattr(doc, "Title", ""), "sheets": self._sheet_names()}

    def snapshot(self) -> dict[str, Any]:
        doc = self._current_document()
        sheets: dict[str, list[list[Any]]] = {}
        for name in doc.Sheets.getElementNames():
            sheet = doc.Sheets.getByName(name)
            cursor = sheet.createCursor()
            cursor.gotoEndOfUsedArea(False)
            end = cursor.RangeAddress
            cell_range = sheet.getCellRangeByPosition(0, 0, end.EndColumn, end.EndRow)
            rows = []
            for row in cell_range.getDataArray():
                rows.append([_convert_value(value) for value in row])
            sheets[name] = rows
        return {"ok": True, "sheets": sheets}

    def save(self, path: str | None = None) -> dict[str, Any]:
        doc = self._current_document()
        if path:
            filter_name = _filter_for(path)
            props = (_make_property(self.uno, "FilterName", filter_name),)
            doc.storeToURL(_path_to_url(path), props)
            return {"ok": True, "path": str(Path(path))}
        if hasattr(doc, "hasLocation") and not doc.hasLocation():
            raise RuntimeError("Cannot save without a path because the document has no location")
        doc.store()
        return {"ok": True, "path": _url_to_path(getattr(doc, "URL", ""))}

    def open(self, path: str) -> dict[str, Any]:
        doc = self._open_document(path)
        return {"ok": True, "doc": getattr(doc, "Title", "")}

    def execute(self, manifest: dict[str, Any]) -> dict[str, Any]:
        actions = manifest.get("actions", []) if isinstance(manifest, dict) else []
        applied = 0
        errors: list[str] = []
        for index, action in enumerate(actions):
            try:
                action_type = action.get("type") if isinstance(action, dict) else None
                handler = getattr(self, f"_action_{action_type}", None)
                if handler is None:
                    raise ValueError(f"Unsupported action type: {action_type}")
                handler(action)
                applied += 1
            except Exception as exc:  # noqa: BLE001 - per-action failures must not abort the manifest.
                errors.append(str(exc) or f"Action {index} failed")
        return {"ok": True, "applied": applied, "errors": errors}

    def _range(self, ref: str) -> tuple[Any, int, int, int, int]:
        sheet_name, start_col, start_row, end_col, end_row = _parse_range(ref)
        sheet = self._current_document().Sheets.getByName(sheet_name)
        cell_range = sheet.getCellRangeByName(ref.split("!", 1)[1].replace("$", ""))
        return cell_range, start_col, start_row, end_col, end_row

    def _cell(self, ref: str) -> Any:
        sheet_name, col, row = _parse_sheet_cell(ref)
        sheet = self._current_document().Sheets.getByName(sheet_name)
        return sheet.getCellByPosition(col, row)

    def _write_cell_value(self, cell: Any, value: Any) -> None:
        if value is None:
            cell.String = ""
        elif isinstance(value, bool):
            cell.Value = 1 if value else 0
        elif isinstance(value, (int, float)):
            cell.Value = value
        elif isinstance(value, str) and value.startswith("="):
            cell.Formula = _normalize_formula(value)
        else:
            cell.String = str(value)

    def _action_highlight(self, action: dict[str, Any]) -> None:
        cell_range, *_ = self._range(action["range"])
        cell_range.CellBackColor = _hex_to_int(action["color"])

    def _action_write_value(self, action: dict[str, Any]) -> None:
        self._write_cell_value(self._cell(action["cell"]), action.get("value"))

    def _action_write_range(self, action: dict[str, Any]) -> None:
        _, start_col, start_row, _, _ = self._range(action["range"])
        values = action.get("values", [])
        sheet_name, *_ = _parse_range(action["range"])
        sheet = self._current_document().Sheets.getByName(sheet_name)
        for row_offset, row_values in enumerate(values):
            for col_offset, value in enumerate(row_values):
                self._write_cell_value(sheet.getCellByPosition(start_col + col_offset, start_row + row_offset), value)

    def _action_formula(self, action: dict[str, Any]) -> None:
        self._cell(action["cell"]).Formula = _normalize_formula(action["formula"])

    def _action_fill_formula(self, action: dict[str, Any]) -> None:
        _, start_col, start_row, end_col, end_row = self._range(action["range"])
        sheet_name, *_ = _parse_range(action["range"])
        sheet = self._current_document().Sheets.getByName(sheet_name)
        first_row_number = start_row + 1
        for row in range(start_row, end_row + 1):
            formula = _normalize_formula(_fill_formula_for_row(action["formula"], row + 1, first_row_number))
            for col in range(start_col, end_col + 1):
                sheet.getCellByPosition(col, row).Formula = formula

    def _action_set_format(self, action: dict[str, Any]) -> None:
        cell_range, *_ = self._range(action["range"])
        if action.get("bold") is not None:
            cell_range.CharWeight = 150.0 if action.get("bold") else 100.0
        if action.get("italic") is not None:
            cell_range.CharPosture = 2 if action.get("italic") else 0
        if action.get("font_color"):
            cell_range.CharColor = _hex_to_int(action["font_color"])
        if action.get("background"):
            cell_range.CellBackColor = _hex_to_int(action["background"])
        if action.get("number_format"):
            doc = self._current_document()
            formats = doc.NumberFormats
            locale = _locale(self.uno)
            key = formats.queryKey(action["number_format"], locale, False)
            if key == -1:
                key = formats.addNew(action["number_format"], locale)
            cell_range.NumberFormat = key

    def _action_set_column_width(self, action: dict[str, Any]) -> None:
        sheet = self._current_document().Sheets.getByName(action["sheet"])
        # Excel character width has no direct UNO equivalent; 200 hundredths-mm
        # per character is a pragmatic approximation used by this bridge.
        sheet.Columns.getByIndex(_col_index(action["column"])).Width = int(float(action["width"]) * 200)

    def _action_freeze_panes(self, action: dict[str, Any]) -> None:
        doc = self._current_document()
        sheet = doc.Sheets.getByName(action["sheet"])
        doc.CurrentController.setActiveSheet(sheet)
        col, row = _split_cell(action["cell"])
        doc.CurrentController.freezeAtPosition(col, row)

    def _action_add_note(self, action: dict[str, Any]) -> None:
        cell = self._cell(action["cell"])
        sheet_name, *_ = _parse_sheet_cell(action["cell"])
        sheet = self._current_document().Sheets.getByName(sheet_name)
        sheet.Annotations.insertNew(cell.CellAddress, action["text"])

    def _action_sort_range(self, action: dict[str, Any]) -> None:
        cell_range, start_col, _, _, _ = self._range(action["range"])
        sort_field = self.uno.createUnoStruct("com.sun.star.table.TableSortField")
        sort_field.Field = _col_index(action["by_column"]) - start_col
        sort_field.IsAscending = not bool(action.get("descending", False))

        descriptor = list(cell_range.createSortDescriptor())
        values = {
            "SortFields": (sort_field,),
            "ContainsHeader": bool(action.get("has_header", True)),
            "IsSortColumns": False,
        }
        seen: set[str] = set()
        for prop in descriptor:
            if prop.Name in values:
                prop.Value = values[prop.Name]
                seen.add(prop.Name)
        for name, value in values.items():
            if name not in seen:
                descriptor.append(_make_property(self.uno, name, value))
        cell_range.sort(tuple(descriptor))

    def _action_insert_rows(self, action: dict[str, Any]) -> None:
        sheet = self._current_document().Sheets.getByName(action["sheet"])
        sheet.Rows.insertByIndex(int(action["at"]) - 1, int(action.get("count", 1)))

    def _action_delete_rows(self, action: dict[str, Any]) -> None:
        sheet = self._current_document().Sheets.getByName(action["sheet"])
        sheet.Rows.removeByIndex(int(action["at"]) - 1, int(action.get("count", 1)))

    def _action_clear_range(self, action: dict[str, Any]) -> None:
        cell_range, *_ = self._range(action["range"])
        cell_range.clearContents(1 + 2 + 4 + 8 + 16)

    def _action_add_sheet(self, action: dict[str, Any]) -> None:
        sheets = self._current_document().Sheets
        if sheets.hasByName(action["name"]):
            raise ValueError(f"Sheet '{action['name']}' already exists")
        sheets.insertNewByName(action["name"], sheets.Count)

    def _action_add_chart(self, action: dict[str, Any]) -> None:
        doc = self._current_document()
        sheet = doc.Sheets.getByName(action["sheet"])
        _, anchor_col, anchor_row = _split_anchor(action["anchor"])
        anchor = sheet.getCellByPosition(anchor_col, anchor_row)
        data_sheet_name, data_start_col, data_start_row, data_end_col, data_end_row = _parse_range(action["data_range"])
        data_sheet = doc.Sheets.getByName(data_sheet_name)
        data_range = data_sheet.getCellRangeByPosition(data_start_col, data_start_row, data_end_col, data_end_row)

        chart_name = self._unique_chart_name(sheet, action.get("title") or f"Vitreus {action['chart_type']} chart")
        position = anchor.Position
        size = anchor.Size
        rect = _rectangle(self.uno, position.X, position.Y, max(size.Width * 8, 12000), max(size.Height * 16, 7000))
        sheet.Charts.addNewByName(chart_name, rect, (data_range.RangeAddress,), True, True)

        chart = sheet.Charts.getByName(chart_name).EmbeddedObject
        diagram_types = {
            "bar": "com.sun.star.chart.BarDiagram",
            "line": "com.sun.star.chart.LineDiagram",
            "pie": "com.sun.star.chart.PieDiagram",
            "scatter": "com.sun.star.chart.XYDiagram",
        }
        chart.Diagram = chart.createInstance(diagram_types[action["chart_type"]])
        if action.get("title"):
            chart.HasMainTitle = True
            chart.Title.String = action["title"]

    def _unique_chart_name(self, sheet: Any, base: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "VitreusChart"
        name = safe
        counter = 1
        while sheet.Charts.hasByName(name):
            counter += 1
            name = f"{safe}_{counter}"
        return name


def _split_anchor(anchor: str) -> tuple[str | None, int, int]:
    if "!" in anchor:
        sheet, col, row = _parse_sheet_cell(anchor)
        return sheet, col, row
    col, row = _split_cell(anchor)
    return None, col, row


def _dispatch(bridge: UnoBridge, payload: dict[str, Any]) -> dict[str, Any]:
    cmd = payload.get("cmd")
    if cmd == "ping":
        return bridge.ping()
    if cmd == "snapshot":
        return bridge.snapshot()
    if cmd == "execute":
        return bridge.execute(payload.get("manifest", {}))
    if cmd == "save":
        return bridge.save(payload.get("path"))
    if cmd == "open":
        path = payload.get("path")
        if not path:
            raise ValueError("open requires a path")
        return bridge.open(path)
    if cmd == "close":
        return {"ok": True}
    raise ValueError(f"Unsupported command: {cmd}")


def _serve(bridge: UnoBridge) -> None:
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            response = _dispatch(bridge, payload)
            _json_response(response)
            if payload.get("cmd") == "close":
                break
        except Exception as exc:  # noqa: BLE001 - protocol errors return JSON and keep serving.
            _json_response({"ok": False, "error": str(exc)})


def _selftest() -> int:
    try:
        import uno  # noqa: F401

        _json_response({"ok": True, "uno": True})
        return 0
    except Exception as exc:  # noqa: BLE001 - discovery needs the import error text.
        _json_response({"ok": False, "uno": False, "error": str(exc)})
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=2002)
    parser.add_argument("--open", dest="open_path")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    try:
        bridge = UnoBridge(args.host, args.port, args.open_path)
    except Exception as exc:  # noqa: BLE001 - startup failures must be machine-readable.
        _json_response({"ok": False, "error": str(exc)})
        return 2

    _serve(bridge)
    time.sleep(0.05)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
