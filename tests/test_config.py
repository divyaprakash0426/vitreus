from pathlib import Path

from core.config import MODEL_IDS, Settings, config_template, detect_backend, load_settings


def test_defaults_are_local_first():
    s = load_settings(env={})

    assert s.backend == "auto"
    assert s.primary == "gemma4:31b"
    assert s.drafter == "gemma4:e4b"
    assert s.ollama_host == "http://localhost:11434"


def test_toml_values_override_defaults(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'backend = "google"\n[ollama]\nhost = "http://box:11434"\nnum_ctx = 8192\n[agent]\ncontext_tokens = 5000\n',
        encoding="utf-8",
    )

    s = load_settings(env={}, config_path=cfg)

    assert s.backend == "google"
    assert s.ollama_host == "http://box:11434"
    assert s.ollama_num_ctx == 8192
    assert s.context_tokens == 5000


def test_env_overrides_toml_and_cli_overrides_env(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('backend = "google"\n', encoding="utf-8")

    from_env = load_settings(env={"VITREUS_BACKEND": "openrouter", "OPENROUTER_API_KEY": "k"}, config_path=cfg)
    assert from_env.backend == "openrouter"
    assert from_env.openrouter_api_key == "k"

    from_cli = load_settings(overrides={"backend": "ollama"}, env={"VITREUS_BACKEND": "openrouter"}, config_path=cfg)
    assert from_cli.backend == "ollama"


def test_missing_config_file_is_ignored(tmp_path: Path):
    s = load_settings(env={}, config_path=tmp_path / "nope.toml")

    assert s.backend == "auto"


def test_detect_backend_prefers_ollama_when_reachable():
    s = load_settings(env={"GEMINI_API_KEY": "x"})

    backend, reason = detect_backend(s, ollama_reachable=lambda host: True)

    assert backend == "ollama"
    assert "localhost:11434" in reason


def test_detect_backend_falls_through_keys_then_fallback():
    assert detect_backend(load_settings(env={"GEMINI_API_KEY": "x"}), lambda h: False)[0] == "google"
    assert detect_backend(load_settings(env={"OPENROUTER_API_KEY": "x"}), lambda h: False)[0] == "openrouter"
    assert detect_backend(load_settings(env={"OPENAI_BASE_URL": "http://l:1234/v1"}), lambda h: False)[0] == "openai"
    backend, reason = detect_backend(load_settings(env={}), lambda h: False)
    assert backend == "fallback"
    assert "ollama" in reason.lower()


def test_detect_backend_respects_explicit_choice_without_probing():
    s = load_settings(overrides={"backend": "google"}, env={"GEMINI_API_KEY": "x"})

    def boom(host: str) -> bool:
        raise AssertionError("must not probe ollama for an explicit backend")

    assert detect_backend(s, ollama_reachable=boom) == ("google", "explicitly selected")


def test_model_for_maps_policy_names_per_backend():
    s = load_settings(env={})

    assert s.model_for("ollama") == "gemma4:31b"
    assert s.model_for("google") == MODEL_IDS["google"]["primary"]
    assert load_settings(overrides={"fast": True}, env={}).model_for("openrouter") == "google/gemma-4-26b-a4b-it"
    assert load_settings(overrides={"model": "gemma4:26b"}, env={}).model_for("ollama") == "gemma4:26b"
    assert load_settings(env={"OPENAI_MODEL": "local-gemma"}).model_for("openai") == "local-gemma"


def test_config_template_parses_as_toml_with_documented_sections():
    import tomllib

    parsed = tomllib.loads(config_template())

    assert parsed["backend"] == "auto"
    assert parsed["models"]["primary"] == "gemma4:31b"
    assert "ollama" in parsed and "agent" in parsed and "calc" in parsed


def test_settings_is_a_plain_dataclass_with_public_fields():
    s = Settings()

    assert s.max_steps == 8
    assert s.calc_port == 2002
