"""Tool-augmented planning loop: workbook context → Gemma → validated manifest.

The protocol is prompt-level and model-agnostic. Each model turn is either a tool call
`{"tool": name, "args": {...}}` — answered with an observation — or a final manifest
`{"summary": ..., "actions": [...]}` which is validated before being returned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.backends import Backend, FallbackBackend, Message
from core.config import Settings
from core.context import build_context, describe_sheet, sheet_rows_csv
from core.driver import WorkbookSnapshot, column_name, parse_range
from core.fallback import plan_fallback
from core.manifest import Manifest, ManifestValidationError, ModelInfo, manifest_schema_text, parse_json_object, validate_manifest

TOOLS = {"list_sheets", "describe_sheet", "get_range", "find"}
MAX_VALIDATION_RETRIES = 2
OBSERVATION_LIMIT = 12000

SYSTEM_PROMPT = f"""You are Vitreus, a local-first spreadsheet intelligence agent. You inspect workbook data and return an auditable JSON action manifest that a driver applies to LibreOffice Calc or an .xlsx/.csv file. You never edit cells yourself; you only propose actions.

Rules:
- Reply with exactly ONE JSON object and nothing else (no prose, no markdown fences).
- Cell and range references are always sheet-qualified A1 notation: "Sheet1!A2", "Sales!B2:D10". Row 1 is the header row unless the data says otherwise.
- Every highlight and every non-obvious formula needs a short "reason".
- Only reference sheets that exist (or that you create earlier in the same manifest with add_sheet).
- Never fabricate values. If the request cannot be answered from the data, return {{"summary": "<why>", "actions": []}}.
- Formulas use LibreOffice/Excel syntax with ";" or "," separators, e.g. "=SUM(B2:B10)", "=IF(C2>B2;\\"over\\";\\"ok\\")".
- Prefer fill_formula with {{row}} placeholders for per-row formulas over many single formula actions.

When you need more data than the context shows, call a tool by replying with ONLY:
{{"tool": "<name>", "args": {{...}}}}
Available tools:
- list_sheets: {{}} → sheet names and dimensions
- describe_sheet: {{"sheet": "Name"}} → per-column type, min/max/mean, samples
- get_range: {{"range": "Sheet!A1:D50"}} → CSV of that range (keep it under ~200 rows)
- find: {{"text": "needle", "sheet": "optional"}} → cells whose value contains the text

