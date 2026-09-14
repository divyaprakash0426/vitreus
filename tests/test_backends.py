import base64
import json

import httpx
import pytest

from core.backends import (
    BackendError,
    FallbackBackend,
    GoogleAIBackend,
    OllamaBackend,
    OpenAICompatibleBackend,
    make_backend,
    ollama_reachable,
)
from core.config import load_settings

MESSAGES = [
    {"role": "system", "content": "You are Vitreus."},
    {"role": "user", "content": "Highlight rows"},
]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ─── Ollama ──────────────────────────────────────────────────────────────────


def test_ollama_chat_posts_messages_with_num_ctx_and_returns_content():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"actions": []}'}})

    backend = OllamaBackend(host="http://localhost:11434", model="gemma4:31b", num_ctx=16384, client=_client(handler))

    assert backend.chat(MESSAGES) == '{"actions": []}'
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["body"]["model"] == "gemma4:31b"
    assert seen["body"]["stream"] is False
    assert seen["body"]["options"]["num_ctx"] == 16384
    assert seen["body"]["messages"][0] == {"role": "system", "content": "You are Vitreus."}


def test_ollama_grows_num_ctx_to_fit_long_prompts():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "{}"}})

    backend = OllamaBackend(host="http://localhost:11434", model="gemma4:31b", num_ctx=4096, client=_client(handler))
    backend.chat([{"role": "user", "content": "x" * 40000}])

    assert seen["body"]["options"]["num_ctx"] >= 12000


def test_ollama_attaches_base64_images_to_last_user_message():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "{}"}})

    OllamaBackend(host="http://h", model="m", client=_client(handler)).chat(MESSAGES, images=[PNG])

    assert seen["body"]["messages"][-1]["images"] == [base64.b64encode(PNG).decode()]


def test_ollama_missing_model_maps_to_backend_error_with_pull_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'gemma4:31b' not found"})

    with pytest.raises(BackendError) as excinfo:
        OllamaBackend(host="http://h", model="gemma4:31b", client=_client(handler)).chat(MESSAGES)

    assert "ollama pull gemma4:31b" in excinfo.value.hint


def test_ollama_connection_error_maps_to_backend_error_with_serve_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(BackendError) as excinfo:
        OllamaBackend(host="http://h", model="m", client=_client(handler)).chat(MESSAGES)

    assert "ollama serve" in excinfo.value.hint


def test_ollama_list_models_reads_tags():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "gemma4:31b"}, {"name": "gemma4:e4b"}]})

    assert OllamaBackend(host="http://h", model="m", client=_client(handler)).list_models() == ["gemma4:31b", "gemma4:e4b"]


def test_ollama_reachable_probe_true_and_false():
    ok = _client(lambda r: httpx.Response(200, json={"models": []}))
    assert ollama_reachable("http://h", client=ok) is True

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert ollama_reachable("http://h", client=_client(down)) is False


# ─── Google AI Studio ────────────────────────────────────────────────────────


def test_google_posts_system_instruction_contents_and_image_parts():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "reply"}]}}]})

    backend = GoogleAIBackend(api_key="secret", model="gemma-4-31b-it", client=_client(handler))

    assert backend.chat(MESSAGES + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "go"}], images=[PNG]) == "reply"
    assert seen["url"].startswith("https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it:generateContent")
    assert "key=secret" in seen["url"]
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "You are Vitreus."
    roles = [c["role"] for c in seen["body"]["contents"]]
    assert roles == ["user", "model", "user"]
    last_parts = seen["body"]["contents"][-1]["parts"]
    assert last_parts[0]["text"] == "go"
    assert last_parts[1]["inline_data"]["mime_type"] == "image/png"


def test_google_http_error_maps_to_backend_error_with_key_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "API key not valid"}})

    with pytest.raises(BackendError) as excinfo:
        GoogleAIBackend(api_key="bad", model="m", client=_client(handler)).chat(MESSAGES)

    assert "API key not valid" in str(excinfo.value)
    assert "GEMINI_API_KEY" in excinfo.value.hint


