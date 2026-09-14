import json

import pytest

from core.agent import SYSTEM_PROMPT, TOOLS, AgentError, SpreadsheetAgent
from core.backends import FallbackBackend
from core.config import load_settings
from core.driver import WorkbookSnapshot
from core.manifest import Manifest

CSV = """Name,Department,Budget,Spent
Ada,Eng,100,90
Alan,Eng,100,120
Grace,Ops,50,20
"""
MANIFEST = json.dumps(
    {"summary": "Alan is over budget.", "actions": [{"type": "highlight", "range": "Sheet1!A3:D3", "color": "#F97316", "reason": "Spent > Budget"}]}
)


class ScriptedBackend:
    name = "scripted"
    model = "scripted-1"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.requests: list[list[dict]] = []
        self.images: list = []

    def chat(self, messages, images=None):
        self.requests.append([dict(m) for m in messages])
        self.images.append(images)
        if not self.replies:
            raise AssertionError("ScriptedBackend ran out of replies")
        return self.replies.pop(0)

    def list_models(self):
        return [self.model]


def make_agent(replies, **overrides):
    backend = ScriptedBackend(replies)
    settings = load_settings(overrides={"backend": "fallback", **overrides}, env={})
    agent = SpreadsheetAgent(backend, settings, WorkbookSnapshot.from_csv_text(CSV), source_name="budget.csv")
    return agent, backend


def test_direct_manifest_reply_is_validated_and_stamped_with_model_info():
    agent, backend = make_agent([MANIFEST])

    result = agent.run("Highlight rows over budget")

    assert isinstance(result.manifest, Manifest)
    assert result.steps == 1 and result.tool_calls == []
    assert result.manifest.summary == "Alan is over budget."
    assert result.manifest.actions[0].color == "#f97316"
    assert result.manifest.model.backend == "scripted" and result.manifest.model.model == "scripted-1"
    system, user = backend.requests[0][0], backend.requests[0][1]
    assert system["role"] == "system" and system["content"] == SYSTEM_PROMPT
    assert "budget.csv" in user["content"] and "Alan" in user["content"] and "Highlight rows over budget" in user["content"]


def test_tool_call_round_trip_feeds_observation_back_to_model():
    tool_call = json.dumps({"tool": "get_range", "args": {"range": "Sheet1!A1:B2"}})
    agent, backend = make_agent([tool_call, MANIFEST])

    result = agent.run("Check budgets")

    assert result.steps == 2
    assert result.tool_calls == [{"tool": "get_range", "args": {"range": "Sheet1!A1:B2"}}]
    second = backend.requests[1]
    assert second[-2]["role"] == "assistant" and second[-2]["content"] == tool_call
    assert second[-1]["role"] == "user" and "observation" in second[-1]["content"].lower()
    assert "Ada" in second[-1]["content"]


def test_invalid_manifest_triggers_retry_with_validation_errors():
    bad = json.dumps({"summary": "x", "actions": [{"type": "explode", "range": "Sheet1!A1"}]})
    agent, backend = make_agent([bad, MANIFEST])

    result = agent.run("Do something")

    assert result.steps == 2
    assert "Unsupported action type" in backend.requests[1][-1]["content"]


def test_unknown_sheet_in_manifest_is_reported_to_model():
    bad = json.dumps({"actions": [{"type": "write_value", "cell": "Nope!A1", "value": 1}]})
    agent, backend = make_agent([bad, MANIFEST])

    agent.run("Write it")

    assert "Unknown sheet" in backend.requests[1][-1]["content"]


def test_non_json_reply_is_retried_then_fails_after_two_retries():
    agent, _ = make_agent(["Sure, I can help!", "still prose", "and more prose"])

    with pytest.raises(AgentError, match="valid manifest"):
        agent.run("Anything")


def test_unknown_tool_returns_error_observation_and_loop_continues():
    agent, backend = make_agent([json.dumps({"tool": "teleport", "args": {}}), MANIFEST])

    result = agent.run("Go")

    assert result.steps == 2
    assert "unknown tool" in backend.requests[1][-1]["content"].lower()
    assert all(name in backend.requests[1][-1]["content"] for name in sorted(TOOLS))


