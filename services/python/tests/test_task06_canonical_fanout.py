# -*- coding: utf-8 -*-
"""TASK 06 — MULTI-MT5 / ONE SIGNAL → MANY ACCOUNTS (STOP GATE 06).

Proves the exact desired trading model::

    1 Supervisor → 1 Committee → 1 Canonical Signal → N MT5 Accounts

with deterministic per-account broker normalization and a per-account Risk
Gate. No real MT5 terminal is needed: the execution engine and risk gate are
fakes injected into the coordinator / pipeline. Each test maps to one STOP GATE
06 criterion (documented in the test docstring / name).
"""

from __future__ import annotations

import importlib
import types

import pytest

canonical_mod = importlib.import_module("trading.canonical_signal")
fanout_mod = importlib.import_module("execution.fanout")
pipeline_mod = importlib.import_module("orchestration.pipeline")


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_ledger(monkeypatch):
    fanout_mod.set_fanout_ledger(fanout_mod.FanoutLedger())
    # B-9 Lanjutan: fan-out now re-attaches the process-wide binding per account.
    # These are headless tests (no MetaTrader5), so stub the connector so the
    # synthetic re-attach is a no-op success — the per-account routing itself is
    # verified by tests/test_b9_multi_arm_hardening.py with a recording connector.
    try:
        connector = importlib.import_module("mt5.connector")
        monkeypatch.setattr(connector, "shutdown", lambda: None)
        monkeypatch.setattr(connector, "use_live_data_mode", lambda path=None: True)
    except Exception:  # pragma: no cover - connector module always importable
        pass
    yield
    fanout_mod.set_fanout_ledger(fanout_mod.FanoutLedger())


class FakeGate:
    """Deterministic per-account risk gate for tests.

    Approves only accounts whose login is in ``approved_logins`` — unless
    ``by_equity`` is set, in which case it approves accounts above a min equity
    (used to prove the gate runs on that account's OWN state).
    """

    def __init__(self, approved_logins=None, min_equity=None):
        self.approved_logins = set(approved_logins or [])
        self.min_equity = min_equity
        self.calls: list[dict] = []

    def validate_proposal(self, proposal, account_state, current_positions, market_info):
        self.calls.append({"account_state": account_state, "proposal": proposal})
        if self.min_equity is not None:
            ok = float(account_state.get("equity") or 0.0) >= self.min_equity
            reason = "equity OK" if ok else "equity below minimum"
        else:
            ok = account_state.get("login") in self.approved_logins
            reason = "approved by test gate" if ok else "rejected by test gate"
        return types.SimpleNamespace(
            approved=ok, reason=reason, checks_passed={}, metrics_snapshot={}
        )


class FakeEngine:
    """Records the orders it is asked to send (one per account)."""

    def __init__(self, fail_symbols=None):
        self.sent: list[object] = []
        self.fail_symbols = set(fail_symbols or [])

    def execute_order(self, request):
        self.sent.append(request)
        symbol = getattr(request, "symbol", "")
        ok = symbol not in self.fail_symbols
        return types.SimpleNamespace(
            success=ok,
            ticket=len(self.sent) if ok else None,
            error_code=0 if ok else 10004,
            error_message="" if ok else f"rejected {symbol}",
        )


def _targets(*specs):
    """Build fan-out target dicts from ``(id, login, mode, equity)`` tuples."""
    out = []
    for tid, login, mode, equity in specs:
        out.append(
            {
                "id": tid,
                "label": tid.upper(),
                "path": rf"C:\mt\{tid}\terminal64.exe",
                "account": {"login": login, "mode": mode, "equity": equity},
            }
        )
    return out


def _signal(signal_id="sig_S1", direction="BUY", symbol="XAUUSD"):
    return canonical_mod.make_canonical_signal(
        opportunity_id="opp_1",
        symbol=symbol,
        direction=direction,
        entry_reference=2500.0,
        initial_SL=2495.0,
        initial_TP=2510.0,
        planned_RR=2.0,
        strategy_version="v1.0.0",
        signal_id=signal_id,
    )


def _coordinator(engine, gate, ledger=None, targets=None):
    return fanout_mod.CanonicalFanout(
        execution_engine=engine,
        risk_gate=gate,
        targets_provider=(lambda: list(targets)) if targets is not None else None,
        ledger=ledger or fanout_mod.FanoutLedger(),
    )


