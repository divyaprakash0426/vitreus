from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


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
