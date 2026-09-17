# -*- coding: utf-8 -*-
"""Tests for the multi-terminal MT5 manager (Run 24).

Covers the safety model end to end, without a real MT5 terminal:

- config parsing (missing/malformed files degrade safely),
- terminal listing merged with auto-detected running processes,
- selection re-attaches the binding and ALWAYS disarms execution,
- arming requires: running + execution-enabled + attached (fail-closed),
- ``execution_permitted()`` is the final gate consulted by the engine,
- ``/mt5/terminals`` endpoints report the registry honestly.

All tests run on CI Linux (no MetaTrader5 package, no psutil processes).
"""

from __future__ import annotations

import importlib
import json
import sys

import pytest

terminals = importlib.import_module("mt5.terminals")

CONFIG_TWO = {
    "terminals": [
        {"id": "a", "label": "Terminal A", "path": r"C:\mt\A\terminal64.exe", "execution": False},
        {"id": "c", "label": "Terminal C", "path": r"C:\mt\C\terminal64.exe", "execution": True},
    ]
}


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module-level manager state around every test."""
    terminals._selected_id = None
    terminals._execution_armed = False
    yield
    terminals._selected_id = None
    terminals._execution_armed = False


def _write_config(tmp_path, payload):
    p = tmp_path / "mt5_terminals.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _use_config(monkeypatch, tmp_path, payload):
    path = _write_config(tmp_path, payload)
    monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(path))
    return path


def _fake_running(folder: str, pid: int = 1111):
    """Return a scan_running_terminals replacement with one terminal."""
    return lambda: [{"pid": pid, "exe": f"{folder}\\terminal64.exe", "folder": folder}]


def _fake_attached(folder):
    """Return a _detect_attached_path replacement pointing at ``folder``."""
    return lambda: folder


# ---------------------------------------------------------------------------
# F1 — config loading
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_missing_file_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(tmp_path / "nope.json"))
        assert terminals.load_config() == []

    def test_malformed_json_returns_empty(self, monkeypatch, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(p))
        assert terminals.load_config() == []

    def test_parses_entries_and_defaults(self, monkeypatch, tmp_path):
        _use_config(
            monkeypatch,
            tmp_path,
            {
                "terminals": [
                    {"id": "a", "path": r"C:\mt\A\terminal64.exe"},
                    {"id": "", "path": "x"},  # dropped: empty id
                    {"id": "b"},  # dropped: no path
                    "junk",  # dropped: not a dict
                ]
            },
        )
        entries = terminals.load_config()
        assert len(entries) == 1
        assert entries[0]["id"] == "a"
        assert entries[0]["label"] == "a"  # label defaults to id
        assert entries[0]["execution"] is False  # execution defaults to False

    def test_bare_list_is_accepted(self, monkeypatch, tmp_path):
        _use_config(
            monkeypatch,
            tmp_path,
            [{"id": "a", "path": r"C:\mt\A\terminal64.exe", "execution": True}],
        )
        entries = terminals.load_config()
        assert entries[0]["execution"] is True


# ---------------------------------------------------------------------------
# F2 — registry view (config + auto-detect merge)
# ---------------------------------------------------------------------------


class TestListTerminals:
    def test_merges_config_with_auto_detected(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\A"))
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\A")

        view = terminals.list_terminals()
        by_id = {t["id"]: t for t in view["terminals"]}

        assert by_id["a"]["running"] is True
        assert by_id["a"]["pid"] == 1111
        assert by_id["a"]["source"] == "config"
        assert by_id["a"]["attached"] is True
        assert by_id["a"]["execution_allowed"] is False

        assert by_id["c"]["running"] is False  # in config, not running
        assert by_id["c"]["execution_allowed"] is True  # eligible candidate

        assert view["selected_id"] is None
        assert view["execution_armed"] is False
        assert view["attached_path"] == r"C:\mt\A"

    def test_auto_detected_terminal_is_data_only(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\Z", 2222))
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

        view = terminals.list_terminals()
        auto = [t for t in view["terminals"] if t["source"] == "auto"]
        assert len(auto) == 1
        assert auto[0]["id"] == "auto-2222"
        assert auto[0]["execution_allowed"] is False  # never armable

    def test_scan_without_psutil_returns_empty(self, monkeypatch):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("simulated missing psutil")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        monkeypatch.delitem(sys.modules, "psutil", raising=False)
        assert terminals.scan_running_terminals() == []


class TestWindowsPathHandling:
    """Regression: CI runs on Linux where os.path is posixpath.

    posixpath does not treat backslashes as separators, so
    ``os.path.dirname(r"C:\\mt\\A\\terminal64.exe")`` returns ``""`` and all
    folder matching silently fails. The module must derive folders from
    Windows paths via ``ntpath`` so the registry works on any host OS.
    """

    def test_folder_matching_survives_posixpath(self, monkeypatch, tmp_path):
        import posixpath
        import types

        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\A"))
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\A")

        real_os = terminals.os
        monkeypatch.setattr(
            terminals,
            "os",
            types.SimpleNamespace(path=posixpath, environ=real_os.environ),
        )

        view = terminals.list_terminals()
        by_id = {t["id"]: t for t in view["terminals"]}
        assert by_id["a"]["folder"] == r"C:\mt\A"
        assert by_id["a"]["running"] is True
        assert by_id["a"]["attached"] is True

    def test_norm_handles_windows_paths_on_any_os(self):
        assert terminals._norm(r"C:\MT\A\\") == terminals._norm(r"c:\mt\a")


# ---------------------------------------------------------------------------
# F3 — selection re-attaches and ALWAYS disarms
# ---------------------------------------------------------------------------


class TestSelectTerminal:
    def test_unknown_id_rejected(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

        result = terminals.select_terminal("nope")
        assert result["ok"] is False
        assert "not found" in result["message"].lower()

    def test_not_running_rejected(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

        result = terminals.select_terminal("a")
        assert result["ok"] is False
        assert "not running" in result["message"].lower()

    def test_switch_reattaches_and_disarms(self, monkeypatch, tmp_path):
        """Selecting C must re-attach and reset the arm switch to OFF."""
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\C", 3333))
        monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\C"))

        calls = []

        # ``terminals.select_terminal`` imports ``from . import connector`` at
        # call time, so patching the real module object is sufficient.
        real_connector = importlib.import_module("mt5.connector")
        monkeypatch.setattr(real_connector, "shutdown", lambda: calls.append("shutdown"))
        monkeypatch.setattr(
            real_connector,
            "use_live_data_mode",
            lambda path=None: (calls.append(path), True)[1],
        )

        # Pretend execution was armed before the switch.
        terminals._execution_armed = True

        result = terminals.select_terminal("c")
        assert result["ok"] is True
        assert calls[0] == "shutdown"
        assert calls[1] == r"C:\mt\C\terminal64.exe"
        assert result["execution_armed"] is False
        assert terminals.is_execution_armed() is False
        assert terminals._selected_id == "c"

    def test_failed_reattach_disarms_and_reports(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\C", 3333))
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

        real_connector = importlib.import_module("mt5.connector")
        monkeypatch.setattr(real_connector, "shutdown", lambda: None)
        monkeypatch.setattr(real_connector, "use_live_data_mode", lambda path=None: False)

        terminals._execution_armed = True
        result = terminals.select_terminal("c")
        assert result["ok"] is False
        assert result["execution_armed"] is False
        assert terminals.is_execution_armed() is False


# ---------------------------------------------------------------------------
# F4 — arm switch (fail-closed)
# ---------------------------------------------------------------------------


class TestArmExecution:
    def test_arm_without_selection_rejected(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

        result = terminals.arm_execution(True)
        assert result["ok"] is False
        assert terminals.is_execution_armed() is False

    def test_arm_requires_execution_flag(self, monkeypatch, tmp_path):
        """Terminal A is running+attached but NOT execution-enabled → reject."""
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\A"))
        monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\A"))
        terminals._selected_id = "a"

        result = terminals.arm_execution(True)
        assert result["ok"] is False
        assert "execution" in result["message"].lower()
        assert terminals.is_execution_armed() is False

    def test_arm_requires_running_terminal(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)
        terminals._selected_id = "c"

        result = terminals.arm_execution(True)
        assert result["ok"] is False
        assert terminals.is_execution_armed() is False

    def test_arm_requires_attached_binding(self, monkeypatch, tmp_path):
        """Running + execution-enabled but the binding is elsewhere → reject."""
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\C", 3333))
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\OTHER")
        terminals._selected_id = "c"

        result = terminals.arm_execution(True)
        assert result["ok"] is False
        assert "attached" in result["message"].lower()
        assert terminals.is_execution_armed() is False

    def test_arm_succeeds_when_all_conditions_met(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\C", 3333))
        monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\C"))
        terminals._selected_id = "c"

        result = terminals.arm_execution(True)
        assert result["ok"] is True
        assert result["armed"] is True
        assert terminals.is_execution_armed() is True
        assert terminals.execution_permitted() is True

    def test_disarm_always_allowed(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        terminals._execution_armed = True
        result = terminals.arm_execution(False)
        assert result["ok"] is True
        assert result["armed"] is False
        assert terminals.is_execution_armed() is False

    def test_arm_config_flag_is_reread_without_restart(self, monkeypatch, tmp_path):
        """Flipping "execution" in the JSON file takes effect immediately."""
        path = _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\A"))
        monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\A"))
        terminals._selected_id = "a"

        assert terminals.arm_execution(True)["ok"] is False  # flag still false

        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["terminals"][0]["execution"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert terminals.arm_execution(True)["ok"] is True


# ---------------------------------------------------------------------------
# F5 — execution_permitted(): the final gate
# ---------------------------------------------------------------------------


class TestExecutionPermitted:
    def test_false_by_default(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)
        assert terminals.execution_permitted() is False

    def test_false_when_terminal_stops_after_arming(self, monkeypatch, tmp_path):
        """Fail-closed: a terminal that dies after arming loses permission."""
        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\C", 3333))
        monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\C"))
        terminals._selected_id = "c"
        terminals._execution_armed = True

        assert terminals.execution_permitted() is True

        # The terminal process dies.
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        assert terminals.execution_permitted() is False


# ---------------------------------------------------------------------------
# F6 — endpoints
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine without requiring pytest-asyncio."""
    import asyncio

    return asyncio.run(coro)


class TestTerminalEndpoints:
    def test_list_endpoint_reports_registry(self, monkeypatch, tmp_path):
        from mt5.endpoints import list_terminals as endpoint

        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

        result = _run(endpoint())
        assert {t["id"] for t in result["terminals"]} == {"a", "c"}
        assert result["execution_armed"] is False

    def test_select_endpoint_rejects_unknown_terminal(self, monkeypatch, tmp_path):
        from mt5.endpoints import select_terminal as endpoint

        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

        result = _run(endpoint(type("R", (), {"terminal_id": "ghost"})()))
        # JSONResponse carries a 400 status for rejected selections.
        assert getattr(result, "status_code", None) == 400

    def test_arm_endpoint_rejects_when_not_eligible(self, monkeypatch, tmp_path):
        from mt5.endpoints import arm_terminal as endpoint

        _use_config(monkeypatch, tmp_path, CONFIG_TWO)
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

        result = _run(endpoint(type("R", (), {"armed": True})()))
        assert getattr(result, "status_code", None) == 400
