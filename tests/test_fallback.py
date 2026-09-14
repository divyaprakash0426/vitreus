from core.driver import WorkbookSnapshot
from core.fallback import plan_fallback

SAMPLE = """Name,Department,Budget,Spent,Status
Ada,Eng,100,90,ok
Alan,Eng,100,120,ok
Grace,Ops,50,20,ok
Dennis,Ops,60,75,ok
"""


def test_legacy_review_rule_highlights_scores_below_80():
    snapshot = WorkbookSnapshot.from_csv_text("Name,Score\nAda,91\nLinus,72\n")

    manifest = plan_fallback("Highlight rows that need review", snapshot, "Sheet1")

    assert manifest["actions"] == [
        {
            "type": "highlight",
            "range": "Sheet1!A3:B3",
            "color": "#f97316",
            "reason": "Score is below the review threshold of 80.",
        }
    ]
    assert "fallback" in manifest["summary"].lower()


def test_comparison_rule_highlights_rows_where_spent_exceeds_budget():
    snapshot = WorkbookSnapshot.from_csv_text(SAMPLE)

    manifest = plan_fallback("Highlight rows where Spent exceeds Budget", snapshot, "Sheet1")

    ranges = [a["range"] for a in manifest["actions"] if a["type"] == "highlight"]
    assert ranges == ["Sheet1!A3:E3", "Sheet1!A5:E5"]
    assert all("Spent" in a["reason"] and "Budget" in a["reason"] for a in manifest["actions"])


def test_comparison_rule_can_also_write_a_status_value():
    snapshot = WorkbookSnapshot.from_csv_text(SAMPLE)

    manifest = plan_fallback('Highlight rows where Spent is over Budget and write "over" in Status', snapshot, "Sheet1")

    writes = [a for a in manifest["actions"] if a["type"] == "write_value"]
    assert [(a["cell"], a["value"]) for a in writes] == [("Sheet1!E3", "over"), ("Sheet1!E5", "over")]


def test_unknown_request_returns_empty_actions_with_reasoning():
    snapshot = WorkbookSnapshot.from_csv_text(SAMPLE)

    manifest = plan_fallback("Forecast next quarter revenue", snapshot, "Sheet1")

    assert manifest["actions"] == []
    assert "no model backend" in manifest["summary"].lower()
