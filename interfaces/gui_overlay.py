from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverlayMessage:
    title: str
    body: str
    severity: str = "info"


class GuiOverlay:
    """Small seam for a future transparent LibreOffice HUD."""

    def render(self, message: OverlayMessage) -> str:
        return f"[{message.severity.upper()}] {message.title}: {message.body}"
