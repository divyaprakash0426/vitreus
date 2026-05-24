"""TDD tests for OllamaBackend and GoogleAIBackend before implementation."""
import json
import sys
import types as stdlib_types

import pytest


MANIFEST_JSON = json.dumps({
    "model": {"primary": "gemma4:31b", "drafter": "gemma4:4b", "rationale": "test"},
    "actions": [{"type": "highlight", "range": "Sheet1!A2:B2", "color": "#f97316", "reason": "test"}],
})


def _fake_ollama_module(content: str) -> stdlib_types.ModuleType:
    class _Msg:
        pass

    class _Resp:
        pass

    msg = _Msg()
    msg.content = content
    resp = _Resp()
    resp.message = msg
    mod = stdlib_types.ModuleType("ollama")
    mod.chat = lambda model, messages: resp
    return mod


def _fake_genai_module(text: str) -> tuple[stdlib_types.ModuleType, stdlib_types.ModuleType]:
    class _Resp:
        pass

    class _Models:
        def generate_content(self, model, contents):
            r = _Resp()
            r.text = text
            return r

    class _Client:
        models = _Models()

        def __init__(self, api_key=None):
            pass

    google_mod = stdlib_types.ModuleType("google")
    genai_mod = stdlib_types.ModuleType("google.genai")
    genai_mod.Client = _Client
    google_mod.genai = genai_mod
    return google_mod, genai_mod


def test_ollama_backend_returns_content_from_ollama_chat(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", _fake_ollama_module(MANIFEST_JSON))

    from core.reasoning import OllamaBackend

    assert OllamaBackend(model="gemma4:31b").call("test prompt") == MANIFEST_JSON


def test_ollama_backend_raises_runtime_error_when_package_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "ollama", raising=False)
    import builtins

    original = builtins.__import__

    def _block(name, *args, **kwargs):
        if name == "ollama":
            raise ImportError("No module named 'ollama'")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block)

    from core.reasoning import OllamaBackend

    with pytest.raises(RuntimeError, match="ollama"):
        OllamaBackend().call("test")


def test_google_ai_backend_returns_text_from_generate_content(monkeypatch):
    google_mod, genai_mod = _fake_genai_module(MANIFEST_JSON)
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)

    from core.reasoning import GoogleAIBackend

    assert GoogleAIBackend(api_key="test-key").call("test prompt") == MANIFEST_JSON


def test_google_ai_backend_raises_runtime_error_when_package_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "google", raising=False)
    monkeypatch.delitem(sys.modules, "google.genai", raising=False)
    import builtins

    original = builtins.__import__

    def _block(name, *args, **kwargs):
        if name in ("google", "google.genai"):
            raise ImportError(f"No module named '{name}'")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block)

    from core.reasoning import GoogleAIBackend

    with pytest.raises(RuntimeError, match="google-genai"):
        GoogleAIBackend(api_key="key").call("test")


def test_reasoning_with_injected_backend_calls_backend_and_parses_manifest():
    from core.reasoning import VitreusReasoning

    class _MockBackend:
        def call(self, prompt: str) -> str:
            return MANIFEST_JSON

    reasoning = VitreusReasoning(backend=_MockBackend())
    result = reasoning.plan_action_sync(
        "Highlight anything",
        json.dumps([{"Name": "Ada", "Score": 91}]),
    )
    assert result == json.loads(MANIFEST_JSON)


def test_reasoning_without_backend_uses_deterministic_fallback():
    from core.reasoning import VitreusReasoning

    result = VitreusReasoning().plan_action_sync(
        "Highlight rows that need review",
        json.dumps([{"Name": "Linus", "Score": 72}]),
        sheet_name="Sheet1",
    )
    assert result["actions"][0]["type"] == "highlight"


def test_build_prompt_contains_task_model_name_and_sheet_data():
    from core.driver import WorkbookSnapshot
    from core.reasoning import VitreusReasoning

    snapshot = WorkbookSnapshot(sheets={"Sheet1": [["Item", "Total"], ["Coffee", 4.5]]})
    prompt = VitreusReasoning().build_prompt(
        "Explain totals", snapshot.range_to_json("Sheet1!A1:B2")
    )

    assert "Explain totals" in prompt
    assert "gemma4:31b" in prompt
    assert "Coffee" in prompt
