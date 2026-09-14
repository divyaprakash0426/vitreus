"""Compatibility layer over `core.agent` for the original Vitreus API.

New code should use `core.backends.make_backend` + `core.agent.SpreadsheetAgent` directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core import backends as _backends
from core.agent import SpreadsheetAgent
from core.config import MODEL_IDS, Settings
from core.driver import WorkbookSnapshot
from core.manifest import parse_json_object


@dataclass(frozen=True)
class GemmaModelChoice:
    primary: str
    drafter: str
    rationale: str

    @classmethod
    def default(cls) -> GemmaModelChoice:
        return cls(
            primary="gemma4:31b",
            drafter="gemma4:e4b",
            rationale=(
                "Gemma 4 31B Dense is the default because Vitreus needs local, "
                "long-context workbook reasoning and stronger multimodal planning; "
                "Gemma 4 E4B remains useful as a low-latency drafter on edge hardware."
            ),
        )


class _LegacyCallMixin:
    """Adds the old single-prompt `.call()` entry point on top of the REST backends."""

    def call(self, prompt: str) -> str:
        return self.chat([{"role": "user", "content": prompt}])  # type: ignore[attr-defined]


class OllamaBackend(_LegacyCallMixin, _backends.OllamaBackend):
    def __init__(self, model: str = "gemma4:31b", host: str = "http://localhost:11434", **kwargs: Any) -> None:
        super().__init__(host=host, model=model, **kwargs)


class GoogleAIBackend(_LegacyCallMixin, _backends.GoogleAIBackend):
    def __init__(self, api_key: str, model: str = MODEL_IDS["google"]["primary"], **kwargs: Any) -> None:
        super().__init__(api_key=api_key, model=model, **kwargs)


def _snapshot_from_rows(rows: list[dict[str, Any]], sheet_name: str) -> WorkbookSnapshot:
    if not rows:
        return WorkbookSnapshot(sheets={sheet_name: []})
    header = list(rows[0].keys())
    return WorkbookSnapshot(sheets={sheet_name: [header] + [[row.get(k) for k in header] for row in rows]})


class _CallAdapter:
    """Wraps an object exposing only `.call(prompt)` into the Backend protocol."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.name = getattr(inner, "name", "custom")
        self.model = getattr(inner, "model", "custom")

    def chat(self, messages: list[dict[str, Any]], images: list[bytes] | None = None) -> str:
        prompt = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)
        return str(self._inner.call(prompt))

    def list_models(self) -> list[str]:
        return []


class VitreusReasoning:
    def __init__(self, use_cloud: bool = False, model_choice: GemmaModelChoice | None = None, backend: Any = None) -> None:
        self.use_cloud = use_cloud
        self.model_choice = model_choice or GemmaModelChoice.default()
        self.backend = backend

    def build_prompt(self, user_query: str, sheet_context: str) -> str:
        model = self.model_choice
        rows = json.loads(sheet_context)
        return (
            f"You are Vitreus, a spreadsheet intelligence agent running {model.primary}.\n"
            "Analyze the spreadsheet data below and respond with ONLY a valid JSON manifest.\n\n"
            f"Task: {user_query}\n\nSheet data:\n{json.dumps(rows, indent=2)}\n"
        )

    async def plan_action(self, user_query: str, sheet_context: str, sheet_name: str = "Scores") -> dict[str, Any]:
        return self.plan_action_sync(user_query, sheet_context, sheet_name=sheet_name)

    def plan_action_sync(self, user_query: str, sheet_context: str, sheet_name: str = "Scores") -> dict[str, Any]:
        snapshot = _snapshot_from_rows(json.loads(sheet_context), sheet_name)
        backend = self.backend if self.backend is not None else _backends.FallbackBackend()
        if hasattr(backend, "call"):
            backend = _CallAdapter(backend)
        settings = Settings(backend=getattr(backend, "name", "fallback"), primary=self.model_choice.primary, drafter=self.model_choice.drafter)
        result = SpreadsheetAgent(backend, settings, snapshot).run(user_query)
        manifest = result.manifest.model_dump(mode="json", exclude_none=True)
        manifest["model"] = {**manifest.get("model", {}), "primary": self.model_choice.primary, "drafter": self.model_choice.drafter}
        return manifest

    @staticmethod
    def parse_manifest(content: str) -> dict[str, Any]:
        return parse_json_object(content)
