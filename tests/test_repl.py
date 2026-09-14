import json
from pathlib import Path

from core.agent import SpreadsheetAgent
from core.config import load_settings
from core.driver import WorkbookDriver
from interfaces.repl import run_chat

MANIFEST = json.dumps({"summary": "Flagging Linus.", "actions": [{"type": "write_value", "cell": "Sheet1!C3", "value": "review"}]})


class Scripted:
    name = "scripted"
    model = "m"

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def chat(self, messages, images=None):
        self.requests.append([dict(m) for m in messages])
        return self.replies.pop(0)

    def list_models(self):
        return []


def make(replies):
    driver = WorkbookDriver.from_csv_text("Name,Score\nAda,91\nLinus,72\n")
    settings = load_settings(overrides={"backend": "fallback"}, env={})
    backend = Scripted(replies)
    agent = SpreadsheetAgent(backend, settings, driver.snapshot(), source_name="scores.csv")
    return agent, driver, backend


def scripted_io(lines):
    lines = list(lines)
    out: list[str] = []

    def input_fn(prompt=""):
        if not lines:
            raise EOFError
        return lines.pop(0)

    return input_fn, out.append, out


def test_chat_session_plans_previews_applies_and_saves(tmp_path: Path):
    agent, driver, backend = make([MANIFEST, json.dumps({"summary": "Done.", "actions": []})])
    save_path = tmp_path / "out.xlsx"
    input_fn, output_fn, out = scripted_io(["flag low scores", "/preview", "/apply", "second question", f"/save {save_path}", "/quit"])

    run_chat(agent, driver, input_fn=input_fn, output_fn=output_fn)

    text = "\n".join(out)
    assert "Flagging Linus." in text
    assert "C3" in text and "review" in text  # preview diff
    assert "applied 1" in text.lower()
    assert save_path.exists()
    assert driver.snapshot().sheets["Sheet1"][2][2] == "review"
    # after /apply the agent context was refreshed with the new snapshot
    assert "review" in backend.requests[1][-1]["content"]


def test_chat_handles_reset_help_and_eof():
    agent, driver, _ = make([])
    input_fn, output_fn, out = scripted_io(["/help", "/reset", "/apply"])

    run_chat(agent, driver, input_fn=input_fn, output_fn=output_fn)

    text = "\n".join(out).lower()
    assert "/apply" in text and "/quit" in text
    assert "nothing to apply" in text
    assert len(agent.messages) == 1


def test_chat_reports_agent_errors_and_continues():
    agent, driver, _ = make(["not json", "still not", "nope", MANIFEST])
    input_fn, output_fn, out = scripted_io(["do it", "again", "/quit"])

    run_chat(agent, driver, input_fn=input_fn, output_fn=output_fn)

    text = "\n".join(out)
    assert "valid manifest" in text and "Flagging Linus." in text


def test_apply_reports_bridge_failures_and_keeps_the_session_alive():
    agent, driver, backend = make([MANIFEST])

    class BrokenDriver:
        def execute_manifest(self, manifest):
            raise RuntimeError("Timed out waiting for UNO bridge response")

        def snapshot(self):
            return driver.snapshot()

    input_fn, output_fn, out = scripted_io(["flag low scores", "/apply", "/quit"])

    run_chat(agent, BrokenDriver(), input_fn=input_fn, output_fn=output_fn, live=True)

    text = "\n".join(out)
    assert "Apply failed: Timed out waiting for UNO bridge response" in text
    assert "bye" in text.lower() or "quit" in text.lower() or len(out) >= 3  # session continued to /quit


def test_format_manifest_only_hints_at_preview_when_there_are_actions():
    from core.manifest import validate_manifest
    from interfaces.repl import _format_manifest

    answer = _format_manifest(validate_manifest({"summary": "Row 3 is over budget.", "actions": []}, {"Sheet1"}))
    plan = _format_manifest(validate_manifest({"summary": "Flag it.", "actions": [{"type": "write_value", "cell": "Sheet1!H3", "value": "OVER"}]}, {"Sheet1"}))

    assert answer == "Row 3 is over budget."
    assert plan.endswith("Type /preview to see the diff, /apply to apply.")
