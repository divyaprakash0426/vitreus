import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.driver import ManifestSummary, WorkbookSnapshot


def _fake_bridge(tmp_path: Path) -> Path:
    script = tmp_path / "fake_bridge.py"
    script.write_text(
        """
import argparse
import json
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--host")
parser.add_argument("--port")
parser.add_argument("--open")
parser.add_argument("--selftest", action="store_true")
args = parser.parse_args()
if args.selftest:
    print(json.dumps({"ok": True, "uno": True}), flush=True)
    raise SystemExit(0)

for line in sys.stdin:
    payload = json.loads(line)
    cmd = payload.get("cmd")
    if cmd == "ping":
        print(json.dumps({"ok": True, "doc": "Fake.ods", "sheets": ["Data"]}), flush=True)
    elif cmd == "snapshot":
        print(json.dumps({"ok": True, "sheets": {"Data": [["A", "B"], [1, 2]]}}), flush=True)
    elif cmd == "execute":
        actions = payload.get("manifest", {}).get("actions", [])
        errors = []
        applied = 0
        for action in actions:
            if action.get("type") == "bogus":
                errors.append("Unsupported action type: bogus")
            else:
                applied += 1
        print(json.dumps({"ok": True, "applied": applied, "errors": errors}), flush=True)
    elif cmd == "save":
        print(json.dumps({"ok": True, "path": payload.get("path")}), flush=True)
    elif cmd == "error":
        print(json.dumps({"ok": False, "error": "fake failure"}), flush=True)
    elif cmd == "close":
        print(json.dumps({"ok": True}), flush=True)
        break
    else:
        print(json.dumps({"ok": False, "error": f"unexpected command: {cmd}"}), flush=True)
""".lstrip(),
        encoding="utf-8",
    )
    return script


def test_is_available_true_with_fake_bridge(tmp_path: Path):
    from core.uno_driver import UnoDriver

    driver = UnoDriver(python=sys.executable, bridge_script=_fake_bridge(tmp_path), timeout=5)
    try:
        assert driver.is_available() is True
    finally:
        driver.close()


def test_snapshot_returns_workbook_snapshot(tmp_path: Path):
    from core.uno_driver import UnoDriver

    driver = UnoDriver(python=sys.executable, bridge_script=_fake_bridge(tmp_path), timeout=5)
    try:
        snapshot = driver.snapshot()
    finally:
        driver.close()

    assert isinstance(snapshot, WorkbookSnapshot)
    assert snapshot.sheets["Data"][1] == [1, 2]


def test_execute_manifest_returns_summary_for_supported_actions(tmp_path: Path):
    from core.uno_driver import UnoDriver

    driver = UnoDriver(python=sys.executable, bridge_script=_fake_bridge(tmp_path), timeout=5)
    manifest = {
        "actions": [
            {"type": "highlight", "range": "Data!A1:B1", "color": "#ff0000", "reason": "header"},
            {"type": "write_value", "cell": "Data!A2", "value": "done"},
        ]
    }

    try:
        summary = driver.execute_manifest(manifest)
    finally:
        driver.close()

    assert isinstance(summary, ManifestSummary)
    assert summary == ManifestSummary(applied=2, errors=[])


def test_execute_manifest_preserves_unsupported_action_errors(tmp_path: Path):
    from core.uno_driver import UnoDriver

    driver = UnoDriver(python=sys.executable, bridge_script=_fake_bridge(tmp_path), timeout=5)
    try:
        summary = driver.execute_manifest({"actions": [{"type": "bogus"}]})
    finally:
        driver.close()

    assert summary.applied == 0
    assert summary.errors == ["Unsupported action type: bogus"]


def test_bridge_ok_false_raises_runtime_error_with_message(tmp_path: Path):
    from core.uno_driver import UnoDriver

    driver = UnoDriver(python=sys.executable, bridge_script=_fake_bridge(tmp_path), timeout=5)
    try:
        with pytest.raises(RuntimeError, match="fake failure"):
            driver._request({"cmd": "error"})
    finally:
        driver.close()


def test_find_uno_python_returns_none_for_missing_candidate():
    from core import uno_driver

    uno_driver._UNO_PYTHON_CACHE = None

    assert uno_driver.find_uno_python(candidates=["/definitely/not/a/python"]) is None


def test_find_uno_python_returns_none_when_candidate_lacks_uno():
    from core import uno_driver

    if subprocess.run(
        [sys.executable, "-c", "import uno"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0:
        pytest.skip("current interpreter can import uno")

    uno_driver._UNO_PYTHON_CACHE = None

    assert uno_driver.find_uno_python(candidates=[sys.executable]) is None


def test_launch_calc_builds_headless_accept_command(monkeypatch):
    from core.uno_driver import launch_calc

    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    proc = launch_calc(headless=True, port=2199)

    assert isinstance(proc, FakePopen)
    command = captured["args"]
    assert command[0] in {"soffice", "libreoffice"}
    assert "--headless" in command
    assert "--invisible" in command
    assert "--norestore" in command
    assert "--nologo" in command
    assert "--nodefault" in command
    assert "--accept=socket,host=localhost,port=2199;urp;StarOffice.ComponentContext" in command


def test_bridge_helpers_are_importable_without_uno():
    from core import uno_bridge

    assert uno_bridge._parse_range("My Sheet!B2:D10") == ("My Sheet", 1, 1, 3, 9)
    assert uno_bridge._col_index("AB") == 27
    assert uno_bridge._shift_formula("=B2*2", 2) == "=B4*2"
    assert uno_bridge._shift_formula("=$B$2*2", 2) == "=$B$2*2"
    assert uno_bridge._fill_formula_for_row("=B{row}-C{row}", 7) == "=B7-C7"
    assert uno_bridge._hex_to_int("#ff0000") == 0xFF0000
    assert uno_bridge._filter_for(".xlsx") == "Calc MS Excel 2007 XML"


def test_normalize_formula_converts_argument_commas_to_semicolons_outside_strings():
    from core.uno_bridge import _normalize_formula

    assert _normalize_formula('=IF(C2>B2,"over, budget","ok")') == '=IF(C2>B2;"over, budget";"ok")'
    assert _normalize_formula("=SUM(B2:B10)") == "=SUM(B2:B10)"
    assert _normalize_formula("=SUM(A1;B1)") == "=SUM(A1;B1)"
    assert _normalize_formula("plain text") == "plain text"


def test_launch_calc_visible_mode_opens_calc_window(monkeypatch):
    from core.uno_driver import launch_calc

    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args

    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    launch_calc(port=2002)
    assert "--calc" in captured["args"] and "--invisible" not in captured["args"] and "--headless" not in captured["args"]

    launch_calc("budget.xlsx", port=2002)
    assert captured["args"][-1] == "budget.xlsx" and "--calc" not in captured["args"]
