# -*- coding: utf-8 -*-
"""B-9 Lanjutan — Multi-arm execution hardening.

Proves the four gaps that made manual per-account multi-arm unusable are
closed end to end (no real MT5 terminal needed):

1. several terminals can be ARMED at once WITHOUT attaching a binding first,
2. selecting another terminal does NOT disarm the already-armed ones,
3. canonical fan-out re-attaches the process-wide binding to EACH account
   before its order, then restores the original binding (fail-safe),
4. the single-terminal path fails closed when >1 terminal is armed (so a
   partial send can never silently leave the other armed accounts without an
   order) — while ``execution_permitted()`` keeps the "attached-to-an-armed"
   gate.

All fakes are injected; no real order is ever sent.
"""

from __future__ import annotations

import importlib
import json
import types

import pytest

terminals = importlib.import_module("mt5.terminals")
fanout_mod = importlib.import_module("execution.fanout")
canonical_mod = importlib.import_module("trading.canonical_signal")
pipeline_mod = importlib.import_module("orchestration.pipeline")
connector_mod = importlib.import_module("mt5.connector")


CONFIG_MULTI = {
    "terminals": [
        {"id": "a", "label": "A", "path": r"C:\mt\A\terminal64.exe", "execution": True},
        {"id": "b", "label": "B", "path": r"C:\mt\B\terminal64.exe", "execution": True},
        {"id": "c", "label": "C", "path": r"C:\mt\C\terminal64.exe", "execution": True},
    ]
}


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module-level manager state (and mirrors) around every test."""
    terminals._selected_id = None
    terminals._execution_armed = False
    terminals._terminal_states = {}
    terminals._mirror_selected = None
    terminals._mirror_armed = False
    terminals._account_cache = {}
    terminals._account_cache_ts = None
    fanout_mod.set_fanout_ledger(fanout_mod.FanoutLedger())
    yield
    terminals._selected_id = None
    terminals._execution_armed = False
    terminals._terminal_states = {}
    terminals._mirror_selected = None
    terminals._mirror_armed = False
    terminals._account_cache = {}
    terminals._account_cache_ts = None
    fanout_mod.set_fanout_ledger(fanout_mod.FanoutLedger())
    assert terminals.is_execution_armed() is False


def _use_config(monkeypatch, tmp_path, payload):
    p = tmp_path / "mt5_terminals.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(p))
    return p


def _three_running():
    return lambda: [
        {"pid": 10, "exe": r"C:\mt\A\terminal64.exe", "folder": r"C:\mt\A"},
        {"pid": 20, "exe": r"C:\mt\B\terminal64.exe", "folder": r"C:\mt\B"},
        {"pid": 30, "exe": r"C:\mt\C\terminal64.exe", "folder": r"C:\mt\C"},
    ]


def _mark_verified(*folders):
    for index, folder in enumerate(folders, start=1):
        terminals._account_cache[terminals._norm(folder)] = {
            "login": 3000 + index,
            "server": "Broker-Demo",
            "mode": "DEMO",
            "trade_mode": "0",
        }


# ===========================================================================
# 1. Multi-arm without attach
# ===========================================================================
class TestMultiArmWithoutAttach:
    def test_arm_two_terminals_without_attaching_each(self, monkeypatch, tmp_path):
        """Arming A+B must succeed WITHOUT attaching the binding to B first."""
        _use_config(monkeypatch, tmp_path, CONFIG_MULTI)
        monkeypatch.setattr(terminals, "scan_running_terminals", _three_running())
        # Binding is attached to A only.
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\A")
        _mark_verified(r"C:\mt\A", r"C:\mt\B", r"C:\mt\C")

        res_a = terminals.arm_terminal("a", True)
        res_b = terminals.arm_terminal("b", True)

        assert res_a["ok"] is True and res_a["armed"] is True
        assert res_b["ok"] is True and res_b["armed"] is True
        assert set(terminals.get_armed_terminals()) == {"a", "b"}


# ===========================================================================
# 2. Select does not disarm
# ===========================================================================
class TestSelectDoesNotDisarm:
    def test_select_moves_binding_but_keeps_arms(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_MULTI)
        monkeypatch.setattr(terminals, "scan_running_terminals", _three_running())
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\A")
        _mark_verified(r"C:\mt\A", r"C:\mt\B", r"C:\mt\C")
        assert terminals.arm_terminal("a", True)["ok"] is True
        assert terminals.arm_terminal("b", True)["ok"] is True

        calls = []
        monkeypatch.setattr(connector_mod, "shutdown", lambda: calls.append("shutdown"))
        monkeypatch.setattr(
            connector_mod,
            "use_live_data_mode",
            lambda path=None: (calls.append(path), True)[1],
        )
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\C")

        res = terminals.select_terminal("c")
        assert res["ok"] is True
        # Binding moved to C …
        assert "shutdown" in calls
        assert r"C:\mt\C\terminal64.exe" in calls
        assert res["selected_id"] == "c"
        # … but A and B remain armed.
        assert set(terminals.get_armed_terminals()) == {"a", "b"}
        assert terminals.is_execution_armed() is True


# ===========================================================================
# 3. Fan-out re-attaches per account (+ restore)
# ===========================================================================
class _RecordingConnector:
    """Fake connector recording attach/shutdown order (no real MT5)."""

    def __init__(self, attached=None, fail_paths=()):
        self.calls: list[str] = []
        self._attached = attached
        self._fail_paths = set(fail_paths)

    def shutdown(self):
        self.calls.append("shutdown")
        self._attached = None

    def use_live_data_mode(self, path=None):
        self.calls.append(f"attach:{path}")
        if path in self._fail_paths:
            return False
        self._attached = path
        return True


class _RecordingEngine:
    """Engine stub that records the binding attached at execute time."""

    def __init__(self, connector, fail_logins=()):
        self.connector = connector
        self.fail_logins = set(fail_logins)
        self.sent: list[dict] = []

    def execute_order(self, request):
        self.sent.append(
            {
                "account_id": getattr(request, "account_id", None),
                "symbol": getattr(request, "symbol", None),
                "attached": self.connector._attached,
            }
        )
        login = getattr(request, "account_id", None)
        ok = login not in self.fail_logins
        return types.SimpleNamespace(
            success=ok,
            ticket=len(self.sent) if ok else None,
            error_code=0 if ok else 10004,
            error_message="" if ok else "rejected",
            retries=0,
            position_opened=None,
        )


class _ApproveGate:
    def validate_proposal(self, proposal, account_state, current_positions, market_info):
        return types.SimpleNamespace(
            approved=True, reason="ok", checks_passed={}, metrics_snapshot={}
        )


def _targets(*specs):
    out = []
    for tid, login in specs:
        out.append(
            {
                "id": tid,
                "label": tid.upper(),
                "path": rf"C:\mt\{tid}\terminal64.exe",
                "account": {"login": login, "mode": "DEMO", "equity": 10000},
            }
        )
    return out


def _signal(signal_id="sig_B9", direction="BUY", symbol="XAUUSD"):
    return canonical_mod.make_canonical_signal(
        opportunity_id="opp_b9",
        symbol=symbol,
        direction=direction,
        entry_reference=2500.0,
        initial_SL=2495.0,
        initial_TP=2510.0,
        planned_RR=2.0,
        strategy_version="v1.0.0",
        signal_id=signal_id,
    )


class TestFanoutReattachPerAccount:
    def test_reattaches_per_account_then_restores(self, monkeypatch):
        rec = _RecordingConnector(attached=r"C:\mt\ORIGINAL\terminal64.exe")
        monkeypatch.setattr(
            fanout_mod.CanonicalFanout, "_load_connector", staticmethod(lambda: rec)
        )
        monkeypatch.setattr(
            fanout_mod.CanonicalFanout,
            "_current_attached_path",
            staticmethod(lambda: r"C:\mt\ORIGINAL\terminal64.exe"),
        )
        monkeypatch.setattr(
            fanout_mod.CanonicalFanout, "_clear_symbol_cache", staticmethod(lambda: None)
        )

        engine = _RecordingEngine(rec)
        coord = fanout_mod.CanonicalFanout(execution_engine=engine, risk_gate=_ApproveGate())
        targets = _targets(("a", "111"), ("b", "222"))

        out = coord.fan_out(_signal(), targets=targets, raw_proposal={"volume": 0.05})

        assert out["executed"] == 2 and out["failed"] == 0
        # Each order saw the binding attached to ITS OWN terminal.
        assert engine.sent[0]["account_id"] == "111"
        assert engine.sent[0]["attached"] == r"C:\mt\a\terminal64.exe"
        assert engine.sent[1]["account_id"] == "222"
        assert engine.sent[1]["attached"] == r"C:\mt\b\terminal64.exe"
        # Binding restored to the original terminal at the end.
        assert rec.calls[-1] == r"attach:C:\mt\ORIGINAL\terminal64.exe"
        assert rec._attached == r"C:\mt\ORIGINAL\terminal64.exe"

    def test_partial_attach_failure_keeps_other_account(self, monkeypatch):
        rec = _RecordingConnector(
            attached=r"C:\mt\ORIGINAL\terminal64.exe",
            fail_paths={r"C:\mt\b\terminal64.exe"},
        )
        monkeypatch.setattr(
            fanout_mod.CanonicalFanout, "_load_connector", staticmethod(lambda: rec)
        )
        monkeypatch.setattr(
            fanout_mod.CanonicalFanout,
            "_current_attached_path",
            staticmethod(lambda: r"C:\mt\ORIGINAL\terminal64.exe"),
        )
        monkeypatch.setattr(
            fanout_mod.CanonicalFanout, "_clear_symbol_cache", staticmethod(lambda: None)
        )

        engine = _RecordingEngine(rec)
        coord = fanout_mod.CanonicalFanout(execution_engine=engine, risk_gate=_ApproveGate())
        targets = _targets(("a", "111"), ("b", "222"))

        out = coord.fan_out(_signal(), targets=targets, raw_proposal={"volume": 0.05})

        by_acct = {r["account_id"]: r for r in out["accounts"]}
        assert by_acct["111"]["status"] == "FILLED"
        assert by_acct["222"]["status"] == "FAILED"
        assert "gagal attach" in by_acct["222"]["reason"].lower()
        # A's order still went through and the binding was restored.
        assert engine.sent[0]["account_id"] == "111"
        assert rec._attached == r"C:\mt\ORIGINAL\terminal64.exe"

    def test_pathless_target_skips_reattach(self, monkeypatch):
        """A path-less (test-double) target must not trigger re-attach."""
        rec = _RecordingConnector(attached=r"C:\mt\ORIGINAL\terminal64.exe")
        monkeypatch.setattr(
            fanout_mod.CanonicalFanout, "_load_connector", staticmethod(lambda: rec)
        )
        monkeypatch.setattr(
            fanout_mod.CanonicalFanout,
            "_current_attached_path",
            staticmethod(lambda: r"C:\mt\ORIGINAL\terminal64.exe"),
        )
        engine = _RecordingEngine(rec)
        coord = fanout_mod.CanonicalFanout(execution_engine=engine, risk_gate=_ApproveGate())
        targets = [{"id": "a", "account": {"login": "111", "mode": "DEMO", "equity": 10000}}]

        out = coord.fan_out(_signal(), targets=targets, raw_proposal={"volume": 0.05})
        assert out["executed"] == 1
        # No per-target attach happened (only the final restore to ORIGINAL).
        assert not any(c.startswith(r"attach:C:\mt\a") for c in rec.calls)
        assert rec.calls == ["shutdown", r"attach:C:\mt\ORIGINAL\terminal64.exe"]


# ===========================================================================
# 4. execution_permitted() gate (verify, code already enforces it)
# ===========================================================================
class TestExecutionPermittedGate:
    def _run_with_attached(self, monkeypatch, tmp_path, attached_folder):
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: attached_folder)

    def test_true_when_binding_attached_to_an_armed_terminal(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_MULTI)
        monkeypatch.setattr(terminals, "scan_running_terminals", _three_running())
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\A")
        _mark_verified(r"C:\mt\A", r"C:\mt\B", r"C:\mt\C")
        assert terminals.arm_terminal("a", True)["ok"] is True
        assert terminals.arm_terminal("b", True)["ok"] is True
        # Binding attached to A (armed) → permitted even though B is armed too.
        assert terminals.execution_permitted() is True

    def test_false_when_binding_attached_to_non_armed(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_MULTI)
        monkeypatch.setattr(terminals, "scan_running_terminals", _three_running())
        # Attach to C BEFORE arming; then arm A/B and point attachment at C.
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\C")
        _mark_verified(r"C:\mt\A", r"C:\mt\B", r"C:\mt\C")
        assert terminals.arm_terminal("a", True)["ok"] is True
        # C is NOT armed → the gate must fail closed.
        assert terminals.execution_permitted() is False

    def test_false_when_armed_terminal_stops_running(self, monkeypatch, tmp_path):
        _use_config(monkeypatch, tmp_path, CONFIG_MULTI)
        monkeypatch.setattr(terminals, "scan_running_terminals", _three_running())
        monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\A")
        _mark_verified(r"C:\mt\A", r"C:\mt\B", r"C:\mt\C")
        assert terminals.arm_terminal("a", True)["ok"] is True
        assert terminals.execution_permitted() is True
        # A stops running → dropped from the armed list → gate fails closed.
        monkeypatch.setattr(terminals, "scan_running_terminals", lambda: [])
        assert terminals.execution_permitted() is False


# ===========================================================================
# 5/6. Pipeline single-path >1 armed fail-closed
# ===========================================================================
class _StubSupervisor:
    def __init__(self, proposal, signal_id="sig_b9"):
        self._proposal = proposal
        self._signal_id = signal_id
        self.calls = 0

    def analyze(self, context):
        self.calls += 1
        return {
            "overall_confidence": 0.9,
            "summary": "stub",
            "agent_results": {},
            "signal_id": self._signal_id,
            "committee_record": {"signal_id": self._signal_id},
            "proposal": dict(self._proposal),
        }


def _buy_proposal():
    return {
        "symbol": "XAUUSD",
        "direction": "BUY",
        "confidence": 0.9,
        "entry_price": 2500.0,
        "stop_loss": 2495.0,
        "take_profit": 2510.0,
        "size": 0.10,
    }


class _CountingEngine:
    def __init__(self):
        self.calls = 0

    def execute_order(self, request):
        self.calls += 1
        return types.SimpleNamespace(
            success=True,
            ticket=1,
            error_code=0,
            error_message="",
            retries=0,
            position_opened=None,
        )


class TestPipelineMultiArmSinglePath:
    def test_two_armed_fails_closed_without_engine_call(self, monkeypatch):
        engine = _CountingEngine()
        pipe = pipeline_mod.TradingPipeline(
            supervisor=_StubSupervisor(_buy_proposal()),
            risk_gate=_ApproveGate(),
            execution_engine=engine,
            freshness_gate_enabled=False,
        )
        monkeypatch.setattr(terminals, "get_armed_terminals", lambda: ["a", "b"])

        result = pipe.run({"event_id": "eB9", "event_type": "BREAKOUT"}, {"symbol": "XAUUSD"})

        assert result.executed is False
        assert engine.calls == 0  # no order was sent
        assert "MULTIPLE TERMINALS ARMED" in (result.execution_result.get("error_message") or "")

    def test_one_armed_uses_normal_single_path(self, monkeypatch):
        engine = _CountingEngine()
        pipe = pipeline_mod.TradingPipeline(
            supervisor=_StubSupervisor(_buy_proposal()),
            risk_gate=_ApproveGate(),
            execution_engine=engine,
            freshness_gate_enabled=False,
        )
        monkeypatch.setattr(terminals, "get_armed_terminals", lambda: ["a"])

        result = pipe.run({"event_id": "eB9", "event_type": "BREAKOUT"}, {"symbol": "XAUUSD"})
        assert result.executed is True
        assert engine.calls == 1

    def test_zero_armed_uses_normal_single_path(self, monkeypatch):
        engine = _CountingEngine()
        pipe = pipeline_mod.TradingPipeline(
            supervisor=_StubSupervisor(_buy_proposal()),
            risk_gate=_ApproveGate(),
            execution_engine=engine,
            freshness_gate_enabled=False,
        )
        monkeypatch.setattr(terminals, "get_armed_terminals", lambda: [])
        pipe.run({"event_id": "eB9", "event_type": "BREAKOUT"}, {"symbol": "XAUUSD"})
        assert engine.calls == 1

    def test_fanout_on_is_not_blocked_by_multi_arm(self, monkeypatch):
        class _FanEngine:
            def __init__(self):
                self.calls = 0

            def execute_order_fanout(self, request, *, risk_price=0.0, tp_price=0.0, targets=None):
                self.calls += 1
                return types.SimpleNamespace(
                    any_success=True,
                    results=[{"success": True, "ticket": 1}],
                    succeeded=1,
                    failed=0,
                    target_count=1,
                )

        fan_engine = _FanEngine()
        pipe = pipeline_mod.TradingPipeline(
            supervisor=_StubSupervisor(_buy_proposal()),
            risk_gate=_ApproveGate(),
            execution_engine=fan_engine,
            fanout_enabled=True,
            freshness_gate_enabled=False,
        )
        monkeypatch.setattr(terminals, "get_armed_terminals", lambda: ["a", "b"])

        result = pipe.run({"event_id": "eB9", "event_type": "BREAKOUT"}, {"symbol": "XAUUSD"})
        # The fan-out path is used (not blocked by the >1-armed single-path guard).
        assert fan_engine.calls == 1
        assert result.executed is True
