"""Manifest v2: the auditable contract between the model and the spreadsheet drivers."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

RANGE_RE = re.compile(r"^(?P<sheet>[^!]+)!(?P<start>\$?[A-Za-z]{1,3}\$?[0-9]+)(?::(?P<end>\$?[A-Za-z]{1,3}\$?[0-9]+))?$")
CELL_ONLY_RE = re.compile(r"^\$?[A-Za-z]{1,3}\$?[0-9]+$")
COLUMN_RE = re.compile(r"^[A-Za-z]{1,3}$")
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def normalize_color(value: str) -> str:
    match = HEX_RE.match(str(value).strip())
    if not match:
        raise ValueError(f"color must be #rrggbb hex, got {value!r}")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return f"#{digits.lower()}"


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ModelInfo(_Base):
    backend: str = "fallback"
    primary: str = "gemma4:31b"
    drafter: str = "gemma4:e4b"
    model: str = ""
    rationale: str = ""


class Highlight(_Base):
    type: Literal["highlight"]
    range: str
    color: str = "#f97316"
    reason: str = ""

    _norm = field_validator("color")(lambda cls, v: normalize_color(v))


class WriteValue(_Base):
    type: Literal["write_value"]
    cell: str
    value: str | int | float | bool | None = None
    reason: str = ""


class WriteRange(_Base):
    type: Literal["write_range"]
    range: str
    values: list[list[Any]]
    reason: str = ""


class Formula(_Base):
    type: Literal["formula"]
    cell: str
    formula: str
    reason: str = ""


class FillFormula(_Base):
    type: Literal["fill_formula"]
    range: str
    formula: str
    reason: str = ""


class SetFormat(_Base):
    type: Literal["set_format"]
    range: str
    bold: bool | None = None
    italic: bool | None = None
    font_color: str | None = None
    background: str | None = None
    number_format: str | None = None
    reason: str = ""

    @field_validator("font_color", "background")
    @classmethod
    def _norm(cls, v: str | None) -> str | None:
        return None if v is None else normalize_color(v)


class SetColumnWidth(_Base):
    type: Literal["set_column_width"]
    sheet: str
    column: str
    width: float
    reason: str = ""


class FreezePanes(_Base):
    type: Literal["freeze_panes"]
    sheet: str
    cell: str
    reason: str = ""


class AddNote(_Base):
    type: Literal["add_note"]
    cell: str
    text: str
    reason: str = ""


class SortRange(_Base):
    type: Literal["sort_range"]
    range: str
    by_column: str
    descending: bool = False
    has_header: bool = True
    reason: str = ""


class InsertRows(_Base):
    type: Literal["insert_rows"]
    sheet: str
    at: int = Field(ge=1)
    count: int = Field(default=1, ge=1)
    reason: str = ""


class DeleteRows(_Base):
    type: Literal["delete_rows"]
    sheet: str
    at: int = Field(ge=1)
    count: int = Field(default=1, ge=1)
    reason: str = ""


class ClearRange(_Base):
    type: Literal["clear_range"]
    range: str
    reason: str = ""


class AddSheet(_Base):
    type: Literal["add_sheet"]
    name: str
    reason: str = ""


class AddChart(_Base):
    type: Literal["add_chart"]
    sheet: str
    chart_type: Literal["bar", "line", "pie", "scatter"]
    data_range: str
    title: str = ""
    anchor: str = "H2"
    reason: str = ""


Action = Annotated[
    Union[
        Highlight,
        WriteValue,
        WriteRange,
        Formula,
        FillFormula,
        SetFormat,
        SetColumnWidth,
        FreezePanes,
        AddNote,
        SortRange,
        InsertRows,
        DeleteRows,
        ClearRange,
        AddSheet,
        AddChart,
    ],
    Field(discriminator="type"),
]

ACTION_TYPES: tuple[str, ...] = (
    "highlight",
    "write_value",
    "write_range",
    "formula",
    "fill_formula",
    "set_format",
    "set_column_width",
    "freeze_panes",
    "add_note",
    "sort_range",
    "insert_rows",
    "delete_rows",
    "clear_range",
    "add_sheet",
    "add_chart",
)


class Manifest(_Base):
    summary: str = ""
    actions: list[Action] = Field(default_factory=list)
    model: ModelInfo | None = None


class ManifestValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


PREFERRED_KEYS = ("actions", "tool", "rows")


def parse_json_object(text: str, prefer_keys: tuple[str, ...] = PREFERRED_KEYS) -> dict[str, Any]:
    """Return the most plausible JSON object in `text`.

    Models may emit reasoning prose (sometimes containing braces) before the real answer, so
    every balanced top-level object is collected and the last one carrying a preferred key
    (`actions`, `tool`, `rows`) wins; otherwise the first object is returned.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        try:
            candidate = json.loads(fenced.group(1))
            if isinstance(candidate, dict) and any(key in candidate for key in prefer_keys):
                return candidate
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    index = 0
    while True:
        index = text.find("{", index)
        if index == -1:
            break
        try:
            obj, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(obj, dict):
            candidates.append(obj)
        index += max(end, 1)
    if not candidates:
        raise ValueError("No JSON object found in model reply")
    for candidate in reversed(candidates):
        if any(key in candidate for key in prefer_keys):
            return candidate
    return candidates[0]


