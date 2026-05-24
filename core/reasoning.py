from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GemmaModelChoice:
    primary: str
    drafter: str
    rationale: str

    @classmethod
    def default(cls) -> "GemmaModelChoice":
        return cls(
            primary="gemma4:31b",
            drafter="gemma4:4b",
            rationale=(
                "Gemma 4 31B Dense is the default because Vitreus needs local, "
                "long-context workbook reasoning and stronger multimodal planning; "
                "Gemma 4 4B remains useful as a low-latency drafter on edge hardware."
            ),
        )


class OllamaBackend:
    """Local Gemma 4 inference via Ollama. Requires: uv sync --extra integrations && ollama pull gemma4:31b"""

    def __init__(self, model: str = "gemma4:31b"):
        self.model = model

    def call(self, prompt: str) -> str:
        try:
            from ollama import chat
        except ImportError as exc:
            raise RuntimeError(
                "Ollama integration requires the 'ollama' package.\n"
                "  Install: uv sync --extra integrations\n"
                "  Then pull the model: ollama pull gemma4:31b"
            ) from exc
        response = chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        return response.message.content


class GoogleAIBackend:
    """Gemma 4 via Google AI Studio API. Requires: uv sync --extra integrations + GEMINI_API_KEY."""

    def __init__(self, api_key: str, model: str = "gemma-4-31b-it"):
        self.api_key = api_key
        self.model = model

    def call(self, prompt: str) -> str:
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "Google AI Studio integration requires the 'google-genai' package.\n"
                "  Install: uv sync --extra integrations"
            ) from exc
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(model=self.model, contents=prompt)
        return response.text


class VitreusReasoning:
    def __init__(
        self,
        use_cloud: bool = False,
        model_choice: GemmaModelChoice | None = None,
        backend: Any = None,
    ):
        self.use_cloud = use_cloud
        self.model_choice = model_choice or GemmaModelChoice.default()
        self.backend = backend

    def build_prompt(self, user_query: str, sheet_context: str) -> str:
        model = self.model_choice
        rows = json.loads(sheet_context)
        return (
            f"You are Vitreus, a spreadsheet intelligence agent running {model.primary}.\n"
            f"Analyze the spreadsheet data below and respond with ONLY a valid JSON manifest "
            f"(no markdown, no explanation).\n\n"
            f"Task: {user_query}\n\n"
            f"Sheet data:\n{json.dumps(rows, indent=2)}\n\n"
            f"Required JSON response shape:\n"
            f'{{"model": {{"primary": "{model.primary}", "drafter": "{model.drafter}", "rationale": "..."}}, '
            f'"actions": [{{"type": "highlight|write_value|formula", '
            f'"range": "Sheet1!A1:B2", "cell": "Sheet1!C2", '
            f'"value": "...", "formula": "=SUM(A1:A10)", "color": "#f97316", '
            f'"reason": "why this action is needed"}}]}}'
        )

    async def plan_action(self, user_query: str, sheet_context: str, sheet_name: str = "Scores") -> dict[str, Any]:
        return self.plan_action_sync(user_query, sheet_context, sheet_name=sheet_name)

    def plan_action_sync(self, user_query: str, sheet_context: str, sheet_name: str = "Scores") -> dict[str, Any]:
        if self.backend is not None:
            content = self.backend.call(self.build_prompt(user_query, sheet_context))
            return self.parse_manifest(content)
        return self._fallback_manifest(user_query, json.loads(sheet_context), sheet_name)

    @staticmethod
    def parse_manifest(content: str) -> dict[str, Any]:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
        candidate = fenced.group(1) if fenced else content
        return json.loads(candidate)

    def _fallback_manifest(self, user_query: str, rows: list[dict[str, Any]], sheet_name: str) -> dict[str, Any]:
        query = user_query.lower()
        actions: list[dict[str, Any]] = []
        if "review" in query or "highlight" in query:
            for index, row in enumerate(rows, start=2):
                score = _first_numeric(row, preferred_keys=("Score", "score", "Amount", "amount", "Total", "total"))
                if score is not None and score < 80:
                    last_column = _column_name(max(len(row) - 1, 0))
                    actions.append(
                        {
                            "type": "highlight",
                            "range": f"{sheet_name}!A{index}:{last_column}{index}",
                            "color": "#f97316",
                            "reason": "Score is below the review threshold of 80.",
                        }
                    )
        return {"model": asdict(self.model_choice), "actions": actions}


def _first_numeric(row: dict[str, Any], preferred_keys: tuple[str, ...]) -> float | None:
    for key in preferred_keys:
        value = row.get(key)
        if isinstance(value, int | float):
            return float(value)
    for value in row.values():
        if isinstance(value, int | float):
            return float(value)
    return None


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name