def test_google_list_models_filters_gemma():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "models/gemma-4-31b-it"}, {"name": "models/gemini-2.5-pro"}]})

    assert GoogleAIBackend(api_key="k", model="m", client=_client(handler)).list_models() == ["gemma-4-31b-it"]


# ─── OpenAI-compatible (OpenRouter, LM Studio, llama.cpp, vLLM) ──────────────


def test_openai_compatible_posts_chat_completions_with_bearer_and_image_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    backend = OpenAICompatibleBackend(
        base_url="https://openrouter.ai/api/v1", api_key="or-key", model="google/gemma-4-31b-it", name="openrouter",
        client=_client(handler),
    )

    assert backend.chat(MESSAGES, images=[PNG]) == "hi"
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer or-key"
    assert seen["body"]["model"] == "google/gemma-4-31b-it"
    content = seen["body"]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "Highlight rows"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_compatible_without_images_sends_plain_string_content():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    OpenAICompatibleBackend(base_url="http://localhost:1234/v1/", api_key=None, model="m", client=_client(handler)).chat(MESSAGES)

    assert seen["body"]["messages"][-1]["content"] == "Highlight rows"


def test_openai_compatible_error_maps_to_backend_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})

    with pytest.raises(BackendError, match="Insufficient credits"):
        OpenAICompatibleBackend(base_url="http://h/v1", api_key="k", model="m", client=_client(handler)).chat(MESSAGES)


def test_openai_compatible_list_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "google/gemma-4-31b-it"}, {"id": "other"}]})

    backend = OpenAICompatibleBackend(base_url="http://h/v1", api_key="k", model="m", client=_client(handler))

    assert backend.list_models() == ["google/gemma-4-31b-it", "other"]


# ─── Fallback + factory ──────────────────────────────────────────────────────


def test_fallback_backend_refuses_chat():
    with pytest.raises(BackendError):
        FallbackBackend().chat(MESSAGES)


def test_make_backend_auto_prefers_reachable_ollama():
    settings = load_settings(env={"GEMINI_API_KEY": "k"})

    backend, reason = make_backend(settings, ollama_probe=lambda host: True)

    assert isinstance(backend, OllamaBackend)
    assert backend.model == "gemma4:31b"
    assert "Ollama" in reason


def test_make_backend_auto_falls_back_to_google_then_openrouter():
    google, _ = make_backend(load_settings(env={"GEMINI_API_KEY": "k"}), ollama_probe=lambda host: False)
    assert isinstance(google, GoogleAIBackend) and google.model == "gemma-4-31b-it"

    openrouter, _ = make_backend(load_settings(env={"OPENROUTER_API_KEY": "k"}), ollama_probe=lambda host: False)
    assert isinstance(openrouter, OpenAICompatibleBackend)
    assert openrouter.name == "openrouter" and openrouter.model == "google/gemma-4-31b-it"
    assert openrouter.extra_headers["X-Title"] == "Vitreus"


def test_make_backend_openai_uses_base_url_and_model_from_settings():
    settings = load_settings(env={"OPENAI_BASE_URL": "http://localhost:1234/v1", "OPENAI_MODEL": "gemma-4-e4b"})

    backend, _ = make_backend(settings, ollama_probe=lambda host: False)

    assert isinstance(backend, OpenAICompatibleBackend)
    assert backend.base_url == "http://localhost:1234/v1" and backend.model == "gemma-4-e4b"


def test_make_backend_explicit_google_without_key_raises_actionable_error():
    with pytest.raises(BackendError) as excinfo:
        make_backend(load_settings(overrides={"backend": "google"}, env={}), ollama_probe=lambda host: False)

    assert "GEMINI_API_KEY" in excinfo.value.hint


def test_make_backend_fallback_when_nothing_configured():
    backend, reason = make_backend(load_settings(env={}), ollama_probe=lambda host: False)

    assert isinstance(backend, FallbackBackend)
    assert "fallback" in reason.lower()