def canonical_ref(ref: str) -> str:
    """Normalise `'My Sheet'!a1:b2` → `My Sheet!A1:B2` (unquote sheet, upper-case cells)."""
    text = str(ref).strip()
    if "!" not in text:
        return text.upper()
    sheet, _, cells = text.rpartition("!")
    return f"{canonical_sheet(sheet)}!{cells.upper()}"


def canonical_sheet(sheet: str) -> str:
    text = str(sheet).strip()
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def _canonicalise_refs(actions: list[Any]) -> None:
    for action in actions:
        if not isinstance(action, dict):
            continue
        for field in ("range", "cell", "data_range", "anchor"):
            if isinstance(action.get(field), str):
                action[field] = canonical_ref(action[field])
        if isinstance(action.get("sheet"), str):
            action["sheet"] = canonical_sheet(action["sheet"])
        for field in ("column", "by_column"):
            if isinstance(action.get(field), str):
                action[field] = action[field].strip().upper()
        if action.get("type") in {"formula", "fill_formula"} and isinstance(action.get("formula"), str):
            action["formula"] = canonical_formula(action["formula"])


def canonical_formula(formula: str) -> str:
    """Ensure a leading '=' and Excel-style ',' argument separators.

    Models often emit Calc-style ';' separators; the xlsx grammar only accepts ','. Separators inside string
    literals and array constants (`{1;2}`) are left alone. The UNO bridge converts back to ';' for Calc.
    """
    text = formula.strip()
    if not text.startswith("="):
        text = "=" + text
    out: list[str] = []
    in_string = False
    depth = 0
    for char in text:
        if char == '"':
            in_string = not in_string
        elif not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(depth - 1, 0)
            elif char == ";" and depth == 0:
                char = ","
        out.append(char)
    return "".join(out)


_FORMULA_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_\"!])"
    r"(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)?"
    r"\$?(?P<col1>[A-Za-z]{1,3})\$?(?P<row1>[0-9]+)"
    r"(?::\$?(?P<col2>[A-Za-z]{1,3})\$?(?P<row2>[0-9]+))?"
    r"(?![0-9A-Za-z_(])"
)


def _column_index(letters: str) -> int:
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - 64)
    return index