When you are ready, reply with ONLY the final manifest:
{manifest_schema_text()}
"""


class AgentError(RuntimeError):
    pass


@dataclass
class AgentResult:
    manifest: Manifest
    steps: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw_replies: list[str] = field(default_factory=list)


class SpreadsheetAgent:
    def __init__(
        self,
        backend: Backend,
        settings: Settings,
        snapshot: WorkbookSnapshot,
        source_name: str = "",
        focus_sheets: list[str] | None = None,
    ) -> None:
        self.backend = backend
        self.settings = settings
        self.snapshot = snapshot
        self.source_name = source_name or snapshot.source or "workbook"
        # Sheets rendered in the context; tools can still reach every sheet in the snapshot.
        self.focus_sheets = focus_sheets
        self.messages: list[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._context_sent = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def refresh(self, snapshot: WorkbookSnapshot) -> None:
        """Swap in a new snapshot (e.g. after applying a manifest); the next turn resends context."""
        self.snapshot = snapshot
        self._context_sent = False

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._context_sent = False

    # ── main loop ────────────────────────────────────────────────────────

    def run(self, query: str, images: list[bytes] | None = None) -> AgentResult:
        if isinstance(self.backend, FallbackBackend):
            return self._run_fallback(query)

        self.messages.append({"role": "user", "content": self._user_turn(query)})
        tool_calls: list[dict[str, Any]] = []
        raw_replies: list[str] = []
        validation_failures = 0
        pending_images: list[bytes] | None = list(images) if images else None
        steps = 0

        while steps < self.settings.max_steps:
            steps += 1
            reply = self.backend.chat(self.messages, images=pending_images)
            pending_images = None
            raw_replies.append(reply)
            self.messages.append({"role": "assistant", "content": reply})

            try:
                payload = parse_json_object(reply)
            except ValueError:
                validation_failures += 1
                if validation_failures > MAX_VALIDATION_RETRIES:
                    raise AgentError(f"Model did not return a valid manifest after {steps} steps. Last reply:\n{reply[:800]}")
                self.messages.append({"role": "user", "content": "Your reply did not contain a JSON object. Reply with ONLY one JSON object: either a tool call or the final manifest."})
                continue

            if "tool" in payload and "actions" not in payload:
                call = {"tool": str(payload.get("tool")), "args": dict(payload.get("args") or {})}
                tool_calls.append(call)
                observation = self._call_tool(call["tool"], call["args"])
                self.messages.append({"role": "user", "content": f"Observation from {call['tool']}:\n{observation}\n\nContinue: call another tool or reply with the final manifest."})
                continue

            try:
                manifest = validate_manifest(payload, self.snapshot.sheet_names)
            except ManifestValidationError as exc:
                validation_failures += 1
                if validation_failures > MAX_VALIDATION_RETRIES:
                    raise AgentError(f"Model did not return a valid manifest after {steps} steps: {'; '.join(exc.errors)}") from exc
                bullet = "\n".join(f"- {e}" for e in exc.errors)
                self.messages.append({"role": "user", "content": f"The manifest is invalid:\n{bullet}\n\nFix these problems and reply with ONLY the corrected manifest JSON."})
                continue

            manifest.model = self._model_info()
            return AgentResult(manifest=manifest, steps=steps, tool_calls=tool_calls, raw_replies=raw_replies)

        raise AgentError(f"Agent exceeded {self.settings.max_steps} steps without producing a manifest")

    # ── helpers ──────────────────────────────────────────────────────────

    def _run_fallback(self, query: str) -> AgentResult:
        sheet = self.snapshot.sheet_names[0] if self.snapshot.sheet_names else "Sheet1"
        raw = plan_fallback(query, self.snapshot, sheet)
        manifest = validate_manifest(raw, self.snapshot.sheet_names)
        manifest.model = self._model_info(rationale="No model backend available; deterministic rule-based planner.")
        self.messages.append({"role": "user", "content": query})
        self.messages.append({"role": "assistant", "content": json.dumps(raw)})
        return AgentResult(manifest=manifest, steps=0)

    def _model_info(self, rationale: str | None = None) -> ModelInfo:
        return ModelInfo(
            backend=self.backend.name,
            primary=self.settings.primary,
            drafter=self.settings.drafter,
            model=self.backend.model,
            rationale=rationale
            or (
                "Gemma 4 31B Dense is the default for long-context workbook reasoning; "
                f"this run used {self.backend.model} via {self.backend.name}."
            ),
        )

    def _user_turn(self, query: str) -> str:
        if self._context_sent:
            return f"Request: {query}"
        self._context_sent = True
        sheets = [s for s in (self.focus_sheets or []) if s in self.snapshot.sheets] or None
        context = build_context(self.snapshot, budget_tokens=self.settings.context_tokens, sheets=sheets, source_name=self.source_name)
        return f"{context}\n\nRequest: {query}"

    def _call_tool(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "list_sheets":
                return json.dumps([{"sheet": s, "rows": self.snapshot.dims(s)[0], "cols": self.snapshot.dims(s)[1], "data_range": self.snapshot.data_range(s)} for s in self.snapshot.sheet_names])
            if name == "describe_sheet":
                sheet = self._sheet_arg(args)
                return json.dumps(describe_sheet(self.snapshot, sheet), default=str)
            if name == "get_range":
                rng = str(args.get("range") or "")
                if "!" not in rng:
                    rng = f"{self.snapshot.sheet_names[0]}!{rng}"
                parsed = parse_range(rng)
                if parsed.sheet not in self.snapshot.sheets:
                    return f"error: Unknown sheet: {parsed.sheet}. Sheets: {', '.join(self.snapshot.sheet_names)}"
                if parsed.end_row - parsed.start_row > 500:
                    return "error: range too large; request at most 500 rows at a time"
                return self._truncate(f"CSV for {rng}:\n" + self.snapshot.range_to_csv(rng))
            if name == "find":
                return self._find(str(args.get("text") or ""), args.get("sheet"))
        except (KeyError, ValueError, IndexError) as exc:
            return f"error: {exc}"
        return f"error: unknown tool '{name}'. Available tools: {', '.join(sorted(TOOLS))}"

    def _sheet_arg(self, args: dict[str, Any]) -> str:
        sheet = str(args.get("sheet") or (self.snapshot.sheet_names[0] if self.snapshot.sheet_names else ""))
        if sheet not in self.snapshot.sheets:
            raise ValueError(f"Unknown sheet: {sheet}. Sheets: {', '.join(self.snapshot.sheet_names)}")
        return sheet

    def _find(self, needle: str, sheet: str | None) -> str:
        if not needle:
            return "error: find requires a non-empty 'text'"
        needle_l = needle.lower()
        hits: list[str] = []
        for name in [sheet] if sheet else self.snapshot.sheet_names:
            if name not in self.snapshot.sheets:
                return f"error: Unknown sheet: {name}"
            for r, row in enumerate(self.snapshot.sheets[name], start=1):
                for c, value in enumerate(row):
                    if value is not None and needle_l in str(value).lower():
                        hits.append(f"{name}!{column_name(c)}{r} = {value!r}")
                        if len(hits) >= 100:
                            return "\n".join(hits) + "\n(…truncated at 100 hits)"
        return "\n".join(hits) if hits else f"no cells contain {needle!r}"

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= OBSERVATION_LIMIT:
            return text
        return text[:OBSERVATION_LIMIT] + "\n…(truncated; request a smaller range)"


__all__ = ["SYSTEM_PROMPT", "TOOLS", "AgentError", "AgentResult", "SpreadsheetAgent", "sheet_rows_csv"]