# ---------------------------------------------------------------------------
# Canonical signal model
# ---------------------------------------------------------------------------
def test_canonical_signal_is_immutable_and_has_all_fields():
    """The signal object is frozen and carries every required field."""
    sig = _signal()
    required = {
        "signal_id",
        "opportunity_id",
        "symbol",
        "direction",
        "entry_reference",
        "initial_SL",
        "initial_TP",
        "planned_RR",
        "risk_policy",
        "strategy_version",
        "created_at",
        "evidence_hash",
    }
    assert required <= set(sig.to_dict().keys())
    # Frozen: cannot mutate a field.
    with pytest.raises(Exception):
        sig.symbol = "EURUSD"  # type: ignore[misc]


def test_signal_id_is_deterministic_for_same_identity():
    """The same opportunity identity always yields the same signal_id."""
    a = canonical_mod.make_canonical_signal(
        opportunity_id="opp_9",
        symbol="XAUUSD",
        direction="BUY",
        entry_reference=2500.0,
        initial_SL=2495.0,
        initial_TP=2510.0,
        planned_RR=2.0,
        strategy_version="v1",
    )
    b = canonical_mod.make_canonical_signal(
        opportunity_id="opp_9",
        symbol="XAUUSD",
        direction="BUY",
        entry_reference=2500.0,
        initial_SL=2495.0,
        initial_TP=2510.0,
        planned_RR=2.0,
        strategy_version="v1",
    )
    assert a.signal_id == b.signal_id


# ---------------------------------------------------------------------------
# STOP GATE 06 — 2+ demo terminals receive the SAME signal_id
# ---------------------------------------------------------------------------
def test_two_demo_terminals_receive_same_signal_id():
    engine = FakeEngine()
    gate = FakeGate(approved_logins={"111", "222"})
    coord = _coordinator(engine, gate)
    sig = _signal(signal_id="sig_S1")
    targets = _targets(("a", "111", "DEMO", 10000), ("b", "222", "DEMO", 8000))

    out = coord.fan_out(sig, targets=targets)

    assert out["executed"] == 2
    assert out["signal_status"] == canonical_mod.SignalStatus.EXECUTED_ALL
    ids = {row["signal_id"] for row in out["accounts"]}
    assert ids == {"sig_S1"}  # SAME id for every account
    assert len(engine.sent) == 2


# ---------------------------------------------------------------------------
# STOP GATE 06 — one account rejection does NOT create a second signal
# ---------------------------------------------------------------------------
def test_one_rejection_does_not_create_a_second_signal():
    """A approved / B rejected / C approved → exactly ONE signal, B REJECTED."""
    engine = FakeEngine()
    gate = FakeGate(approved_logins={"111", "333"})  # B (222) rejected
    ledger = fanout_mod.FanoutLedger()
    coord = _coordinator(engine, gate, ledger)
    sig = _signal(signal_id="sig_S1")
    targets = _targets(
        ("a", "111", "DEMO", 10000),
        ("b", "222", "DEMO", 5000),
        ("c", "333", "DEMO", 20000),
    )

    out = coord.fan_out(sig, targets=targets)

    assert out["executed"] == 2 and out["rejected"] == 1 and out["failed"] == 0
    assert out["signal_status"] == canonical_mod.SignalStatus.PARTIALLY_EXECUTED
    # ONLY ONE signal exists — B's rejection did not spawn another.
    assert len(ledger.all_signals()) == 1
    assert ledger.get_signal("sig_S1") is not None
    # B is recorded under the SAME signal_id with status REJECTED + reason.
    b = ledger.get_account_dispatch("sig_S1", "222")
    assert b is not None
    assert b.signal_id == "sig_S1"
    assert b.status == canonical_mod.AccountExecutionStatus.REJECTED
    assert b.reason  # a reason is always present


# ---------------------------------------------------------------------------
# STOP GATE 06 — one event creates one signal_id
# ---------------------------------------------------------------------------
def test_one_event_creates_one_signal_id_duplicate_fanout_is_idempotent():
    engine = FakeEngine()
    gate = FakeGate(approved_logins={"111", "222"})
    ledger = fanout_mod.FanoutLedger()
    coord = _coordinator(engine, gate, ledger)
    sig = _signal(signal_id="sig_S1")
    targets = _targets(("a", "111", "DEMO", 10000), ("b", "222", "DEMO", 8000))

    first = coord.fan_out(sig, targets=targets)
    assert first["executed"] == 2
    assert len(ledger.all_signals()) == 1

    # Re-registering the SAME signal id is idempotent.
    assert ledger.register_signal(sig) is False
    assert len(ledger.all_signals()) == 1
    assert len(engine.sent) == 2


