# -*- coding: utf-8 -*-
"""B-10 — auto-detect active terminals: running is the only arm gate.

Proves: arm works for execution:false + auto-detected terminals, stopped
terminals fail closed, fan-out has no execution-flag gate, execution_permitted
still requires an attached binding, sizing falls back to the signal volume,
and the default state is DISARMED.
"""

from __future__ import annotations

import importlib
import json
import sys
import types

import pytest

terminals = importlib.import_module("mt5.terminals")
engine_mod = importlib.import_module("execution.engine")


CONFIG_B10 = {
    "terminals": [
        {
            "id": "bil2",
            "label": "BIL 2",
            "path": r"C:\mt\BIL2\terminal64.exe",
            "execution": True,
        },
        {
            "id": "vito2",
            "label": "VITO 2",
            "path": r"C:\mt\VITO2\terminal64.exe",
            "execution": False,
        },
        {
            "id": "third",
            "label": "THIRD",
            "path": r"C:\mt\THIRD\terminal64.exe",
            "execution": False,
        },
    ]
}


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module-level manager state around every test."""
    terminals._selected_id = None
    terminals._execution_armed = False
    terminals._terminal_states = {}
    terminals._mirror_selected = None
    terminals._mirror_armed = False
    terminals._account_cache = {}
    terminals._account_cache_ts = None
    yield
    terminals._selected_id = None
    terminals._execution_armed = False
    terminals._terminal_states = {}
    terminals._mirror_selected = None
    terminals._mirror_armed = False
    terminals._account_cache = {}
    terminals._account_cache_ts = None


def _use_config(monkeypatch, tmp_path, payload):
    p = tmp_path / "mt5_terminals.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(p))
    return p


def _fake_running(folder: str, pid: int = 1111):
    """Return a scan_running_terminals replacement with one terminal."""
    return lambda: [{"pid": pid, "exe": f"{folder}\\terminal64.exe", "folder": folder}]


def _fake_attached(folder):
    """Return a _detect_attached_path replacement pointing at ``folder``."""
    return lambda: folder


def _folder_of(terminal_id: str) -> str:
    return {
        "bil2": r"C:\mt\BIL2",
        "vito2": r"C:\mt\VITO2",
        "third": r"C:\mt\THIRD",
    }[terminal_id]


# ---------------------------------------------------------------------------
# Skenario 1 — arm execution:false terminal that IS running → OK
# ---------------------------------------------------------------------------
def test_b10_arm_execution_false_running_ok(monkeypatch, tmp_path):
    """vito2 is execution:false in config but running → arm SUCCEEDS."""
    _use_config(monkeypatch, tmp_path, CONFIG_B10)
    monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\VITO2", 30))
    monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\VITO2"))

    result = terminals.arm_terminal("vito2", True)
    assert result["ok"] is True
    assert result["armed"] is True
    assert terminals.get_armed_terminals() == ["vito2"]

    # Cleanup: disarm.
    assert terminals.arm_terminal("vito2", False)["ok"] is True
    assert terminals.get_armed_terminals() == []


# ---------------------------------------------------------------------------
# Skenario 2 — arm an AUTO-DETECTED terminal (not in config)
# ---------------------------------------------------------------------------
def test_b10_arm_auto_detected_terminal_ok(monkeypatch, tmp_path):
    """A running terminal absent from the config is armable + fan-out target."""
    _use_config(monkeypatch, tmp_path, CONFIG_B10)
    monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\Z", 2222))
    monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\Z"))

    view = terminals.list_terminals()
    auto = [t for t in view["terminals"] if t["source"] == "auto"]
    assert len(auto) == 1
    assert auto[0]["id"] == "auto-2222"
    assert auto[0]["armable"] is True
    assert auto[0]["fanout_target"] is True

    result = terminals.arm_terminal("auto-2222", True)
    assert result["ok"] is True
    assert terminals.get_armed_terminals() == ["auto-2222"]

    # Cleanup: disarm.
    terminals.arm_terminal("auto-2222", False)
    assert terminals.get_armed_terminals() == []


# ---------------------------------------------------------------------------
# Skenario 3 — arm a STOPPED terminal → rejected (fail-closed)
# ---------------------------------------------------------------------------
def test_b10_arm_stopped_rejected_fail_closed(monkeypatch, tmp_path):
    """A terminal present in config but NOT running cannot be armed."""
    _use_config(monkeypatch, tmp_path, CONFIG_B10)
    monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
    monkeypatch.setattr(terminals, "_detect_attached_path", lambda: None)

    result = terminals.arm_terminal("bil2", True)
    assert result["ok"] is False
    assert "not running" in result["message"].lower()
    assert terminals.get_armed_terminals() == []


# ---------------------------------------------------------------------------
# Skenario 4 — fan-out targets ignore the execution flag; drop when stopped
# ---------------------------------------------------------------------------
def test_b10_fanout_targets_ignore_execution_flag(monkeypatch, tmp_path):
    """fan-out = running + armed + fanout_target; the execution flag is ignored."""
    _use_config(monkeypatch, tmp_path, CONFIG_B10)
    monkeypatch.setattr(
        terminals,
        "scan_running_terminals",
        lambda: [
            {"pid": 10, "exe": r"C:\mt\BIL2\terminal64.exe", "folder": r"C:\mt\BIL2"},
            {"pid": 30, "exe": r"C:\mt\VITO2\terminal64.exe", "folder": r"C:\mt\VITO2"},
        ],
    )
    monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\BIL2"))

    # bil2 is execution:true; vito2 is execution:false — both are running.
    assert terminals.arm_terminal("vito2", True)["ok"] is True
    assert terminals.arm_terminal("bil2", True)["ok"] is True

    target_ids = {t["id"] for t in terminals.get_fanout_targets()}
    assert target_ids == {"bil2", "vito2"}

    # Both stop → fail-closed: no fan-out targets left.
    monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
    assert terminals.get_fanout_targets() == []


# ---------------------------------------------------------------------------
# Skenario 5 — execution_permitted still requires an ATTACHED binding
# ---------------------------------------------------------------------------
def test_b10_execution_permitted_still_requires_attached(monkeypatch, tmp_path):
    """Armed + running but binding attached elsewhere → fail-closed."""
    _use_config(monkeypatch, tmp_path, CONFIG_B10)
    monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\VITO2", 30))
    # Binding attached to a DIFFERENT terminal (not vito2).
    monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\OTHER"))

    assert terminals.arm_terminal("vito2", True)["ok"] is True
    assert terminals.execution_permitted() is False

    # Binding now attached to the armed terminal → permitted.
    monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\VITO2"))
    assert terminals.execution_permitted() is True

    # Cleanup: disarm.
    terminals.arm_terminal("vito2", False)


# ---------------------------------------------------------------------------
# Skenario 6 — an armed terminal that stops is dropped everywhere
# ---------------------------------------------------------------------------
def test_b10_armed_terminal_stops_dropped_everywhere(monkeypatch, tmp_path):
    """Fail-closed: a dead terminal leaves both armed + fan-out lists; the
    underlying arm state persists so it reappears when it runs again."""
    _use_config(monkeypatch, tmp_path, CONFIG_B10)
    monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\VITO2", 30))
    monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\VITO2"))

    assert terminals.arm_terminal("vito2", True)["ok"] is True
    assert terminals.get_armed_terminals() == ["vito2"]
    assert "vito2" in {t["id"] for t in terminals.get_fanout_targets()}

    # The terminal process dies.
    monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
    assert terminals.get_armed_terminals() == []
    assert terminals.get_fanout_targets() == []

    # It comes back up → arm state persisted (not reset), so it reappears.
    monkeypatch.setattr(terminals, "scan_running_terminals", _fake_running(r"C:\mt\VITO2", 30))
    assert terminals.get_armed_terminals() == ["vito2"]
    assert "vito2" in {t["id"] for t in terminals.get_fanout_targets()}

    # Cleanup: disarm.
    terminals.arm_terminal("vito2", False)


# ---------------------------------------------------------------------------
# Skenario 7 — sizing fallback to the signal volume
# ---------------------------------------------------------------------------
class _FakeSizingMT5(types.ModuleType):
    """Minimal MetaTrader5 stand-in for the fallback sizing path."""

    def __init__(self):
        super().__init__("MetaTrader5")
        self.attached = None

    def initialize(self, path=None):
        self.attached = path
        return True

    def shutdown(self):
        self.attached = None

    def account_info(self):
        return types.SimpleNamespace(equity=10000.0, balance=10000.0)

    def symbol_info(self, symbol):
        # Minimal broker constraints: step 0.01, min 0.01.
        return types.SimpleNamespace(
            trade_tick_value=1.0, trade_tick_size=0.01, volume_step=0.01, volume_min=0.01
        )

    def symbol_info_tick(self, symbol):
        return types.SimpleNamespace(ask=100.0, bid=99.9)


def test_b10_sizing_fallback_signal_volume(monkeypatch):
    """No fixed_lot/risk_pct → signal volume; fixed_lot wins; 0 → fail-closed."""
    monkeypatch.setitem(sys.modules, "MetaTrader5", _FakeSizingMT5())
    engine = engine_mod.ExecutionEngine(simulation_mode=False)

    # Target with no sizing config → fall back to the signal volume.
    assert engine._size_for_terminal({}, 100.0, 1.0, "XAUUSD", fallback_volume=0.10) == 0.10

    # fixed_lot has priority over the fallback.
    assert (
        engine._size_for_terminal({"fixed_lot": 0.05}, 100.0, 1.0, "XAUUSD", fallback_volume=0.10)
        == 0.05
    )

    # No fallback volume → fail-closed (0.0).
    assert engine._size_for_terminal({}, 100.0, 1.0, "XAUUSD", fallback_volume=0.0) == 0.0


# ---------------------------------------------------------------------------
# Skenario 8 — default state is DISARMED everywhere
# ---------------------------------------------------------------------------
def test_b10_default_state_all_disarmed(monkeypatch, tmp_path):
    """Without an explicit arm, nothing is armed and no fan-out targets exist."""
    _use_config(monkeypatch, tmp_path, CONFIG_B10)
    monkeypatch.setattr(
        terminals,
        "scan_running_terminals",
        lambda: [
            {"pid": 10, "exe": r"C:\mt\BIL2\terminal64.exe", "folder": r"C:\mt\BIL2"},
            {"pid": 30, "exe": r"C:\mt\VITO2\terminal64.exe", "folder": r"C:\mt\VITO2"},
        ],
    )
    monkeypatch.setattr(terminals, "_detect_attached_path", _fake_attached(r"C:\mt\BIL2"))

    view = terminals.list_terminals()
    assert view["execution_armed"] is False
    assert view["armed_terminals"] == []
    assert all(t["armed"] is False for t in view["terminals"])
    assert terminals.get_armed_terminals() == []
    assert terminals.get_fanout_targets() == []
