"""Model backends for Vitreus.

Every backend speaks plain REST through httpx — no vendor SDKs — and exposes the same tiny
surface: `chat(messages, images) -> str` and `list_models() -> list[str]`. The local Ollama
backend is the primary path; hosted Gemma endpoints are optional secondaries.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

import httpx

from core.config import BACKENDS, OPENROUTER_BASE_URL, Settings, detect_backend

Message = dict[str, Any]
DEFAULT_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


class BackendError(RuntimeError):
    """A backend call failed. `hint` tells the user what to do next."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\n  hint: {self.hint}" if self.hint else base


@runtime_checkable
class Backend(Protocol):
    name: str
    model: str

    def chat(self, messages: Sequence[Message], images: Sequence[bytes] | None = None) -> str: ...

    def list_models(self) -> list[str]: ...


def _sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()[:400] or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        if error:
            return str(error)
        if "message" in payload:
            return str(payload["message"])
    return json.dumps(payload)[:400]


def _last_user_index(messages: Sequence[Message]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return len(messages) - 1


# ─── Ollama (local, primary) ─────────────────────────────────────────────────


class OllamaBackend:
    name = "ollama"

    def __init__(self, host: str, model: str, num_ctx: int = 32768, client: httpx.Client | None = None) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT)

    def chat(self, messages: Sequence[Message], images: Sequence[bytes] | None = None) -> str:
        payload_messages = [dict(m) for m in messages]
        if images:
            payload_messages[_last_user_index(payload_messages)]["images"] = [_b64(img) for img in images]
        prompt_chars = sum(len(str(m.get("content", ""))) for m in payload_messages)
        # Ollama defaults to a 4K window; grow it so the workbook context is never silently truncated.
        # Round up to 16K steps: every distinct num_ctx makes Ollama reload the model, which costs
        # tens of seconds for a 31B model, so keep the value stable across agent steps.
        needed = min(prompt_chars // 3 + 2048, 131072)
        num_ctx = max(self.num_ctx, -(-needed // 16384) * 16384)
        body = {
            "model": self.model,
            "messages": payload_messages,
            "stream": False,
            "options": {"num_ctx": num_ctx, "temperature": 0.1},
        }
        try:
            response = self._client.post(f"{self.host}/api/chat", json=body)
        except httpx.ConnectError as exc:
            raise BackendError(
                f"Cannot reach Ollama at {self.host}: {exc}",
                hint="start it with `ollama serve` (or set OLLAMA_HOST / --backend google|openrouter)",
            ) from exc
        except httpx.HTTPError as exc:
            raise BackendError(f"Ollama request failed: {exc}", hint="check `ollama ps` and the server log") from exc
        if response.status_code == 404:
            raise BackendError(
                f"Ollama model '{self.model}' is not installed",
                hint=f"run `ollama pull {self.model}` or pick another with --model / `vitreus models`",
            )
        if response.is_error:
            raise BackendError(f"Ollama returned HTTP {response.status_code}: {_error_message(response)}")
        data = response.json()
        return str((data.get("message") or {}).get("content", ""))

    def list_models(self) -> list[str]:
        try:
            response = self._client.get(f"{self.host}/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(f"Cannot list Ollama models: {exc}", hint="start it with `ollama serve`") from exc
        return [str(m.get("name")) for m in response.json().get("models", []) if m.get("name")]


def ollama_reachable(host: str, timeout: float = 1.0, client: httpx.Client | None = None) -> bool:
    try:
        http = client or httpx.Client(timeout=timeout)
        response = http.get(f"{host.rstrip('/')}/api/tags")
        return response.status_code == 200
    except httpx.HTTPError:
        return False


# ─── Google AI Studio (hosted Gemma, optional) ───────────────────────────────


class GoogleAIBackend:
    name = "google"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT)

    def chat(self, messages: Sequence[Message], images: Sequence[bytes] | None = None) -> str:
        system_parts = [{"text": str(m["content"])} for m in messages if m.get("role") == "system"]
        contents: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                continue
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": str(m.get("content", ""))}]})
        if images and contents:
            target = contents[_last_user_index(contents)]
            for img in images:
                target["parts"].append({"inline_data": {"mime_type": _sniff_mime(img), "data": _b64(img)}})
        body: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": 0.1}}
        if system_parts:
            body["systemInstruction"] = {"parts": system_parts}
        url = f"{self.BASE_URL}/models/{self.model}:generateContent"
        try:
            response = self._client.post(url, headers={"x-goog-api-key": self.api_key}, json=body)
        except httpx.HTTPError as exc:
            raise BackendError(f"Google AI request failed: {exc}", hint="check network access to generativelanguage.googleapis.com") from exc
        if response.is_error:
            raise BackendError(
                f"Google AI returned HTTP {response.status_code}: {_error_message(response)}",
                hint="verify GEMINI_API_KEY and that the model ID exists (`vitreus models --backend google`)",
            )
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise BackendError(f"Google AI returned no candidates: {json.dumps(data)[:300]}", hint="the prompt may have been blocked")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(str(p.get("text", "")) for p in parts)

    def list_models(self) -> list[str]:
        try:
            response = self._client.get(f"{self.BASE_URL}/models", headers={"x-goog-api-key": self.api_key}, params={"pageSize": 200})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(f"Cannot list Google AI models: {exc}", hint="verify GEMINI_API_KEY") from exc
        names = [str(m.get("name", "")).removeprefix("models/") for m in response.json().get("models", [])]
        return [n for n in names if "gemma" in n.lower()]


# ─── OpenAI-compatible (OpenRouter, LM Studio, llama.cpp, vLLM…) ─────────────


class OpenAICompatibleBackend:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        name: str = "openai",
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name
        self.extra_headers = extra_headers or {}
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, messages: Sequence[Message], images: Sequence[bytes] | None = None) -> str:
        payload_messages = [dict(m) for m in messages]
        if images:
            target = payload_messages[_last_user_index(payload_messages)]
            target["content"] = [{"type": "text", "text": str(target.get("content", ""))}] + [
                {"type": "image_url", "image_url": {"url": f"data:{_sniff_mime(img)};base64,{_b64(img)}"}} for img in images
            ]
        body = {"model": self.model, "messages": payload_messages, "temperature": 0.1}
        try:
            response = self._client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise BackendError(f"{self.name} request failed: {exc}", hint=f"check that {self.base_url} is reachable") from exc
        if response.is_error:
            hint = "verify the API key and model ID"
            if self.name == "openrouter":
                hint = "verify OPENROUTER_API_KEY, credits, and the model ID (`vitreus models --backend openrouter`)"
            raise BackendError(f"{self.name} returned HTTP {response.status_code}: {_error_message(response)}", hint=hint)
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise BackendError(f"{self.name} returned no choices: {json.dumps(data)[:300]}")
        content = (choices[0].get("message") or {}).get("content", "")
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        return str(content or "")

    def list_models(self) -> list[str]:
        try:
            response = self._client.get(f"{self.base_url}/models", headers=self._headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(f"Cannot list {self.name} models: {exc}") from exc
        return [str(m.get("id")) for m in response.json().get("data", []) if m.get("id")]


# ─── Fallback ────────────────────────────────────────────────────────────────


class FallbackBackend:
    """Placeholder used when no model is available; the agent switches to rule-based planning."""

    name = "fallback"
    model = "rules"

    def chat(self, messages: Sequence[Message], images: Sequence[bytes] | None = None) -> str:
        raise BackendError(
            "No model backend is available",
            hint="install Ollama and `ollama pull gemma4:31b`, or set GEMINI_API_KEY / OPENROUTER_API_KEY / OPENAI_BASE_URL",
        )

    def list_models(self) -> list[str]:
        return []


# ─── Factory ─────────────────────────────────────────────────────────────────


def make_backend(
    settings: Settings,
    ollama_probe: Callable[[str], bool] | None = None,
    client: httpx.Client | None = None,
) -> tuple[Backend, str]:
    """Build the backend selected by `settings` (or auto-detected). Returns (backend, reason)."""
    if settings.backend not in BACKENDS:
        raise BackendError(f"Unknown backend '{settings.backend}'", hint=f"choose one of: {', '.join(BACKENDS)}")
    probe = ollama_probe or (lambda host: ollama_reachable(host, client=client))
    backend_name, reason = detect_backend(settings, ollama_reachable=probe)
    model = settings.model_for(backend_name)

    if backend_name == "ollama":
        backend: Backend = OllamaBackend(settings.ollama_host, model, settings.ollama_num_ctx, client=client)
        return backend, f"Ollama at {settings.ollama_host} ({reason})"
    if backend_name == "google":
        if not settings.gemini_api_key:
            raise BackendError("Google AI backend selected but no API key configured", hint="export GEMINI_API_KEY=... or set [google].api_key in config")
        return GoogleAIBackend(settings.gemini_api_key, model, client=client), f"Google AI Studio ({reason})"
    if backend_name == "openrouter":
        if not settings.openrouter_api_key:
            raise BackendError("OpenRouter backend selected but no API key configured", hint="export OPENROUTER_API_KEY=... or set [openrouter].api_key in config")
        headers = {"HTTP-Referer": "https://github.com/divyaprakash0426/vitreus", "X-Title": "Vitreus"}
        return (
            OpenAICompatibleBackend(OPENROUTER_BASE_URL, settings.openrouter_api_key, model, name="openrouter", client=client, extra_headers=headers),
            f"OpenRouter ({reason})",
        )
    if backend_name == "openai":
        base_url = settings.openai_base_url or "https://api.openai.com/v1"
        return OpenAICompatibleBackend(base_url, settings.openai_api_key, model, name="openai", client=client), f"OpenAI-compatible at {base_url} ({reason})"
    return FallbackBackend(), f"rule-based fallback planner ({reason})"