# ---------------------------------------------------------------------------
# STOP GATE 06 — duplicate fan-out cannot duplicate orders
# ---------------------------------------------------------------------------
def test_duplicate_fanout_cannot_duplicate_orders():
    engine = FakeEngine()
    gate = FakeGate(approved_logins={"111", "222"})
    coord = _coordinator(engine, gate)
    sig = _signal(signal_id="sig_S1")
    targets = _targets(("a", "111", "DEMO", 10000), ("b", "222", "DEMO", 8000))

    coord.fan_out(sig, targets=targets)
    assert len(engine.sent) == 2
    second = coord.fan_out(sig, targets=targets)
    # No new orders: every (signal, account) is already terminal.
    assert second["duplicates"] == 2
    assert len(engine.sent) == 2
    assert second["executed"] == 0


# ---------------------------------------------------------------------------
# STOP GATE 06 — per-account risk is enforced
# ---------------------------------------------------------------------------
def test_per_account_risk_is_enforced_on_own_account_state():
    """The gate runs per account on that account's OWN equity, not a shared one."""
    engine = FakeEngine()
    gate = FakeGate(min_equity=9000.0)  # only accounts with equity ≥ 9000 pass
    ledger = fanout_mod.FanoutLedger()
    coord = _coordinator(engine, gate, ledger)
    sig = _signal()
    targets = _targets(
        ("a", "111", "DEMO", 10000),  # passes
        ("b", "222", "DEMO", 4000),  # fails its OWN gate
        ("c", "333", "DEMO", 20000),  # passes
    )

    out = coord.fan_out(sig, targets=targets)

    assert out["executed"] == 2 and out["rejected"] == 1
    # The gate was called once per account with that account's equity.
    equities = sorted(c["account_state"]["equity"] for c in gate.calls)
    assert equities == [4000.0, 10000.0, 20000.0]
    # Only two orders reached the engine.
    assert len(engine.sent) == 2


def test_per_account_risk_gate_fails_closed_on_error():
    engine = FakeEngine()

    class BoomGate:
        def validate_proposal(self, *a, **k):
            raise RuntimeError("gate exploded")

    coord = _coordinator(engine, BoomGate())
    out = coord.fan_out(_signal(), targets=_targets(("a", "111", "DEMO", 10000)))
    assert out["executed"] == 0
    assert out["rejected"] == 1  # fail-closed
    assert engine.sent == []


# ---------------------------------------------------------------------------
# STOP GATE 06 — broker normalization is per-account (signal unchanged)
# ---------------------------------------------------------------------------
def test_broker_normalization_is_per_account_signal_unchanged():
    """Each account gets its own symbol/volume; the canonical signal never changes."""
    engine = FakeEngine()
    gate = FakeGate(approved_logins={"111", "222"})

    # A per-terminal symbol resolver + order builder proving normalization.
    def resolver(symbol, target):
        # Broker B suffixes its symbols.
        return f"{symbol}c" if target.get("id") == "b" else symbol

    class Builder:
        def build_order_request(self, proposal, quote):
            vol = 0.05 if proposal["symbol"].endswith("c") else 0.10
            return types.SimpleNamespace(
                volume=vol,
                price=proposal["price"],
                sl=proposal["stop_loss"],
                tp=proposal["take_profit"],
                idempotency_key=proposal.get("client_order_id"),
            )

    coord = fanout_mod.CanonicalFanout(
        execution_engine=engine,
        risk_gate=gate,
        symbol_resolver=resolver,
        order_builder=Builder(),
    )
    sig = _signal(signal_id="sig_S1")
    before = sig.to_dict()
    targets = _targets(("a", "111", "DEMO", 10000), ("b", "222", "DEMO", 8000))

    out = coord.fan_out(sig, targets=targets)

    by_account = {r["account_id"]: r for r in out["accounts"]}
    assert by_account["111"]["symbol"] == "XAUUSD"
    assert by_account["222"]["symbol"] == "XAUUSDc"  # broker-normalized
    assert by_account["111"]["volume"] == 0.10
    assert by_account["222"]["volume"] == 0.05
    # The canonical signal is byte-identical after fan-out.
    assert sig.to_dict() == before


# ---------------------------------------------------------------------------
# STOP GATE 06 — no account can bypass the canonical signal
# ---------------------------------------------------------------------------
def test_no_account_can_bypass_the_canonical_signal():
    """Every order the coordinator emits carries the canonical signal_id."""
    engine = FakeEngine()
    gate = FakeGate(approved_logins={"111", "222", "333"})
    coord = _coordinator(engine, gate)
    sig = _signal(signal_id="sig_S1")
    targets = _targets(
        ("a", "111", "DEMO", 10000),
        ("b", "222", "DEMO", 8000),
        ("c", "333", "DEMO", 12000),
    )

    coord.fan_out(sig, targets=targets)

    assert len(engine.sent) == 3
    keys = set()
    for request in engine.sent:
        key = getattr(request, "idempotency_key", "")
        assert key.startswith("sig_S1:")  # the canonical signal_id travels with every order
        assert "sig_S1" in getattr(request, "comment", "")
        keys.add(key)
    # Each account gets a DISTINCT idempotency key so all three can send.
    assert len(keys) == 3


