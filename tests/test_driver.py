import json

import pytest

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


def test_workbook_snapshot_saves_sheet_to_csv_file(tmp_path):
    snapshot = WorkbookSnapshot(
        sheets={"Sheet1": [["Name", "Score", "Status"], ["Ada", 91, "pass"], ["Linus", 72, "review"]]}
    )

    out = tmp_path / "out.csv"
    snapshot.save_csv(str(out), sheet_name="Sheet1")

    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Name,Score,Status"
    assert lines[1] == "Ada,91,pass"
    assert lines[2] == "Linus,72,review"


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


def test_apply_manifest_cli_saves_modified_csv_to_output_path(tmp_path):
    """apply-manifest --output writes write_value changes back to a new CSV."""
    import json as _json

    from typer.testing import CliRunner

    from interfaces.cli import app

    csv_path = tmp_path / "sheet.csv"
    manifest_path = tmp_path / "manifest.json"
    out_path = tmp_path / "sheet_applied.csv"

    csv_path.write_text("Name,Score,Notes\nAda,91,\nLinus,65,\n", encoding="utf-8")
    manifest_path.write_text(
        _json.dumps({"actions": [{"type": "write_value", "cell": "Sheet1!C3", "value": "NEEDS REVIEW"}]}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app, ["apply-manifest", str(csv_path), str(manifest_path), "--output", str(out_path)]
    )

    assert result.exit_code == 0
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Name,Score,Notes"
    assert lines[2] == "Linus,65,NEEDS REVIEW"


def test_apply_manifest_cli_saves_highlights_sidecar_json(tmp_path):
    """apply-manifest --output also writes a _highlights.json sidecar when highlights exist."""
    import json as _json

    from typer.testing import CliRunner

    from interfaces.cli import app

    csv_path = tmp_path / "sheet.csv"
    manifest_path = tmp_path / "manifest.json"
    out_path = tmp_path / "sheet_applied.csv"

    csv_path.write_text("Name,Score\nAda,91\n", encoding="utf-8")
    manifest_path.write_text(
        _json.dumps({"actions": [{"type": "highlight", "range": "Sheet1!A2:B2", "color": "#f97316", "reason": "test"}]}),
        encoding="utf-8",
    )

    CliRunner().invoke(app, ["apply-manifest", str(csv_path), str(manifest_path), "--output", str(out_path)])

    sidecar = tmp_path / "sheet_applied_highlights.json"
    assert sidecar.exists()
    data = _json.loads(sidecar.read_text())
    assert data["Sheet1!A2"]["background"] == "#f97316"



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