def test_all_tools_execute_against_snapshot():
    calls = [
        json.dumps({"tool": "list_sheets", "args": {}}),
        json.dumps({"tool": "describe_sheet", "args": {"sheet": "Sheet1"}}),
        json.dumps({"tool": "find", "args": {"text": "Grace"}}),
        MANIFEST,
    ]
    agent, backend = make_agent(calls)

    result = agent.run("Explore")

    assert result.steps == 4 and len(result.tool_calls) == 3
    assert "Sheet1" in backend.requests[1][-1]["content"]
    assert "Budget" in backend.requests[2][-1]["content"]
    assert "Sheet1!A4" in backend.requests[3][-1]["content"]


def test_exceeding_max_steps_raises_agent_error():
    tool_call = json.dumps({"tool": "list_sheets", "args": {}})
    agent, _ = make_agent([tool_call] * 5, max_steps=3)

    with pytest.raises(AgentError, match="3 steps"):
        agent.run("Loop forever")


def test_fallback_backend_uses_rule_planner_without_chat():
    settings = load_settings(overrides={"backend": "fallback"}, env={})
    agent = SpreadsheetAgent(FallbackBackend(), settings, WorkbookSnapshot.from_csv_text(CSV))

    result = agent.run("Highlight rows where Spent exceeds Budget")

    assert result.manifest.model.backend == "fallback"
    assert [a.range for a in result.manifest.actions] == ["Sheet1!A3:D3"]
    assert result.steps == 0


def test_chat_mode_keeps_history_and_refresh_updates_context():
    agent, backend = make_agent([MANIFEST, MANIFEST])

    agent.run("First question")
    agent.refresh(WorkbookSnapshot.from_csv_text("Name,Spent\nZed,1\n"))
    agent.run("Second question")

    second = backend.requests[1]
    roles = [m["role"] for m in second]
    assert roles.count("assistant") == 1
    assert any("Second question" in m["content"] for m in second if m["role"] == "user")
    assert "Zed" in second[-1]["content"]
    assert len(agent.messages) == 5  # system, user, assistant, user, assistant

    agent.reset()
    assert len(agent.messages) == 1


def test_images_are_passed_to_backend_on_first_call_only():
    agent, backend = make_agent([json.dumps({"tool": "list_sheets", "args": {}}), MANIFEST])

    agent.run("Read this receipt", images=[b"\x89PNG\r\n\x1a\nfake"])

    assert backend.images[0] == [b"\x89PNG\r\n\x1a\nfake"]
    assert backend.images[1] in (None, [])


def test_manifest_with_add_sheet_then_write_is_valid():
    reply = json.dumps({"actions": [{"type": "add_sheet", "name": "Summary"}, {"type": "write_value", "cell": "Summary!A1", "value": "Total"}]})
    agent, _ = make_agent([reply])

    result = agent.run("Make a summary sheet")

    assert [a.type for a in result.manifest.actions] == ["add_sheet", "write_value"]


def test_focus_sheets_limits_context_but_tools_reach_other_sheets():
    snapshot = WorkbookSnapshot(sheets={"Sales": [["Item", "Amount"], ["A", 1]], "Expenses": [["Item", "Amount"], ["Rent", 900]]})
    backend = ScriptedBackend([json.dumps({"tool": "get_range", "args": {"range": "Expenses!A1:B2"}}), MANIFEST.replace("Sheet1", "Sales")])
    settings = load_settings(overrides={"backend": "fallback"}, env={})
    agent = SpreadsheetAgent(backend, settings, snapshot, focus_sheets=["Sales"])

    agent.run("Look at expenses")

    first_user = backend.requests[0][1]["content"]
    assert "Rent" not in first_user and "Other sheets (not shown): Expenses" in first_user
    assert "Rent" in backend.requests[1][-1]["content"]
