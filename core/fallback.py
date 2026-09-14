"""Deterministic rule-based planner used when no model backend is available.

It only handles a handful of common bookkeeping requests and is honest about everything
else: unknown asks return an empty manifest with a clear summary instead of guesses.
"""

from __future__ import annotations

import re
from typing import Any

from core.driver import WorkbookSnapshot, column_name, parse_number

REVIEW_COLOR = "#f97316"
REVIEW_THRESHOLD = 80.0
_COMPARISON = re.compile(
    r"(?P<left>[A-Za-z_][\w ]*?)\s+(?:is\s+)?(?P<op>exceeds?|over|above|greater than|more than|higher than|>|below|under|less than|lower than|<)\s+"
    r"(?P<right>\d[\d,]*(?:\.\d+)?\s*(?:[kKmMgGtT][bB]?|%)?|[A-Za-z_][\w ]*?)(?=[\s,.;]|$)",
    re.IGNORECASE,
)
_WRITE = re.compile(r"""write\s+["']?(?P<value>[^"']+?)["']?\s+(?:in|to|into)\s+(?:the\s+)?(?P<column>[A-Za-z_][\w ]*?)(?:\s+column)?(?=[\s,.;]|$)""", re.IGNORECASE)
_UNIT_MULTIPLIER = {
    "k": 1_000,
    "m": 1_000_000,
    "g": 1_000_000_000,
    "t": 1_000_000_000_000,
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "tb": 1024**4,
    "%": 1,
    "": 1,
}
_BELOW_OPS = {"below", "under", "less than", "lower than", "<"}
# Column names that "files/rows/items over N" most plausibly refer to when the left word is not a header.
_SIZE_LIKE = ("size", "bytes", "amount", "total", "value", "count")


def _parse_threshold(text: str) -> float | None:
    """'1 MB' → 1048576, '1.5k' → 1500, '10%' → 10, '100' → 100; None if not numeric."""
    match = re.fullmatch(r"\s*(\d[\d,]*(?:\.\d+)?)\s*([A-Za-z%]*)\s*", text)
    if not match:
        return None
    unit = match.group(2).lower()
    if unit not in _UNIT_MULTIPLIER:
        return None
    return float(match.group(1).replace(",", "")) * _UNIT_MULTIPLIER[unit]


def _header_lookup(header: list[Any]) -> dict[str, int]:
    return {str(name).strip().lower(): idx for idx, name in enumerate(header) if str(name).strip()}


def _match_column(name: str, lookup: dict[str, int]) -> int | None:
    key = name.strip().lower()
    if key in lookup:
        return lookup[key]
    key = key.replace(" ", "_")
    if key in lookup:
        return lookup[key]
    for col, idx in lookup.items():
        if col.replace("_", " ") == name.strip().lower():
            return idx
    return None


def _number(value: Any) -> float | None:
    return parse_number(value)


def plan_fallback(query: str, snapshot: WorkbookSnapshot, sheet: str) -> dict[str, Any]:
    rows = snapshot.sheets.get(sheet) or []
    if not rows:
        return {"summary": "Fallback planner: the sheet is empty, nothing to do (no model backend available).", "actions": []}
    header, body = list(rows[0]), rows[1:]
    lookup = _header_lookup(header)
    width = max((len(r) for r in rows), default=1)
    last_col = column_name(max(width - 1, 0))
    q = query.lower()

    comparison = _COMPARISON.search(query)
    if comparison:
        below = comparison.group("op").lower() in _BELOW_OPS
        verb = "is below" if below else "exceeds"
        left_idx = _match_column(comparison.group("left").split()[-1], lookup)
        right_text = comparison.group("right").strip()
        threshold = _parse_threshold(right_text)
        right_idx = None if threshold is not None else _match_column(right_text.split()[0], lookup)
        if left_idx is None and threshold is not None:
            # "files over 1 MB": no header named 'files' → fall back to the first size-like numeric column.
            left_idx = next((lookup[k] for k in _SIZE_LIKE if k in lookup), None)
        if left_idx is not None and (right_idx is not None or threshold is not None):
            left_name = header[left_idx]
            right_name = header[right_idx] if right_idx is not None else right_text
            write = _WRITE.search(query)
            write_idx = _match_column(write.group("column"), lookup) if write else None
            actions: list[dict[str, Any]] = []
            for row_no, row in enumerate(body, start=2):
                left = _number(row[left_idx]) if left_idx < len(row) else None
                if right_idx is not None:
                    right = _number(row[right_idx]) if right_idx < len(row) else None
                else:
                    right = threshold
                if left is None or right is None or (left >= right if below else left <= right):
                    continue
                right_shown = f"{right_name} ({right:g})" if right_idx is not None else right_name
                actions.append(
                    {
                        "type": "highlight",
                        "range": f"{sheet}!A{row_no}:{last_col}{row_no}",
                        "color": REVIEW_COLOR,
                        "reason": f"{left_name} ({left:g}) {verb} {right_shown}.",
                    }
                )
                if write and write_idx is not None:
                    actions.append({"type": "write_value", "cell": f"{sheet}!{column_name(write_idx)}{row_no}", "value": write.group("value").strip()})
            return {
                "summary": f"Fallback planner (no model backend): {len([a for a in actions if a['type'] == 'highlight'])} row(s) where {left_name} {verb} {right_name}.",
                "actions": actions,
            }

    if "review" in q or "highlight" in q:
        preferred = ("score", "amount", "total")
        idx = next((lookup[k] for k in preferred if k in lookup), None)
        actions = []
        for row_no, row in enumerate(body, start=2):
            value = _number(row[idx]) if idx is not None and idx < len(row) else next((n for n in (_number(v) for v in row) if n is not None), None)
            if value is not None and value < REVIEW_THRESHOLD:
                actions.append(
                    {
                        "type": "highlight",
                        "range": f"{sheet}!A{row_no}:{last_col}{row_no}",
                        "color": REVIEW_COLOR,
                        "reason": f"Score is below the review threshold of {REVIEW_THRESHOLD:g}.",
                    }
                )
        return {"summary": f"Fallback planner (no model backend): highlighted {len(actions)} row(s) below {REVIEW_THRESHOLD:g}.", "actions": actions}

    return {
        "summary": (
            "No model backend is available and the fallback planner has no rule for this request. "
            "Install Ollama (`ollama pull gemma4:31b`) or set GEMINI_API_KEY / OPENROUTER_API_KEY to enable Gemma reasoning."
        ),
        "actions": [],
    }
