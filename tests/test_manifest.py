import json

import pytest

from core.manifest import (
    ACTION_TYPES,
    Manifest,
    ManifestValidationError,
    manifest_schema_text,
    parse_json_object,
    validate_manifest,
)

SHEETS = {"Sheet1"}


def test_parse_json_object_strips_markdown_fence():
    text = 'Here you go:\n```json\n{"summary": "ok", "actions": []}\n```\nDone.'

    assert parse_json_object(text) == {"summary": "ok", "actions": []}


def test_parse_json_object_finds_first_balanced_object_in_prose():
    text = 'Sure! {"summary": "a {nested} brace", "actions": []} trailing text {"x": 1}'

    assert parse_json_object(text)["summary"] == "a {nested} brace"


def test_parse_json_object_raises_on_no_object():
    with pytest.raises(ValueError, match="No JSON object"):
        parse_json_object("nothing here")


def test_every_action_type_validates():
    raw = {
        "summary": "all actions",
        "actions": [
            {"type": "highlight", "range": "Sheet1!A2:C2", "color": "#ef4444", "reason": "over budget"},
            {"type": "write_value", "cell": "Sheet1!D2", "value": "OVER BUDGET"},
            {"type": "write_range", "range": "Sheet1!E1:E2", "values": [["Flag"], ["x"]]},
            {"type": "formula", "cell": "Sheet1!F2", "formula": "=SUM(B2:C2)", "reason": "total"},
            {"type": "fill_formula", "range": "Sheet1!G2:G5", "formula": "=B{row}-C{row}"},
            {"type": "set_format", "range": "Sheet1!A1:G1", "bold": True, "background": "#e5e7eb"},
            {"type": "set_column_width", "sheet": "Sheet1", "column": "A", "width": 22},
            {"type": "freeze_panes", "sheet": "Sheet1", "cell": "A2"},
            {"type": "add_note", "cell": "Sheet1!D2", "text": "Reviewed by Vitreus"},
            {"type": "sort_range", "range": "Sheet1!A1:G5", "by_column": "B", "descending": True},
            {"type": "insert_rows", "sheet": "Sheet1", "at": 2, "count": 1},
            {"type": "delete_rows", "sheet": "Sheet1", "at": 5},
            {"type": "clear_range", "range": "Sheet1!H2:H5"},
            {"type": "add_sheet", "name": "Summary"},
            {"type": "write_value", "cell": "Summary!A1", "value": 42},
            {"type": "add_chart", "sheet": "Sheet1", "chart_type": "bar", "data_range": "Sheet1!A1:B5", "title": "Q1"},
        ],
    }

    manifest = validate_manifest(raw, SHEETS)

    assert isinstance(manifest, Manifest)
    assert [a.type for a in manifest.actions] == [a["type"] for a in raw["actions"]]
    assert manifest.actions[0].color == "#ef4444"
    assert manifest.actions[11].count == 1
    assert set(ACTION_TYPES) == {a["type"] for a in raw["actions"]}


def test_unknown_action_type_is_rejected_with_clear_message():
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest({"actions": [{"type": "delete_sheet", "sheet": "Sheet1"}]}, SHEETS)

    assert any("Unsupported action type: delete_sheet" in e for e in excinfo.value.errors)


def test_range_on_unknown_sheet_is_rejected():
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest({"actions": [{"type": "highlight", "range": "Ghost!A1:B2"}]}, SHEETS)

    assert any("Unknown sheet: Ghost" in e for e in excinfo.value.errors)


def test_range_without_sheet_prefix_is_rejected():
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest({"actions": [{"type": "write_value", "cell": "A1", "value": 1}]}, SHEETS)

    assert any("Sheet!A1" in e for e in excinfo.value.errors)


def test_range_is_allowed_on_sheet_created_earlier_in_same_manifest():
    manifest = validate_manifest(
        {"actions": [{"type": "add_sheet", "name": "New"}, {"type": "write_value", "cell": "New!A1", "value": 1}]},
        SHEETS,
    )

    assert len(manifest.actions) == 2


def test_named_colour_is_rejected_and_short_hex_expanded():
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest({"actions": [{"type": "highlight", "range": "Sheet1!A1", "color": "red"}]}, SHEETS)
    assert any("color" in e for e in excinfo.value.errors)

    ok = validate_manifest({"actions": [{"type": "highlight", "range": "Sheet1!A1", "color": "F00"}]}, SHEETS)
    assert ok.actions[0].color == "#ff0000"


def test_summary_only_manifest_is_valid_with_no_actions():
    manifest = validate_manifest({"summary": "Engineering spent the most."}, SHEETS)

    assert manifest.actions == []
    assert manifest.model is None


def test_missing_required_field_is_reported_per_action_index():
    with pytest.raises(ManifestValidationError) as excinfo:
        validate_manifest({"actions": [{"type": "formula", "cell": "Sheet1!A1"}]}, SHEETS)

    assert any(e.startswith("actions[0]") and "formula" in e for e in excinfo.value.errors)


def test_manifest_round_trips_through_json():
    manifest = validate_manifest(
        {"summary": "s", "actions": [{"type": "write_value", "cell": "Sheet1!A1", "value": 3.5}]}, SHEETS
    )

    dumped = json.loads(manifest.model_dump_json())

    assert dumped["actions"][0] == {"type": "write_value", "cell": "Sheet1!A1", "value": 3.5, "reason": ""}


def test_schema_text_documents_every_action_type():
    text = manifest_schema_text()

    for action_type in ACTION_TYPES:
        assert action_type in text
    assert "{row}" in text
