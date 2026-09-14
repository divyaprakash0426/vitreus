"""Venv-side client for the PyUNO bridge subprocess."""

from __future__ import annotations

import glob
import json
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from core.driver import ManifestSummary, WorkbookSnapshot

_UNO_PYTHON_CACHE: str | None = None


def _bridge_script() -> Path:
    return Path(__file__).with_name("uno_bridge.py")


def _candidate_order(explicit: str | None = None, candidates: list[str] | None = None) -> list[str]:
    if candidates is not None:
        values = ([explicit] if explicit else []) + candidates
    else:
        values = [
            explicit,
            os.environ.get("VITREUS_UNO_PYTHON"),
            "/usr/bin/python3",
            "python3",
            "/usr/lib/libreoffice/program/python",
            *sorted(glob.glob("/opt/libreoffice*/program/python")),
        ]
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _selftest_python(candidate: str, bridge_script: Path) -> bool:
    try:
        result = subprocess.run(
            [candidate, str(bridge_script), "--selftest"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return False
    return result.returncode == 0 and payload.get("ok") is True


def find_uno_python(explicit: str | None = None, candidates: list[str] | None = None) -> str | None:
    """Return a Python executable that can import PyUNO via `uno_bridge --selftest`."""
    global _UNO_PYTHON_CACHE

    if explicit is None and candidates is None and _UNO_PYTHON_CACHE:
        return _UNO_PYTHON_CACHE

    script = _bridge_script()
    for candidate in _candidate_order(explicit, candidates):
        if _selftest_python(candidate, script):
            if explicit is None and candidates is None:
                _UNO_PYTHON_CACHE = candidate
            return candidate
    return None


def launch_calc(
    file: str | None = None,
    port: int = 2002,
    headless: bool = False,
    user_profile: str | None = None,
) -> subprocess.Popen:
    """Launch LibreOffice Calc with a UNO socket listener and return immediately."""
    executable = "soffice" if shutil.which("soffice") else "libreoffice"
    command = [
        executable,
        "--invisible",
        "--norestore",
        "--nologo",
        "--nodefault",
        f"--accept=socket,host=localhost,port={port};urp;StarOffice.ComponentContext",
    ]
    if headless:
        command.insert(1, "--headless")
    if user_profile:
        profile_path = Path(user_profile).expanduser().resolve()
        profile_path.mkdir(parents=True, exist_ok=True)
        command.append(f"-env:UserInstallation={profile_path.as_uri()}")
    if file:
        command.append(str(file))
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class UnoDriver:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 2002,
        python: str | None = None,
        bridge_script: str | Path | None = None,
        open_path: str | None = None,
        timeout: float = 30.0,
    ):
        self.host = host
        self.port = port
        self.python = python
        self.bridge_script = Path(bridge_script) if bridge_script is not None else _bridge_script()
        self.open_path = open_path
        self.timeout = timeout
        self._process: subprocess.Popen | None = None
        self._last_ping: dict[str, Any] | None = None

    def __enter__(self) -> "UnoDriver":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def is_available(self) -> bool:
        try:
            self.connect()
            return True
        except RuntimeError:
            self.close()
            return False

    def connect(self) -> dict[str, Any]:
        if not self._python():
            raise RuntimeError(
                "No Python interpreter with PyUNO was found. Set VITREUS_UNO_PYTHON to a Python that can import uno."
            )
        try:
            self._last_ping = self._request({"cmd": "ping"})
            return self._last_ping
        except RuntimeError as exc:
            self.close()
            hint = (
                f"Start LibreOffice with: soffice --headless --invisible --norestore --nologo --nodefault "
                f"--accept=\"socket,host={self.host},port={self.port};urp;StarOffice.ComponentContext\""
            )
            raise RuntimeError(f"{exc}. {hint}") from exc

    def snapshot(self) -> WorkbookSnapshot:
        response = self._request({"cmd": "snapshot"})
        return WorkbookSnapshot(sheets=response["sheets"])

    def execute_manifest(self, manifest: Any) -> ManifestSummary:
        payload = manifest.model_dump() if hasattr(manifest, "model_dump") else manifest
        response = self._request({"cmd": "execute", "manifest": payload})
        return ManifestSummary(applied=int(response.get("applied", 0)), errors=list(response.get("errors", [])))

    def save(self, path: str | None = None) -> str:
        response = self._request({"cmd": "save", "path": path})
        return str(response.get("path") or "")

    def document_title(self) -> str:
        return str(self.connect().get("doc", ""))

    def sheet_names(self) -> list[str]:
        return list(self.connect().get("sheets", []))

    def close(self) -> None:
        process = self._process
        self._process = None
        self._last_ping = None
        if process is None:
            return
        if process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.write(json.dumps({"cmd": "close"}) + "\n")
                    process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def _python(self) -> str | None:
        if self.python:
            return self.python
        self.python = find_uno_python()
        return self.python

    def _ensure_process(self) -> subprocess.Popen:
        if self._process is not None and self._process.poll() is None:
            return self._process
        python = self._python()
        if not python:
            raise RuntimeError("No Python interpreter with PyUNO was found")
        args = [
            python,
            str(self.bridge_script),
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        if self.open_path:
            args.extend(["--open", self.open_path])
        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return self._process

    def _stderr_tail(self, process: subprocess.Popen, limit: int = 2000) -> str:
        if process.stderr is None or process.poll() is None:
            return ""
        try:
            return process.stderr.read()[-limit:]
        except OSError:
            return ""

    def _readline_with_timeout(self, process: subprocess.Popen) -> str:
        if process.stdout is None:
            raise RuntimeError("UNO bridge stdout is not available")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            if not selector.select(self.timeout):
                raise RuntimeError("Timed out waiting for UNO bridge response")
            return process.stdout.readline()
        finally:
            selector.close()

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        process = self._ensure_process()
        if process.stdin is None:
            raise RuntimeError("UNO bridge stdin is not available")
        try:
            process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            line = process.stdout.readline() if process.stdout else ""
            if not line:
                tail = self._stderr_tail(process)
                raise RuntimeError(f"UNO bridge died before accepting a request. {tail}".strip()) from exc
        line = self._readline_with_timeout(process)
        if not line:
            tail = self._stderr_tail(process)
            raise RuntimeError(f"UNO bridge died without a response. {tail}".strip())
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"UNO bridge returned invalid JSON: {line.strip()}") from exc
        if response.get("ok") is False:
            raise RuntimeError(str(response.get("error", "UNO bridge request failed")))
        return response
