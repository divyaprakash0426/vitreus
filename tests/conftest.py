import pytest


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch):
    """Keep tests offline: no API keys, no Ollama probing, no user config."""
    for key in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "VITREUS_MODEL", "OLLAMA_HOST"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VITREUS_BACKEND", "fallback")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/nonexistent-vitreus-config")
    yield