# ---------------------------------------------------------------------------
# STOP GATE 06 — live terminal configured but starts disarmed; arm is explicit
# ---------------------------------------------------------------------------
def test_live_terminal_configurable_but_starts_disarmed(tmp_path, monkeypatch):
    terminals = importlib.import_module("mt5.terminals")
    terminals._selected_id = None
    terminals._execution_armed = False
    terminals._terminal_states = {}
    terminals._mirror_selected = None
    terminals._mirror_armed = False

    cfg = tmp_path / "mt5_terminals.json"
    cfg.write_text(
        __import__("json").dumps(
            {
                "terminals": [
                    {
                        "id": "vito2",
                        "label": "LIVE",
                        "path": r"C:\mt\VITO2\terminal64.exe",
                        "execution": True,  # eligible
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(cfg))
    monkeypatch.setattr(
        terminals,
        "scan_running_terminals",
        lambda: [{"pid": 1, "exe": r"C:\mt\VITO2\terminal64.exe", "folder": r"C:\mt\VITO2"}],
    )

    view = terminals.list_terminals()
    entry = next(e for e in view["terminals"] if e["id"] == "vito2")
    # Configured and RUNNING, but DISARMED by default.
    assert entry["armable"] is True
    assert entry["armed"] is False
    # No armed terminals → nothing is a fan-out target.
    assert terminals.get_fanout_targets() == []
    assert terminals.is_execution_armed() is False


def test_arm_is_explicit_and_required_for_fanout(tmp_path, monkeypatch):
    terminals = importlib.import_module("mt5.terminals")
    terminals._selected_id = None
    terminals._execution_armed = False
    terminals._terminal_states = {}
    terminals._mirror_selected = None
    terminals._mirror_armed = False

    cfg = tmp_path / "mt5_terminals.json"
    cfg.write_text(
        __import__("json").dumps(
            {
                "terminals": [
                    {
                        "id": "bil2",
                        "label": "DEMO",
                        "path": r"C:\mt\BIL2\terminal64.exe",
                        "execution": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MT5_TERMINALS_CONFIG", str(cfg))
    monkeypatch.setattr(
        terminals,
        "scan_running_terminals",
        lambda: [{"pid": 2, "exe": r"C:\mt\BIL2\terminal64.exe", "folder": r"C:\mt\BIL2"}],
    )
    # Attached so arming is permitted.
    monkeypatch.setattr(terminals, "_detect_attached_path", lambda: r"C:\mt\BIL2")
    terminals._account_cache[terminals._norm(r"C:\mt\BIL2")] = {
        "login": 5001,
        "server": "Broker-Demo",
        "mode": "DEMO",
    }

    # Not armed → not a fan-out target.
    assert terminals.get_fanout_targets() == []
    # Explicit arm → now it is.
    res = terminals.arm_terminal("bil2", True)
    assert res["ok"] is True
    assert terminals.get_fanout_targets() and terminals.get_fanout_targets()[0]["id"] == "bil2"


# ---------------------------------------------------------------------------
# Pipeline integration — one analysis → canonical signal → fan-out
# ---------------------------------------------------------------------------
class _StubSupervisor:
    def __init__(self, proposal, signal_id="sig_committee"):
        self._proposal = proposal
        self._signal_id = signal_id
        self.calls = 0

    def analyze(self, context):
        self.calls += 1
        return {
            "overall_confidence": 0.9,
            "summary": "test",
            "agent_results": {},
            "signal_id": self._signal_id,
            "committee_record": {"signal_id": self._signal_id},
            "proposal": self._proposal,
        }


def _approved_gate():
    return types.SimpleNamespace(
        validate_proposal=lambda p, a, c, m: types.SimpleNamespace(
            approved=True, reason="ok", checks_passed={}, metrics_snapshot={}
        )
    )


def test_pipeline_creates_one_signal_and_fans_out_to_accounts():
    proposal = {
        "symbol": "XAUUSD",
        "direction": "BUY",
        "confidence": 0.9,
        "entry_price": 2500.0,
        "stop_loss": 2495.0,
        "take_profit": 2510.0,
        "size": 0.1,
    }
    supervisor = _StubSupervisor(proposal)
    engine = FakeEngine()
    gate = FakeGate(approved_logins={"111", "222"})
    coord = _coordinator(
        engine, gate, targets=_targets(("a", "111", "DEMO", 10000), ("b", "222", "DEMO", 8000))
    )

    pipe = pipeline_mod.TradingPipeline(
        supervisor=supervisor,
        risk_gate=_approved_gate(),
        fanout_coordinator=coord,
        order_builder=None,
        strategy_version="v1.0.0",
    )
    result = pipe.run({"event_id": "evt_1", "event_type": "MOMENTUM"}, {"symbol": "XAUUSD"})

    assert supervisor.calls == 1  # ONE supervisor analysis only
    assert result.signal_id  # a canonical signal was created
    assert result.canonical_signal.get("signal_id") == result.signal_id
    assert result.executed is True
    assert result.fanout is not None
    ids = {row["signal_id"] for row in result.fanout["accounts"]}
    assert ids == {result.signal_id}  # same signal_id for both accounts
    assert len(engine.sent) == 2


def test_pipeline_rejection_does_not_reanalyse():
    """A rejected account must not trigger a second supervisor analysis."""
    proposal = {
        "symbol": "XAUUSD",
        "direction": "BUY",
        "confidence": 0.9,
        "entry_price": 2500.0,
        "stop_loss": 2495.0,
        "take_profit": 2510.0,
        "size": 0.1,
    }
    supervisor = _StubSupervisor(proposal)
    engine = FakeEngine()
    gate = FakeGate(approved_logins={"111"})  # 222 rejected
    coord = _coordinator(
        engine, gate, targets=_targets(("a", "111", "DEMO", 10000), ("b", "222", "DEMO", 8000))
    )

    pipe = pipeline_mod.TradingPipeline(
        supervisor=supervisor,
        risk_gate=_approved_gate(),
        fanout_coordinator=coord,
        strategy_version="v1.0.0",
    )
    result = pipe.run({"event_id": "evt_1", "event_type": "MOMENTUM"}, {"symbol": "XAUUSD"})

    # Still exactly one analysis, one signal.
    assert supervisor.calls == 1
    assert len(coord.ledger.all_signals()) == 1
    assert result.fanout["executed"] == 1 and result.fanout["rejected"] == 1


def test_pipeline_without_coordinator_preserves_single_terminal_path():
    """Backward-compat: no coordinator → the historic dispatch path is used."""
    pipe = pipeline_mod.TradingPipeline(
        supervisor=types.SimpleNamespace(analyze=lambda ctx: {}),
        risk_gate=types.SimpleNamespace(),
    )
    assert pipe.fanout_coordinator is None


# ---------------------------------------------------------------------------
# Rollup statuses
# ---------------------------------------------------------------------------
def test_all_rejected_rolls_up_to_rejected_all():
    engine = FakeEngine()
    gate = FakeGate(approved_logins=set())  # everyone rejected
    ledger = fanout_mod.FanoutLedger()
    coord = _coordinator(engine, gate, ledger)
    out = coord.fan_out(
        _signal(), targets=_targets(("a", "111", "DEMO", 10000), ("b", "222", "DEMO", 5000))
    )
    assert out["signal_status"] == canonical_mod.SignalStatus.REJECTED_ALL
    assert out["executed"] == 0 and out["rejected"] == 2
    assert engine.sent == []


# ---------------------------------------------------------------------------
# Real ExecutionEngine integration — per-account idempotency
# ---------------------------------------------------------------------------
def test_real_engine_places_one_order_per_account_not_a_duplicate():
    """The real ExecutionEngine must send ONE order per account (distinct keys),
    and a duplicate fan-out must place NO new orders."""
    engine_mod = importlib.import_module("execution.engine")
    engine = engine_mod.ExecutionEngine(simulation_mode=True)
    gate = FakeGate(approved_logins={"111", "222"})
    order_builder = importlib.import_module("execution.order_builder").OrderBuilder()
    coord = fanout_mod.CanonicalFanout(
        execution_engine=engine, risk_gate=gate, order_builder=order_builder
    )
    sig = _signal(signal_id="sig_REAL")
    targets = _targets(("a", "111", "DEMO", 10000), ("b", "222", "DEMO", 8000))

    first = coord.fan_out(sig, targets=targets, raw_proposal={"volume": 0.05})
    # Both accounts executed — distinct per-account idempotency keys.
    assert first["executed"] == 2 and first["failed"] == 0
    # A duplicate fan-out is fully deduped before dispatch.
    second = coord.fan_out(sig, targets=targets, raw_proposal={"volume": 0.05})
    assert second["duplicates"] == 2
    assert second["executed"] == 0
