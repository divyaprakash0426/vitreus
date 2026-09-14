from core.context import build_context, describe_sheet, estimate_tokens, sheet_rows_csv
from core.driver import WorkbookSnapshot

SAMPLE = WorkbookSnapshot(
    sheets={
        "Budget": [
            ["Name", "Dept", "Budget", "Spent", "Ratio", "Notes"],
            ["Ada", "Eng", 120000, 98000, 0.82, "ok"],
            ["Alan", "Eng", 110000, 135000, 1.23, ""],
            ["Grace", "Mkt", 95000, 90000, 0.95, ""],
        ]
    },
    source="budget.csv",
)


def test_estimate_tokens_is_roughly_four_chars_per_token():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 400) == 101


def test_describe_sheet_reports_dims_range_and_column_types():
    info = describe_sheet(SAMPLE, "Budget")

    assert info["rows"] == 4 and info["cols"] == 6
    assert info["data_range"] == "Budget!A1:F4"
    by_name = {col["name"]: col for col in info["columns"]}
    assert by_name["Name"]["letter"] == "A" and by_name["Name"]["type"] == "text"
    assert by_name["Budget"]["type"] == "int"
    assert by_name["Budget"]["min"] == 95000 and by_name["Budget"]["max"] == 120000
    assert by_name["Budget"]["mean"] == 108333.33
    assert by_name["Ratio"]["type"] == "float"
    assert by_name["Notes"]["non_empty"] == 1
    assert by_name["Dept"]["sample"] == ["Eng", "Mkt"]


def test_describe_sheet_flags_mixed_and_empty_columns():
    snapshot = WorkbookSnapshot(sheets={"S": [["Mixed", "Empty"], [1, ""], ["x", ""], [2.5, ""]]})

    by_name = {col["name"]: col for col in describe_sheet(snapshot, "S")["columns"]}

    assert by_name["Mixed"]["type"] == "mixed"
    assert by_name["Empty"]["type"] == "empty"


def test_sheet_rows_csv_numbers_rows_and_letters_columns():
    text = sheet_rows_csv(SAMPLE, "Budget", start_row=1, end_row=2)

    lines = text.splitlines()
    assert lines[0] == "row,A,B,C,D,E,F"
    assert lines[1] == "1,Name,Dept,Budget,Spent,Ratio,Notes"
    assert lines[2] == "2,Ada,Eng,120000,98000,0.82,ok"
    assert len(lines) == 3


def test_build_context_includes_all_rows_for_small_sheets():
    text = build_context(SAMPLE, budget_tokens=24000)

    assert "## Sheet \"Budget\"" in text
    assert "4 rows x 6 columns, data range Budget!A1:F4" in text
    assert "C Budget (int" in text
    assert "4,Grace,Mkt,95000,90000,0.95," in text
    assert "omitted" not in text


def test_build_context_truncates_large_sheets_and_points_to_tools():
    rows = [["Id", "Value"]] + [[i, i * 2] for i in range(1, 5001)]
    snapshot = WorkbookSnapshot(sheets={"Big": rows})

    text = build_context(snapshot, budget_tokens=2000)

    assert "5001 rows x 2 columns" in text
    assert "rows omitted" in text and "get_range" in text
    assert "\n21,20,40" in text  # head keeps rows 1..21
    assert "\n5001,5000,10000" in text  # tail keeps last rows
    assert "\n2500,2499,4998" not in text
    assert estimate_tokens(text) < 2000 * 1.5


def test_build_context_lists_every_sheet_and_respects_sheet_filter():
    snapshot = WorkbookSnapshot(sheets={"A": [["x"], [1]], "B": [["y"], [2]], "C": [["z"], [3]]}, source="multi.xlsx")

    everything = build_context(snapshot)
    only_b = build_context(snapshot, sheets=["B"])

    assert "Workbook: multi.xlsx (3 sheets: A, B, C)" in everything
    assert '## Sheet "A"' in everything and '## Sheet "C"' in everything
    assert '## Sheet "A"' not in only_b and '## Sheet "B"' in only_b
    assert "Other sheets (not shown): A, C" in only_b


def test_build_context_handles_empty_sheet():
    text = build_context(WorkbookSnapshot(sheets={"Empty": []}))

    assert '## Sheet "Empty"' in text
    assert "0 rows x 0 columns" in text
