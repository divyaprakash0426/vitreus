import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from interfaces.cli import app


runner = CliRunner()


MOCK_MANIFEST = json.dumps({
    "model": {"primary": "gemma4:31b", "drafter": "gemma4:4b", "rationale": "test"},
    "actions": [],
})


def test_models_command_shows_gemma_4_selection():
    result = runner.invoke(app, ["models"])

    assert result.exit_code == 0
    assert "gemma4:31b" in result.stdout
    assert "31B Dense" in result.stdout


def test_analyze_command_reads_csv_and_outputs_manifest(tmp_path: Path):
    csv_path = tmp_path / "scores.csv"
    csv_path.write_text("Name,Score\nAda,91\nLinus,72\n", encoding="utf-8")

    result = runner.invoke(app, ["analyze", str(csv_path), "Highlight rows that need review"])

    assert result.exit_code == 0
    manifest = json.loads(result.stdout)
    assert manifest["actions"][0]["range"] == "Sheet1!A3:B3"


def test_apply_manifest_updates_csv_snapshot(tmp_path: Path):
    csv_path = tmp_path / "sheet.csv"
    manifest_path = tmp_path / "manifest.json"
    csv_path.write_text("Name,Score\nAda,91\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps({"actions": [{"type": "write_value", "cell": "Sheet1!C2", "value": "pass"}]}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["apply-manifest", str(csv_path), str(manifest_path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"applied": 1, "errors": []}


def test_analyze_with_backend_ollama_calls_ollama_backend(tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "scores.csv"
    csv_path.write_text("Name,Score\nAda,91\n", encoding="utf-8")

    monkeypatch.setattr("core.reasoning.OllamaBackend.call", lambda self, p: MOCK_MANIFEST)

    result = runner.invoke(app, ["analyze", str(csv_path), "any query", "--backend", "ollama"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["model"]["primary"] == "gemma4:31b"


def test_analyze_with_backend_google_and_api_key_calls_google_backend(tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "scores.csv"
    csv_path.write_text("Name,Score\nAda,91\n", encoding="utf-8")

    monkeypatch.setattr("core.reasoning.GoogleAIBackend.call", lambda self, p: MOCK_MANIFEST)

    result = runner.invoke(
        app, ["analyze", str(csv_path), "any query", "--backend", "google", "--api-key", "dummy-key"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["model"]["primary"] == "gemma4:31b"


def test_analyze_reads_api_key_from_env_var(tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "scores.csv"
    csv_path.write_text("Name,Score\nAda,91\n", encoding="utf-8")

    monkeypatch.setenv("GEMINI_API_KEY", "env-key-value")
    monkeypatch.setattr("core.reasoning.GoogleAIBackend.call", lambda self, p: MOCK_MANIFEST)

    result = runner.invoke(app, ["analyze", str(csv_path), "any query", "--backend", "google"])

    assert result.exit_code == 0
    manifest = json.loads(result.stdout)
    assert manifest["model"]["primary"] == "gemma4:31b"


def test_analyze_with_backend_google_missing_api_key_exits_nonzero(tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "scores.csv"
    csv_path.write_text("Name,Score\nAda,91\n", encoding="utf-8")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = runner.invoke(app, ["analyze", str(csv_path), "any query", "--backend", "google"])

    assert result.exit_code != 0
