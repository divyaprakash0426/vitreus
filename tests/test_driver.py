import json

from core.driver import CellFormat, InMemoryCalcDriver, WorkbookSnapshot


def test_workbook_snapshot_exports_range_to_csv_and_json():
    snapshot = WorkbookSnapshot(
        sheets={
            "Budget": [
                ["Category", "Amount"],
                ["Cloud", 120.5],
                ["Hardware", 240],
            ]
        }
    )

    assert snapshot.range_to_csv("Budget!A1:B3") == "Category,Amount\r\nCloud,120.5\r\nHardware,240\r\n"
    assert json.loads(snapshot.range_to_json("Budget!A2:B3")) == [
        {"Category": "Cloud", "Amount": 120.5},
        {"Category": "Hardware", "Amount": 240},
    ]


def test_in_memory_driver_executes_highlight_value_and_formula_manifest():
    driver = InMemoryCalcDriver(
        WorkbookSnapshot(sheets={"Sheet1": [["Name", "Score"], ["Ada", 91], ["Linus", 72]]})
    )

    summary = driver.execute_manifest(
        {
            "actions": [
                {"type": "highlight", "range": "Sheet1!B2:B2", "color": "#16a34a"},
                {"type": "write_value", "cell": "Sheet1!C2", "value": "pass"},
                {"type": "formula", "cell": "Sheet1!C3", "formula": "=IF(B3>80,\"pass\",\"review\")"},
            ]
        }
    )

    assert summary.applied == 3
    assert driver.snapshot.sheets["Sheet1"][1][2] == "pass"
    assert driver.snapshot.sheets["Sheet1"][2][2] == '=IF(B3>80,"pass","review")'
    assert driver.formats["Sheet1!B2"] == CellFormat(background="#16a34a")


def test_invalid_manifest_action_is_reported_without_mutating_sheet():
    driver = InMemoryCalcDriver(WorkbookSnapshot(sheets={"Sheet1": [["A"], [1]]}))

    summary = driver.execute_manifest({"actions": [{"type": "delete_sheet", "sheet": "Sheet1"}]})

    assert summary.applied == 0
    assert summary.errors == ["Unsupported action type: delete_sheet"]
    assert driver.snapshot.sheets["Sheet1"] == [["A"], [1]]
