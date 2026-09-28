# -*- coding: utf-8 -*-
"""Tests for multi-terminal fan-out (F1) — one analysis → many terminals.

Runs without a real MT5 terminal: MetaTrader5, the connector and the symbol
resolver are stubbed. Covers:

- ``get_fanout_targets`` selection (running + execution:true + armed + fanout_target),
- ``update_terminal_config`` writing per-account sizing to mt5_terminals.json,
- ``ExecutionEngine.execute_order_fanout``: re-attach per terminal, distance →
  absolute SL/TP, per-account lot, partial failure, binding restore,
- fail-closed without an approval token,
- the pipeline ``_dispatch_execution`` adapter (fan-out vs single order).
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

terminals = importlib.import_module("mt5.terminals")
engine_mod = importlib.import_module("execution.engine")


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_state():
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
    p.write_text(__import__("json").dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(p))
    return p


def _running(folder: str, pid: int = 1):
    return lambda: [{"pid": pid, "exe": f"{folder}\\terminal64.exe", "folder": folder}]


# ---------------------------------------------------------------------------
# get_fanout_targets
# ---------------------------------------------------------------------------
def test_fanout_targets_require_running_armed_eligible(monkeypatch, tmp_path):
    _use_config(
        monkeypatch,
        tmp_path,
        {
            "terminals": [
                {"id": "a", "label": "A", "path": r"C:\mt\A\terminal64.exe", "execution": True},
                {"id": "b", "label": "B", "path": r"C:\mt\B\terminal64.exe", "execution": True},
                {"id": "c", "label": "C", "path": r"C:\mt\C\terminal64.exe", "execution": False},
            ]
        },
    )
    # Only terminal A is running; B (armed) is NOT running → excluded.
    monkeypatch.setattr(terminals, "scan_running_terminals", _running(r"C:\mt\A"))
    terminals._state_for("a")["armed"] = True
    terminals._state_for("b")["armed"] = True  # armed but not running
    targets = terminals.get_fanout_targets()
    assert [t["id"] for t in targets] == ["a"]


def test_fanout_targets_excluded_by_flag(monkeypatch, tmp_path):
    _use_config(
        monkeypatch,
        tmp_path,
        {
            "terminals": [
                {
                    "id": "a",
                    "label": "A",
                    "path": r"C:\mt\A\terminal64.exe",
                    "execution": True,
                    "fanout_target": False,
                }
            ]
        },
    )
    monkeypatch.setattr(terminals, "scan_running_terminals", _running(r"C:\mt\A"))
    terminals._state_for("a")["armed"] = True
    assert terminals.get_fanout_targets() == []


# ---------------------------------------------------------------------------
# update_terminal_config
# ---------------------------------------------------------------------------
def test_update_terminal_config_persists_fields(monkeypatch, tmp_path):
    path = _use_config(
        monkeypatch,
        tmp_path,
        {"terminals": [{"id": "a", "label": "A", "path": r"C:\mt\A\terminal64.exe"}]},
    )
    res = terminals.update_terminal_config(
        "a", {"fixed_lot": 0.05, "risk_per_trade_pct": 1.0, "fanout_target": True}
    )
    assert res["ok"] is True
    written = __import__("json").loads(path.read_text(encoding="utf-8"))
    entry = written["terminals"][0]
    assert entry["fixed_lot"] == 0.05
    assert entry["risk_per_trade_pct"] == 1.0
    assert entry["fanout_target"] is True


def test_update_terminal_config_rejects_unknown_terminal(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {"terminals": []})
    res = terminals.update_terminal_config("ghost", {"fixed_lot": 0.1})
    assert res["ok"] is False


def test_update_terminal_config_allows_clearing(monkeypatch, tmp_path):
    _use_config(
        monkeypatch,
        tmp_path,
        {
            "terminals": [
                {"id": "a", "label": "A", "path": r"C:\mt\A\terminal64.exe", "fixed_lot": 0.5}
            ]
        },
    )
    res = terminals.update_terminal_config("a", {"fixed_lot": None})
    assert res["ok"] is True
    assert res["terminal"]["fixed_lot"] is None


# ---------------------------------------------------------------------------
# execute_order_fanout — with a stubbed MetaTrader5
# ---------------------------------------------------------------------------
class _FakeMT5(types.ModuleType):
    TRADE_ACTION_DEAL = 0
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0

    def __init__(self):
        super().__init__("MetaTrader5")
        self.sent: list[dict] = []
        self.attached = None
        self._fail_symbols: set[str] = set()

    # -- binding ---------------------------------------------------------
    def initialize(self, path=None):
        self.attached = path
        return True

    def shutdown(self):
        self.attached = None

    def terminal_info(self):
        return types.SimpleNamespace(path=self.attached)

    # -- market / account ------------------------------------------------
    def symbol_info_tick(self, symbol):
        return types.SimpleNamespace(ask=100.0, bid=99.9)

    def symbol_info(self, symbol):
        return types.SimpleNamespace(
            trade_tick_value=1.0, trade_tick_size=0.01, volume_step=0.01, volume_min=0.01
        )

    def account_info(self):
        return types.SimpleNamespace(equity=10000.0, balance=10000.0)

    # -- order -----------------------------------------------------------
    def order_send(self, payload):
        self.sent.append(payload)
        if payload["symbol"] in self._fail_symbols:
            return types.SimpleNamespace(retcode=10004, comment="rejected", order=0)
        return types.SimpleNamespace(
            retcode=10009, comment="done", order=555, price=payload["price"]
        )


def _install_fakes(monkeypatch, mt5: _FakeMT5):
    """Install fakes WITHOUT replacing the mt5 submodules wholesale.

    Replacing ``sys.modules['mt5.connector']`` leaks: Python sets the ``mt5``
    package attribute to the fake, and monkeypatch's undo restores only
    ``sys.modules`` — so later tests doing ``from mt5 import connector`` still
    get the fake. We instead patch attributes on the REAL modules (monkeypatch
    restores each cleanly).
    """
    monkeypatch.setitem(sys.modules, "MetaTrader5", mt5)

    connector = importlib.import_module("mt5.connector")
    monkeypatch.setattr(connector, "shutdown", mt5.shutdown, raising=False)
    monkeypatch.setattr(
        connector, "use_live_data_mode", lambda path=None: mt5.initialize(path), raising=False
    )

    resolver = importlib.import_module("mt5.symbol_resolver")
    monkeypatch.setattr(resolver, "clear_symbol_cache", lambda: None, raising=False)
    monkeypatch.setattr(resolver, "resolve_symbol", lambda s: s, raising=False)


def _request():
    return engine_mod.OrderRequest(
        symbol="XAUUSD", order_type="BUY", volume=0.10, price=100.0, sl=99.0, tp=103.0
    )


def test_fanout_dispatches_to_all_targets(monkeypatch):
    mt5 = _FakeMT5()
    _install_fakes(monkeypatch, mt5)
    engine = engine_mod.ExecutionEngine(simulation_mode=False)

    targets = [
        {"id": "a", "label": "A", "path": r"C:\mt\A\terminal64.exe", "fixed_lot": 0.05},
        {"id": "b", "label": "B", "path": r"C:\mt\B\terminal64.exe", "fixed_lot": 0.02},
    ]
    out = engine.execute_order_fanout(_request(), targets=targets, risk_price=1.0, tp_price=3.0)
    assert out.target_count == 2
    assert out.succeeded == 2 and out.failed == 0
    assert len(mt5.sent) == 2
    # Per-account lot honoured.
    vols = sorted(p["volume"] for p in mt5.sent)
    assert vols == [0.02, 0.05]
    # SL/TP are distances off the terminal's own entry (100.0).
    for p in mt5.sent:
        assert p["sl"] == pytest.approx(99.0)
        assert p["tp"] == pytest.approx(103.0)


def test_fanout_partial_failure_continues(monkeypatch):
    mt5 = _FakeMT5()
    mt5._fail_symbols = {"XAUUSD"}  # every send rejects here
    _install_fakes(monkeypatch, mt5)

    # Make ONE terminal use a symbol that succeeds to prove continuation.
    engine = engine_mod.ExecutionEngine(simulation_mode=False)
    targets = [
        {"id": "a", "label": "A", "path": r"C:\mt\A\terminal64.exe", "fixed_lot": 0.05},
        {"id": "b", "label": "B", "path": r"C:\mt\B\terminal64.exe", "fixed_lot": 0.05},
    ]
    # First send fails, second succeeds (flip the fail set inside order_send).
    calls = {"n": 0}
    orig = mt5.order_send

    def send_alternating(payload):
        calls["n"] += 1
        if calls["n"] == 2:
            mt5._fail_symbols = set()
        return orig(payload)

    mt5.order_send = send_alternating  # type: ignore[assignment]

    out = engine.execute_order_fanout(_request(), targets=targets, risk_price=1.0, tp_price=3.0)
    assert out.target_count == 2
    assert out.succeeded == 1 and out.failed == 1
    assert out.any_success and not out.all_success


def test_fanout_fail_closed_without_token(monkeypatch):
    mt5 = _FakeMT5()
    _install_fakes(monkeypatch, mt5)
    engine = engine_mod.ExecutionEngine(simulation_mode=False, require_approval=True)
    out = engine.execute_order_fanout(_request(), targets=[{"id": "a", "path": "x"}])
    assert out.succeeded == 0
    assert out.results[0]["error_code"] == 403
    assert mt5.sent == []


def test_fanout_simulation_when_no_mt5(monkeypatch):
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    engine = engine_mod.ExecutionEngine(simulation_mode=True)
    targets = [
        {"id": "a", "label": "A", "path": r"C:\mt\A\terminal64.exe", "fixed_lot": 0.05},
        {"id": "b", "label": "B", "path": r"C:\mt\B\terminal64.exe", "fixed_lot": 0.05},
    ]
    out = engine.execute_order_fanout(_request(), targets=targets)
    assert out.target_count == 2 and out.succeeded == 2
    assert all(r.get("simulated") for r in out.results)


def test_fanout_restores_binding(monkeypatch):
    mt5 = _FakeMT5()
    mt5.initialize(r"C:\mt\ORIGINAL\terminal64.exe")  # pre-attached binding
    _install_fakes(monkeypatch, mt5)
    engine = engine_mod.ExecutionEngine(simulation_mode=False)
    targets = [{"id": "a", "label": "A", "path": r"C:\mt\A\terminal64.exe", "fixed_lot": 0.05}]
    engine.execute_order_fanout(_request(), targets=targets, risk_price=1.0, tp_price=3.0)
    # After fan-out the binding is restored to the original terminal.
    assert mt5.attached == r"C:\mt\ORIGINAL\terminal64.exe"


# ---------------------------------------------------------------------------
# Pipeline live toggle (dashboard settings → no restart)
# ---------------------------------------------------------------------------
def _pipeline(**kwargs):
    pipeline_mod = importlib.import_module("orchestration.pipeline")
    return pipeline_mod.TradingPipeline(
        supervisor=types.SimpleNamespace(analyze=lambda ctx: {}),
        risk_gate=types.SimpleNamespace(),
        **kwargs,
    )


def test_pipeline_fanout_toggle_is_live_callable():
    state = {"on": False}
    pipe = _pipeline(fanout_enabled=lambda: state["on"])
    assert pipe.fanout_enabled is False
    state["on"] = True
    # Read again → reflects the live value without recreating the pipeline.
    assert pipe.fanout_enabled is True


def test_pipeline_zone_toggle_is_live_callable():
    state = {"on": False}
    pipe = _pipeline(zone_entry_enabled=lambda: state["on"])
    assert pipe.zone_entry_enabled is False
    state["on"] = True
    assert pipe.zone_entry_enabled is True


def test_pipeline_toggle_bool_still_supported():
    assert _pipeline(fanout_enabled=True).fanout_enabled is True
    assert _pipeline(fanout_enabled=False).fanout_enabled is False


def test_pipeline_toggle_provider_failure_is_failsafe():
    def boom():
        raise RuntimeError("store down")

    # A broken provider never breaks a cycle — it fails safe to False.
    assert _pipeline(fanout_enabled=boom).fanout_enabled is False
