"""Vitreus settings: CLI overrides > environment > config.toml > defaults."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

BACKENDS = ("auto", "ollama", "google", "openrouter", "openai", "fallback")

MODEL_IDS: dict[str, dict[str, str]] = {
    "ollama": {"primary": "gemma4:31b", "drafter": "gemma4:e4b"},
    "google": {"primary": "gemma-4-31b-it", "drafter": "gemma-4-26b-a4b-it"},
    "openrouter": {"primary": "google/gemma-4-31b-it", "drafter": "google/gemma-4-26b-a4b-it"},
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_ENV_MAP: dict[str, tuple[str, type]] = {
    "VITREUS_BACKEND": ("backend", str),
    "VITREUS_MODEL": ("model", str),
    "VITREUS_FAST": ("fast", bool),
    "VITREUS_PRIMARY_MODEL": ("primary", str),
    "VITREUS_DRAFTER_MODEL": ("drafter", str),
    "OLLAMA_HOST": ("ollama_host", str),
    "OLLAMA_NUM_CTX": ("ollama_num_ctx", int),
    "GEMINI_API_KEY": ("gemini_api_key", str),
    "OPENROUTER_API_KEY": ("openrouter_api_key", str),
    "OPENAI_API_KEY": ("openai_api_key", str),
    "OPENAI_BASE_URL": ("openai_base_url", str),
    "OPENAI_MODEL": ("openai_model", str),
    "VITREUS_CONTEXT_TOKENS": ("context_tokens", int),
    "VITREUS_MAX_STEPS": ("max_steps", int),
    "VITREUS_CALC_PORT": ("calc_port", int),
    "VITREUS_UNO_PYTHON": ("uno_python", str),
}

# toml section/key -> Settings field
_TOML_MAP: dict[tuple[str, ...], str] = {
    ("backend",): "backend",
    ("model",): "model",
    ("fast",): "fast",
    ("models", "primary"): "primary",
    ("models", "drafter"): "drafter",
    ("ollama", "host"): "ollama_host",
    ("ollama", "num_ctx"): "ollama_num_ctx",
    ("google", "api_key"): "gemini_api_key",
    ("openrouter", "api_key"): "openrouter_api_key",
    ("openai", "api_key"): "openai_api_key",
    ("openai", "base_url"): "openai_base_url",
    ("openai", "model"): "openai_model",
    ("agent", "context_tokens"): "context_tokens",
    ("agent", "max_steps"): "max_steps",
    ("calc", "port"): "calc_port",
    ("calc", "uno_python"): "uno_python",
}


@dataclass
class Settings:
    backend: str = "auto"
    model: str | None = None
    fast: bool = False
    primary: str = "gemma4:31b"
    drafter: str = "gemma4:e4b"
    ollama_host: str = "http://localhost:11434"
    ollama_num_ctx: int = 32768
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gemma-4-31b-it"
    context_tokens: int = 24000
    max_steps: int = 8
    calc_port: int = 2002
    uno_python: str | None = None

    def model_for(self, backend: str) -> str:
        """Resolve the concrete model ID for a backend, honouring --model and --fast."""
        if self.model:
            return self.model
        if backend == "openai":
            return self.openai_model
        tier = "drafter" if self.fast else "primary"
        if backend == "ollama":
            return self.drafter if self.fast else self.primary
        ids = MODEL_IDS.get(backend)
        if ids is None:
            return self.primary
        return ids[tier]


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "vitreus" / "config.toml"


def _coerce(value: Any, kind: type) -> Any:
    if kind is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if kind is int:
        return int(value)
    return str(value)


def _from_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    result: dict[str, Any] = {}
    for keys, field_name in _TOML_MAP.items():
        node: Any = data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if node is not None:
            result[field_name] = node
    return result


def _from_env(env: Mapping[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for env_key, (field_name, kind) in _ENV_MAP.items():
        raw = env.get(env_key)
        if raw is not None and raw != "":
            result[field_name] = _coerce(raw, kind)
    return result


def load_settings(
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> Settings:
    env = os.environ if env is None else env
    path = config_path or default_config_path()
    merged: dict[str, Any] = {}
    merged.update(_from_toml(path))
    merged.update(_from_env(env))
    merged.update({k: v for k, v in (overrides or {}).items() if v is not None})
    valid = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in merged.items() if k in valid})


def detect_backend(settings: Settings, ollama_reachable: Callable[[str], bool]) -> tuple[str, str]:
    """Resolve `auto` to a concrete backend. Local Ollama always wins when reachable."""
    if settings.backend != "auto":
        return settings.backend, "explicitly selected"
    if ollama_reachable(settings.ollama_host):
        return "ollama", f"local Ollama reachable at {settings.ollama_host}"
    if settings.gemini_api_key:
        return "google", "GEMINI_API_KEY present"
    if settings.openrouter_api_key:
        return "openrouter", "OPENROUTER_API_KEY present"
    if settings.openai_base_url or settings.openai_api_key:
        return "openai", "OPENAI_BASE_URL/OPENAI_API_KEY present"
    return "fallback", (
        f"no Ollama at {settings.ollama_host} and no API key configured; using deterministic fallback planner"
    )


def config_template() -> str:
    return (
        "# Vitreus configuration (~/.config/vitreus/config.toml)\n"
        '# backend: auto | ollama | google | openrouter | openai | fallback\n'
        'backend = "auto"\n'
        "# model = \"gemma4:26b\"   # explicit override for the chosen backend\n"
        "fast = false            # use the drafter model\n\n"
        "[models]\n"
        'primary = "gemma4:31b"\n'
        'drafter = "gemma4:e4b"\n\n'
        "[ollama]\n"
        'host = "http://localhost:11434"\n'
        "num_ctx = 32768\n\n"
        "[google]\n"
        '# api_key = "..."        # or GEMINI_API_KEY\n\n'
        "[openrouter]\n"
        '# api_key = "..."        # or OPENROUTER_API_KEY\n\n'
        "[openai]\n"
        '# base_url = "http://localhost:1234/v1"   # LM Studio / llama.cpp / vLLM / any OpenAI-compatible server\n'
        '# api_key = "..."\n'
        'model = "gemma-4-31b-it"\n\n'
        "[agent]\n"
        "context_tokens = 24000\n"
        "max_steps = 8\n\n"
        "[calc]\n"
        "port = 2002\n"
        '# uno_python = "/usr/bin/python3"   # Python that can `import uno`\n'
    )
