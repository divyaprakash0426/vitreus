"""Multimodal helpers: turn receipts, charts and table photos into spreadsheet rows via Gemma."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from core.backends import Backend
from core.manifest import parse_json_object

PURPOSES = ("receipt", "chart", "table")


class VisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisionInput:
    path: Path
    purpose: str
    format: str
    width: int
    height: int
    mode: str

    @classmethod
    def from_file(cls, path: str | Path, purpose: str = "chart") -> "VisionInput":
        image_path = Path(path)
        with Image.open(image_path) as image:
            return cls(
                path=image_path,
                purpose=purpose,
                format=image.format or "UNKNOWN",
                width=image.width,
                height=image.height,
                mode=image.mode,
            )

    def to_prompt_payload(self) -> dict[str, str | int]:
        return {
            "path": str(self.path),
            "purpose": self.purpose,
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "mode": self.mode,
            "instruction": _instruction_for(self.purpose),
        }


def _instruction_for(purpose: str) -> str:
    if purpose == "receipt":
        return "Extract merchant, date, line items, totals, and tax fields as spreadsheet-ready JSON."
    if purpose == "chart":
        return "Explain chart type, visible trends, outliers, and spreadsheet cells likely driving the visual."
    return "Describe the image and return spreadsheet-ready structured observations."


def encode_image(path: str | Path, max_side: int = 1600) -> tuple[bytes, str]:
    """Return (bytes, mime). Large images are downscaled to `max_side`; PNGs stay PNG
    (transparency, screenshots), everything else is re-encoded as JPEG."""
    with Image.open(path) as image:
        original_format = (image.format or "").upper()
        img = image.copy()
    if max(img.size) > max_side:
        scale = max_side / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    buffer = io.BytesIO()
    if original_format == "PNG" or img.mode in {"RGBA", "LA", "P"}:
        img.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), "image/png"
    img.convert("RGB").save(buffer, format="JPEG", quality=88)
    return buffer.getvalue(), "image/jpeg"


def extraction_prompt(purpose: str) -> str:
    purpose = purpose if purpose in PURPOSES else "table"
    focus = {
        "receipt": (
            "This is a receipt or invoice. Produce one row per line item with columns like "
            "Item, Qty, Unit_Price, Total, plus trailing rows for Subtotal, Tax and Total. "
            "Add Merchant and Date as the first rows if visible."
        ),
        "chart": (
            "This is a chart. Reconstruct the underlying data table as accurately as the axes allow: "
            "one header row (category/series names) followed by one row per data point. Note approximations in the summary."
        ),
        "table": "This is a photographed or screenshotted table. Transcribe it faithfully, one header row followed by data rows.",
    }[purpose]
    return (
        f"{focus}\n\n"
        "Reply with exactly ONE JSON object and nothing else:\n"
        '{"sheet_name": "<short sheet name>", "summary": "<one sentence>", "rows": [["Header1", "Header2"], ["value", 1.23]]}\n'
        "Rules: numbers as JSON numbers (no currency symbols), dates as ISO strings, unknown cells as null. Never invent values that are not visible."
    )


def _normalise_rows(rows: Any) -> list[list[Any]]:
    if not isinstance(rows, list) or not rows:
        raise VisionError("Model reply has no 'rows' table")
    if all(isinstance(r, dict) for r in rows):
        header: list[str] = []
        for r in rows:
            header.extend(k for k in r.keys() if k not in header)
        return [header] + [[r.get(k) for k in header] for r in rows]
    if not all(isinstance(r, list) for r in rows):
        raise VisionError("Model reply 'rows' must be a list of lists")
    width = max(len(r) for r in rows)
    return [list(r) + [None] * (width - len(r)) for r in rows]


def extract_table(backend: Backend, image_path: str | Path, purpose: str = "receipt") -> dict[str, Any]:
    """Ask the model to transcribe an image into rows. Returns {"sheet_name", "summary", "rows"}."""
    data, _mime = encode_image(image_path)
    messages = [
        {"role": "system", "content": "You are Vitreus, a spreadsheet intelligence agent. You transcribe images into precise tabular data."},
        {"role": "user", "content": extraction_prompt(purpose)},
    ]
    reply = backend.chat(messages, images=[data])
    try:
        payload = parse_json_object(reply)
    except ValueError as exc:
        raise VisionError(f"Model did not return JSON for the image: {reply[:300]}") from exc
    rows = _normalise_rows(payload.get("rows"))
    sheet_name = str(payload.get("sheet_name") or purpose.capitalize())[:31] or purpose.capitalize()
    return {"sheet_name": sheet_name, "summary": str(payload.get("summary") or ""), "rows": rows}
