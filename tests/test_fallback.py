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


def test_comparison_rule_supports_numeric_thresholds_with_units():
    snapshot = WorkbookSnapshot.from_csv_text("name,size\nsmall.txt,512\nbig.bin,2097152\nmid.csv,1048577\n")

    manifest = plan_fallback("highlight files over 1 MB", snapshot, "Sheet1")

    assert [a["range"] for a in manifest["actions"]] == ["Sheet1!A3:B3", "Sheet1!A4:B4"]
    assert "1 MB" in manifest["actions"][0]["reason"] or "1048576" in manifest["actions"][0]["reason"]


def test_comparison_rule_supports_plain_numbers_and_percent():
    snapshot = WorkbookSnapshot.from_csv_text("Name,Spent,Margin\nA,120,5\nB,80,12\nC,150,-2\n")

    spent = plan_fallback("Highlight rows where Spent exceeds 100", snapshot, "Sheet1")
    margin = plan_fallback("flag rows where Margin is above 10%", snapshot, "Sheet1")

    assert [a["range"] for a in spent["actions"]] == ["Sheet1!A2:C2", "Sheet1!A4:C4"]
    assert [a["range"] for a in margin["actions"]] == ["Sheet1!A3:C3"]


def test_comparison_rule_supports_below_and_less_than():
    snapshot = WorkbookSnapshot(sheets={"S": [["Name", "Score", "Budget", "Spent"], ["Ada", 91, 100, 120], ["Bob", 55, 100, 40], ["Cy", 60, 100, 100]]})

    below = plan_fallback("highlight rows where score is below 60", snapshot, "S")
    less = plan_fallback("Highlight rows where Spent is less than Budget", snapshot, "S")

    assert [a["range"] for a in below["actions"]] == ["S!A3:D3"]
    assert "Score (55) is below 60" in below["actions"][0]["reason"]
    assert [a["range"] for a in less["actions"]] == ["S!A3:D3"]
    assert "below" in less["summary"]