def _formula_is_self_referencing(formula: str, sheet: str, col: str, row: int) -> bool:
    """True when `formula` placed at sheet!col+row references that very cell (directly or via a range)."""
    target_col = _column_index(col)
    for index, part in enumerate(formula.split('"')):
        if index % 2:
            continue  # inside a string literal
        for match in _FORMULA_REF_RE.finditer(part):
            ref_sheet = match.group("sheet")
            if ref_sheet is not None and canonical_sheet(ref_sheet) != sheet:
                continue
            c1, r1 = _column_index(match.group("col1")), int(match.group("row1"))
            c2 = _column_index(match.group("col2")) if match.group("col2") else c1
            r2 = int(match.group("row2")) if match.group("row2") else r1
            if min(c1, c2) <= target_col <= max(c1, c2) and min(r1, r2) <= row <= max(r1, r2):
                return True
    return False


def _self_reference_error(action: Any) -> str | None:
    if isinstance(action, Formula):
        match = RANGE_RE.match(action.cell)
        if not match:
            return None
        col, row = re.match(r"\$?([A-Za-z]+)\$?([0-9]+)", match.group("start")).groups()
        if _formula_is_self_referencing(action.formula, match.group("sheet"), col, int(row)):
            return f"formula {action.formula!r} references its own cell {action.cell}; use write_value or reference other cells"
    if isinstance(action, FillFormula):
        match = RANGE_RE.match(action.range)
        if not match:
            return None
        col, row = re.match(r"\$?([A-Za-z]+)\$?([0-9]+)", match.group("start")).groups()
        # The first filled cell stands for the whole range: {row}/{col} placeholders and relative shifts move together.
        first = action.formula.replace("{row}", row).replace("{col}", col.upper())
        if _formula_is_self_referencing(first, match.group("sheet"), col, int(row)):
            return f"formula {action.formula!r} references its own cell within {action.range}; use write_value or reference other cells"
    return None


RISKY_FORMULA_RE = re.compile(r"\b(WEBSERVICE|DDE|HYPERLINK|IMPORTDATA|IMPORTXML|IMPORTHTML|IMPORTRANGE|FILTERXML|ENCODEURL)\s*\(", re.IGNORECASE)


def risky_formulas(manifest: Manifest) -> list[tuple[str, str]]:
    """(target, formula) pairs for formulas that reach outside the workbook (web, DDE, links)."""
    found: list[tuple[str, str]] = []
    for action in manifest.actions:
        target = getattr(action, "cell", None) or getattr(action, "range", "")
        candidates: list[Any] = [getattr(action, "formula", None), getattr(action, "value", None)]
        for row in getattr(action, "values", None) or []:
            candidates.extend(row if isinstance(row, list) else [row])
        for text in candidates:
            # Values starting with '=' are executed as formulas by both drivers.
            if isinstance(text, str) and text.startswith("=") and RISKY_FORMULA_RE.search(text):
                found.append((target, text))
                break
    return found


def _check_ref(ref: str, known: set[str], field: str, prefix: str, errors: list[str]) -> None:
    match = RANGE_RE.match(str(ref))
    if not match:
        errors.append(f"{prefix}: {field} must look like Sheet!A1 or Sheet!A1:B2, got {ref!r}")
        return
    if match.group("sheet") not in known:
        errors.append(f"{prefix}: Unknown sheet: {match.group('sheet')}")


