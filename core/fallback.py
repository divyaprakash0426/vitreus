"""Deterministic rule-based planner used when no model backend is available.

It only handles a handful of common bookkeeping requests and is honest about everything
else: unknown asks return an empty manifest with a clear summary instead of guesses.
"""

from __future__ import annotations

import re
from typing import Any

from core.driver import WorkbookSnapshot, coerce_value, column_name

REVIEW_COLOR = "#f97316"
REVIEW_THRESHOLD = 80.0
_COMPARISON = re.compile(
    r"(?P<left>[A-Za-z_][\w ]*?)\s+(?:is\s+)?(?:exceeds?|over|above|greater than|more than|higher than|>)\s+(?P<right>[A-Za-z_][\w ]*?)(?=[\s,.;]|$)",
    re.IGNORECASE,
)
_WRITE = re.compile(r"""write\s+["']?(?P<value>[^"']+?)["']?\s+(?:in|to|into)\s+(?:the\s+)?(?P<column>[A-Za-z_][\w ]*?)(?:\s+column)?(?=[\s,.;]|$)""", re.IGNORECASE)


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
    coerced = coerce_value(value)
    if isinstance(coerced, bool):
        return None
    if isinstance(coerced, int | float):
        return float(coerced)
    return None


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
        left_idx = _match_column(comparison.group("left").split()[-1], lookup)
        right_idx = _match_column(comparison.group("right").split()[0], lookup)
        if left_idx is not None and right_idx is not None:
            left_name, right_name = header[left_idx], header[right_idx]
            write = _WRITE.search(query)
            write_idx = _match_column(write.group("column"), lookup) if write else None
            actions: list[dict[str, Any]] = []
            for row_no, row in enumerate(body, start=2):
                left = _number(row[left_idx]) if left_idx < len(row) else None
                right = _number(row[right_idx]) if right_idx < len(row) else None
                if left is None or right is None or left <= right:
                    continue
                actions.append(
                    {
                        "type": "highlight",
                        "range": f"{sheet}!A{row_no}:{last_col}{row_no}",
                        "color": REVIEW_COLOR,
                        "reason": f"{left_name} ({left:g}) exceeds {right_name} ({right:g}).",
                    }
                )
                if write and write_idx is not None:
                    actions.append({"type": "write_value", "cell": f"{sheet}!{column_name(write_idx)}{row_no}", "value": write.group("value").strip()})
            return {
                "summary": f"Fallback planner (no model backend): {len([a for a in actions if a['type'] == 'highlight'])} row(s) where {left_name} exceeds {right_name}.",
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
