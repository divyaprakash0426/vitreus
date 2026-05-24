from core.driver import WorkbookSnapshot
from core.reasoning import GemmaModelChoice, VitreusReasoning


def test_model_choice_explains_31b_dense_selection():
    choice = GemmaModelChoice.default()

    assert choice.primary == "gemma4:31b"
    assert "31B Dense" in choice.rationale
    assert "long-context workbook reasoning" in choice.rationale


def test_fallback_planner_returns_highlight_manifest_for_review_query():
    reasoning = VitreusReasoning()
    snapshot = WorkbookSnapshot(sheets={"Scores": [["Name", "Score"], ["Ada", 91], ["Linus", 72]]})

    manifest = reasoning.plan_action_sync("Highlight rows that need review", snapshot.range_to_json("Scores!A1:B3"))

    assert manifest["model"]["primary"] == "gemma4:31b"
    assert manifest["actions"] == [
        {
            "type": "highlight",
            "range": "Scores!A3:B3",
            "color": "#f97316",
            "reason": "Score is below the review threshold of 80.",
        }
    ]


def test_parse_llm_manifest_extracts_json_object_from_markdown_fence():
    content = """Gemma plan:

```json
{"actions": [{"type": "write_value", "cell": "Sheet1!A1", "value": "ok"}]}
```
"""

    assert VitreusReasoning.parse_manifest(content) == {
        "actions": [{"type": "write_value", "cell": "Sheet1!A1", "value": "ok"}]
    }


def test_context_payload_contains_task_model_name_and_sheet_data():
    snapshot = WorkbookSnapshot(sheets={"Sheet1": [["Item", "Total"], ["Coffee", 4.5]]})

    prompt = VitreusReasoning().build_prompt("Explain totals", snapshot.range_to_json("Sheet1!A1:B2"))

    assert "Explain totals" in prompt
    assert "gemma4:31b" in prompt
    assert "Coffee" in prompt