def validate_manifest(raw: dict[str, Any], sheet_names: set[str]) -> Manifest:
    """Validate the raw model JSON against the schema and the workbook's sheet names."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ManifestValidationError(["Manifest must be a JSON object"])
    actions = raw.get("actions", [])
    if not isinstance(actions, list):
        raise ManifestValidationError(["'actions' must be a list"])

    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"actions[{index}]: must be an object")
        elif action.get("type") not in ACTION_TYPES:
            errors.append(f"actions[{index}]: Unsupported action type: {action.get('type')}")
    if errors:
        raise ManifestValidationError(errors)
    _canonicalise_refs(actions)

    try:
        manifest = Manifest.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            loc = err["loc"]
            if loc and loc[0] == "actions" and len(loc) >= 2 and isinstance(loc[1], int):
                field = ".".join(str(part) for part in loc[3:] if part != "type") or "value"
                errors.append(f"actions[{loc[1]}]: {field}: {err['msg']}")
            else:
                errors.append(f"{'.'.join(str(p) for p in loc)}: {err['msg']}")
        raise ManifestValidationError(errors) from exc

    known = set(sheet_names)
    for index, action in enumerate(manifest.actions):
        prefix = f"actions[{index}] ({action.type})"
        if isinstance(action, AddSheet):
            known.add(action.name)
            continue
        if isinstance(action, FreezePanes):
            if not CELL_ONLY_RE.match(action.cell):
                errors.append(f"{prefix}: cell must be a plain cell like A2, got {action.cell!r}")
        else:
            for field in ("range", "cell", "data_range"):
                ref = getattr(action, field, None)
                if ref is not None:
                    _check_ref(ref, known, field, prefix, errors)
        sheet = getattr(action, "sheet", None)
        if sheet is not None and sheet not in known:
            errors.append(f"{prefix}: Unknown sheet: {sheet}")
        if isinstance(action, (SetColumnWidth, SortRange)):
            column = action.column if isinstance(action, SetColumnWidth) else action.by_column
            if not COLUMN_RE.match(column):
                errors.append(f"{prefix}: column must be letters like B, got {column!r}")
        if isinstance(action, AddChart) and not CELL_ONLY_RE.match(action.anchor):
            errors.append(f"{prefix}: anchor must be a plain cell like H2, got {action.anchor!r}")
        circular = _self_reference_error(action)
        if circular:
            errors.append(f"{prefix}: {circular}")
    if errors:
        raise ManifestValidationError(errors)
    return manifest


def manifest_schema_text() -> str:
    return (
        "Reply with exactly ONE JSON object of this shape (no markdown fences, no prose outside it):\n"
        '{"summary": "<1-3 sentences: what you found / did, or the answer to a question>",\n'
        ' "actions": [ ...zero or more actions... ]}\n\n'
        "Every range/cell MUST include the sheet name: \"Sheet1!A2:K2\", \"Sheet1!D7\". Colors are #rrggbb.\n"
        "Row numbers in ranges are the spreadsheet row numbers shown in the data (row 1 is the header when present).\n"
        "Supported actions:\n"
        '  {"type":"highlight","range":"S!A2:K2","color":"#ef4444","reason":"why"}\n'
        '  {"type":"write_value","cell":"S!K3","value":"OVER BUDGET","reason":"why"}\n'
        '  {"type":"write_range","range":"S!L1:L3","values":[["Header"],["v1"],["v2"]]}\n'
        '  {"type":"formula","cell":"S!J12","formula":"=SUM(J2:J11)","reason":"why"}\n'
        '  {"type":"fill_formula","range":"S!L2:L11","formula":"=J{row}-I{row}","reason":"why"}   ({row} = each row number)\n'
        '  {"type":"set_format","range":"S!A1:K1","bold":true,"italic":false,"font_color":"#111111","background":"#e5e7eb","number_format":"#,##0.00"}\n'
        '  {"type":"set_column_width","sheet":"S","column":"A","width":22}\n'
        '  {"type":"freeze_panes","sheet":"S","cell":"A2"}\n'
        '  {"type":"add_note","cell":"S!J3","text":"comment text"}\n'
        '  {"type":"sort_range","range":"S!A1:K11","by_column":"G","descending":true,"has_header":true}\n'
        '  {"type":"insert_rows","sheet":"S","at":2,"count":1}\n'
        '  {"type":"delete_rows","sheet":"S","at":5,"count":2}\n'
        '  {"type":"clear_range","range":"S!K2:K11"}\n'
        '  {"type":"add_sheet","name":"Summary"}\n'
        '  {"type":"add_chart","sheet":"S","chart_type":"bar|line|pie|scatter","data_range":"S!A1:B11","title":"Title","anchor":"M2"}\n'
        "For pure questions return \"actions\": [] and put the answer in \"summary\".\n"
        "Never invent values that are not derivable from the data; if the request is ambiguous, say so in summary and return no actions."
    )
