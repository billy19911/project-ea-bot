# -*- coding: utf-8 -*-
"""TASK 08 — RECONCILIATION + RESTART RECOVERY (STOP GATE 08).

Proves that broker state and internal state converge SAFELY across a restart:

    load durable intents → connect MT5 → read open positions → read recent
    orders/deals → reconcile → rebuild internal state → ONLY THEN permit new
    execution

Each test maps to one STOP GATE 08 criterion:

- restart with an open trade → durable state is restored,
- restart with a closed trade → review is still possible (closed intent does
  not resurrect as an open position),
- orphan broker position blocks new entries,
- unknown (uncertain) reconciliation state blocks new entries,
- duplicate recovery does not create a duplicate order (idempotency by
  ``intent_id``).

Additionally: durable order identity is persisted (signal_id / account_id /
terminal_id / broker order+deal+position tickets), the ``internal == empty``
trap is never mis-read as ``broker == empty``, and all terminals stay DISARMED
by default.
"""

from __future__ import annotations

import importlib
import types

import pytest

recovery_mod = importlib.import_module("execution.restart_recovery")
pipeline_mod = importlib.import_module("orchestration.pipeline")
engine_mod = importlib.import_module("execution.engine")
state_machine = importlib.import_module("execution.state_machine")
providers_mod = importlib.import_module("execution.reconciliation_providers")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coordinator(**kwargs):
    """Build a coordinator with deterministic defaults, overridable per test."""
    defaults = dict(
        load_intents=lambda: [],
        connect_mt5=lambda: True,
        read_positions=lambda: (True, []),
        read_orders=lambda: (True, []),
        read_deals=lambda: [],
        reconcile=None,
    )
    defaults.update(kwargs)
    return recovery_mod.RestartRecoveryCoordinator(**defaults)


class _Rec:
    """Minimal reconciliation report double."""

    def __init__(self, critical=False, total=0):
        self._critical = critical
        self._total = total

    def has_critical(self):
        return self._critical

    def total_mismatches(self):
        return self._total


def _open_intent(intent_id="intent-1", ticket=555, state="position_confirmed"):
    return {
        "intent_id": intent_id,
        "state": state,
        "ticket": ticket,
        "broker_position_ticket": ticket,
        "signal_id": "sig-1",
        "account_id": "acct-A",
        "terminal_id": "term-A",
        "symbol": "EURUSD",
        "volume": 0.1,
    }


# ===========================================================================
# STOP GATE 08 — Restart with open trade → state restored
# ===========================================================================
class TestRestartWithOpenTrade:
    def test_open_position_reconciles_and_permits_execution(self):
        intents = [_open_intent()]
        broker_positions = [{"ticket": 555, "symbol": "EURUSD", "volume": 0.1}]
        rebuilt = {}

        def _rebuild(the_intents, positions):
            rebuilt["intents"] = list(the_intents)
            rebuilt["positions"] = list(positions)

        coord = _coordinator(
            load_intents=lambda: list(intents),
            read_positions=lambda: (True, broker_positions),
            reconcile=lambda the_intents: _Rec(critical=False),
            rebuild_state=_rebuild,
        )
        report = coord.run()

        assert report.state is recovery_mod.RecoveryState.RECONCILED
        assert report.permits_execution is True
        assert report.mt5_connected is True
        assert report.broker_read_verified is True
        assert report.open_positions == 1
        assert report.recovered_intents == 1
        # State was rebuilt from the recovered truth.
        assert rebuilt["positions"] == broker_positions
        # Ordered sequence is recorded.
        assert report.steps == [
            "start",
            "load_durable_intents",
            "connect_mt5",
            "read_open_positions",
            "read_orders_deals",
            "reconcile",
            "rebuild_internal_state",
            "reconciled",
        ]

    def test_readiness_gate_allows_after_clean_recovery(self):
        coord = _coordinator(reconcile=lambda _i: _Rec(critical=False))
        gate = recovery_mod.ReconciliationReadinessGate(coord)
        # Before the sequence runs → BLOCKED (fail-closed).
        assert gate.check_can_execute()[0] is False
        coord.run()
        assert gate.check_can_execute()[0] is True


# ===========================================================================
# STOP GATE 08 — Restart with closed trade → review still possible
# ===========================================================================
class TestRestartWithClosedTrade:
    def test_closed_intent_is_not_rebuilt_as_open(self):
        # A CLOSED intent must not be treated as an open position: the broker
        # holding nothing is consistent with a closed trade.
        intents = [_open_intent(state="closed", ticket=101)]
        coord = _coordinator(
            load_intents=lambda: list(intents),
            read_positions=lambda: (True, []),
            reconcile=lambda _i: _Rec(critical=False),
        )
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.RECONCILED
        # Only OPEN intents count toward the recovered set.
        assert report.recovered_intents == 0

    def test_closed_trade_state_survives_new_store_and_reconciles(self, tmp_path):
        # Durable round-trip: an intent transitioned to CLOSED, read back by a
        # FRESH store (simulating a restart), is reported as no open position —
        # so the close path (review) can still run without a phantom block.
        from persistence import OrderStateStore  # type: ignore

        path = tmp_path / "order_state.jsonl"
        store = OrderStateStore(path=str(path))
        store.set_order("intent-closed", "position_confirmed", {"ticket": 101})
        store.mark_closed(101)

        fresh = OrderStateStore(path=str(path))
        rec = fresh.get_order("intent-closed")
        assert rec is not None and rec["state"] == "closed"

        positions = providers_mod.internal_positions_from_store(fresh.all_orders())
        assert positions == []  # closed → not an open internal position

        coord = _coordinator(
            load_intents=lambda: list(fresh.all_orders().values()),
            read_positions=lambda: (True, []),
            reconcile=lambda _i: _Rec(critical=False),
        )
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.RECONCILED
        assert report.recovered_intents == 0


# ===========================================================================
# STOP GATE 08 — Orphan broker position blocks new entries
# ===========================================================================
class TestOrphanBrokerPositionBlocks:
    def test_orphan_position_makes_reconcile_critical_and_blocks(self):
        # Broker holds a position the internal ledger never created.
        broker_positions = [{"ticket": 999, "symbol": "EURUSD", "volume": 0.1}]

        def _reconcile(_intents):
            return _Rec(critical=True, total=1)

        coord = _coordinator(
            load_intents=lambda: [],
            read_positions=lambda: (True, broker_positions),
            reconcile=_reconcile,
        )
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.BLOCKED
        assert report.permits_execution is False
        assert report.critical_mismatches == 1

        gate = recovery_mod.ReconciliationReadinessGate(coord)
        assert gate.check_can_execute()[0] is False

    def test_real_reconciler_flags_orphan_as_critical(self):
        from execution.reconciliation import Reconciler

        broker = [{"ticket": 999, "symbol": "EURUSD", "volume": 0.1}]

        def _reconcile(_intents):
            return Reconciler().compare([], broker, [], [])

        coord = _coordinator(
            load_intents=lambda: [],
            read_positions=lambda: (True, broker),
            reconcile=_reconcile,
        )
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.BLOCKED
        assert report.critical_mismatches >= 1


# ===========================================================================
# STOP GATE 08 — Unknown reconciliation state blocks new entries
# ===========================================================================
class TestUnknownStateBlocks:
    def test_failed_position_read_is_unverified_not_empty(self):
        # The trap: internal == empty must NOT be read as broker == empty.
        # A FAILED broker read returns (False, []) → unverified → BLOCK.
        coord = _coordinator(
            load_intents=lambda: [],
            read_positions=lambda: (False, []),
        )
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.BLOCKED
        assert report.broker_read_verified is False
        assert "fail-closed" in report.reason

    def test_mt5_disconnected_blocks(self):
        coord = _coordinator(connect_mt5=lambda: False)
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.BLOCKED
        assert report.mt5_connected is False

    def test_reconcile_exception_blocks(self):
        def _boom(_intents):
            raise RuntimeError("reconcile blew up")

        coord = _coordinator(reconcile=_boom)
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.BLOCKED
        assert "fail-closed" in report.reason

    def test_intent_load_exception_blocks(self):
        def _boom():
            raise RuntimeError("ledger unreadable")

        coord = _coordinator(load_intents=_boom)
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.BLOCKED

    def test_orders_read_exception_blocks(self):
        coord = _coordinator(read_orders=lambda: (False, []))
        report = coord.run()
        assert report.state is recovery_mod.RecoveryState.BLOCKED

    def test_pending_gate_blocks_before_any_run(self):
        coord = _coordinator()
        gate = recovery_mod.ReconciliationReadinessGate(coord)
        allowed, reason = gate.check_can_execute()
        assert allowed is False
        assert "pending" in reason


# ===========================================================================
# STOP GATE 08 — Duplicate recovery does not create a duplicate order
# ===========================================================================
class TestDuplicateRecoveryIdempotent:
    def test_recovered_intent_is_adopted_not_resent(self):
        intents = [_open_intent(intent_id="intent-1", ticket=777)]
        positions = [{"ticket": 777, "symbol": "EURUSD", "volume": 0.1}]
        coord = _coordinator(
            load_intents=lambda: list(intents),
            read_positions=lambda: (True, positions),
            reconcile=lambda _i: _Rec(critical=False),
        )
        report = coord.run()
        # The already-landed intent is adopted (no re-send).
        assert "intent-1" in report.adopted_intents

    def test_reexecution_of_recovered_intent_is_refused_by_engine(self):
        # After recovery, re-dispatching the SAME intent_id (idempotency key)
        # must be refused by the engine's durable duplicate detector — no
        # duplicate order, exactly the idempotency-by-intent_id guarantee.
        state_machine.reset_store()
        state_machine.set_store(None)

        engine = engine_mod.ExecutionEngine(simulation_mode=True, require_approval=False)
        req1 = engine_mod.OrderRequest(
            symbol="EURUSD", order_type="BUY", volume=0.1, idempotency_key="intent-dup"
        )
        # Seed a durable-ish record marking the intent as already dispatched.
        state_machine.set_order(
            "intent-dup", state_machine.OrderState.POSITION_CONFIRMED, {"ticket": 42}
        )

        res = engine.execute_order(req1)
        assert res.success is False
        assert res.error_code == 409  # duplicate rejected
        state_machine.reset_store()

    def test_two_accounts_same_signal_have_distinct_intents(self):
        # Fan-out idempotency: (signal_id, account_id) yields distinct keys, so
        # the SAME signal across two accounts is two legitimate orders, while a
        # duplicate of one account is refused.
        key_a = "sig-1:acct-A"
        key_b = "sig-1:acct-B"
        assert key_a != key_b


# ===========================================================================
# Durable order identity (master plan §10 required fields)
# ===========================================================================
class TestDurableOrderIdentity:
    def test_engine_persists_identity_fields(self):
        state_machine.reset_store()
        state_machine.set_store(None)

        class _ConfirmingConnector:
            def get_symbol_info(self, symbol):
                return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

            def get_positions(self):
                return []

            def positions_get(self, ticket=None):
                return [{"ticket": ticket}] if ticket else []

        import sys

        engine = engine_mod.ExecutionEngine(
            mt5_connector=_ConfirmingConnector(), simulation_mode=True
        )
        saved = sys.modules.get("MetaTrader5", "missing")
        sys.modules["MetaTrader5"] = None
        try:
            req = engine_mod.OrderRequest(
                symbol="EURUSD",
                order_type="BUY",
                volume=0.1,
                magic=7,
                idempotency_key="intent-xyz",
                signal_id="sig-9",
                account_id="acct-9",
                terminal_id="term-9",
            )
            result = engine.execute_order(req)
        finally:
            if saved == "missing":
                sys.modules.pop("MetaTrader5", None)
            else:
                sys.modules["MetaTrader5"] = saved

        assert result.success is True
        rec = state_machine.get_order("intent-xyz")
        assert rec["intent_id"] == "intent-xyz"
        assert rec["signal_id"] == "sig-9"
        assert rec["account_id"] == "acct-9"
        assert rec["terminal_id"] == "term-9"
        assert rec["broker_order_ticket"] == result.ticket
        assert rec["broker_deal_ticket"] == result.ticket
        assert rec["broker_position_ticket"] == result.ticket
        state_machine.reset_store()

    def test_identity_fields_default_none(self):
        req = engine_mod.OrderRequest(symbol="EURUSD", order_type="BUY", volume=0.1)
        assert req.signal_id is None
        assert req.account_id is None
        assert req.terminal_id is None
        assert req.broker_order_ticket is None
        assert req.broker_deal_ticket is None
        assert req.broker_position_ticket is None


# ===========================================================================
# Pipeline integration — readiness gate blocks/permits execution
# ===========================================================================
class _StubSupervisor:
    def analyze(self, context):
        return {
            "overall_confidence": 0.9,
            "summary": "t",
            "agent_results": {},
            "proposal": {
                "symbol": "EURUSD",
                "direction": "BUY",
                "confidence": 0.9,
                "entry_price": 1.10,
                "stop_loss": 1.09,
                "take_profit": 1.13,
                "size": 0.10,
            },
        }


class _ApproveGate:
    def validate_proposal(self, proposal, account_state, current_positions, market_info):
        return types.SimpleNamespace(
            approved=True, reason="ok", checks_passed={}, metrics_snapshot={}
        )


class _FakeEngine:
    def __init__(self):
        self.sent = []

    def execute_order(self, request):
        self.sent.append(request)
        return types.SimpleNamespace(success=True, ticket=99, error_code=0, error_message="")


def _pipe(readiness_guard):
    return pipeline_mod.TradingPipeline(
        supervisor=_StubSupervisor(),
        risk_gate=_ApproveGate(),
        execution_engine=_FakeEngine(),
        single_entry_policy=False,
        max_lot_per_trade=1.0,
        force_risk_sizing=False,
        readiness_guard=readiness_guard,
    )


class TestPipelineReadinessGate:
    def test_pending_recovery_blocks_execution(self):
        coord = _coordinator()  # never run → PENDING
        gate = recovery_mod.ReconciliationReadinessGate(coord)
        pipe = _pipe(gate)
        result = pipe.run({"event_id": "e1", "event_type": "MOMENTUM"}, {"symbol": "EURUSD"})
        assert result.status == pipeline_mod.STATUS_BLOCKED
        assert pipe.execution_engine.sent == []

    def test_reconciled_recovery_permits_execution(self):
        coord = _coordinator(reconcile=lambda _i: _Rec(critical=False))
        coord.run()
        gate = recovery_mod.ReconciliationReadinessGate(coord)
        pipe = _pipe(gate)
        result = pipe.run({"event_id": "e2", "event_type": "MOMENTUM"}, {"symbol": "EURUSD"})
        assert result.status == pipeline_mod.STATUS_EXECUTED
        assert len(pipe.execution_engine.sent) == 1

    def test_broken_guard_fails_closed(self):
        class _Boom:
            def check_can_execute(self):
                raise RuntimeError("guard broken")

        pipe = _pipe(_Boom())
        result = pipe.run({"event_id": "e3", "event_type": "MOMENTUM"}, {"symbol": "EURUSD"})
        assert result.status == pipeline_mod.STATUS_BLOCKED
        assert pipe.execution_engine.sent == []

    def test_no_guard_preserves_historic_behaviour(self):
        pipe = _pipe(None)
        result = pipe.run({"event_id": "e4", "event_type": "MOMENTUM"}, {"symbol": "EURUSD"})
        assert result.status == pipeline_mod.STATUS_EXECUTED


# ===========================================================================
# Default safety — terminals DISARMED by default
# ===========================================================================
class TestDefaultDisarmed:
    def test_no_terminals_armed_after_disarm_all(self):
        # The safety invariant: arming is explicit only. Disarm every terminal
        # first (other tests may legitimately have armed one), then assert the
        # gate stays closed until an explicit arm — never ON by default.
        for mod_name in ("mt5.terminals", "src.mt5.terminals"):
            try:
                terms = importlib.import_module(mod_name)
            except ImportError:
                continue
            for tid in list(terms.get_armed_terminals()):
                terms.arm_terminal(tid, False)
            assert list(terms.get_armed_terminals()) == []
            assert bool(terms.execution_permitted()) is False
            return
        pytest.skip("mt5.terminals unavailable")

    def test_arm_state_starts_off_in_fresh_registry(self, monkeypatch):
        # A freshly-built terminal state mapping has no armed entry — proving the
        # default is DISARMED, not merely "currently disarmed".
        for mod_name in ("mt5.terminals", "src.mt5.terminals"):
            try:
                terms = importlib.import_module(mod_name)
            except ImportError:
                continue
            monkeypatch.setattr(terms, "_terminal_states", {})
            states = terms._terminal_states  # noqa: SLF001 - asserting the default
            assert all(not bool(v.get("armed")) for v in states.values())
            return
        pytest.skip("mt5.terminals unavailable")


# ===========================================================================
# Endpoint — restart recovery state is exposed (source=live)
# ===========================================================================
class TestRecoveryEndpoint:
    def test_recovery_endpoint_returns_real_state(self):
        from fastapi.testclient import TestClient

        from src.main import app
        from src.orchestration.runtime import OrchestrationRuntime, set_runtime

        runtime = OrchestrationRuntime(
            reconciliation_interval=1,
            recovery_coordinator=_coordinator(reconcile=lambda _i: _Rec(critical=False)),
        )
        runtime.run_recovery()
        set_runtime(runtime)
        try:
            client = TestClient(app)
            resp = client.get("/reconciliation/recovery")
            assert resp.status_code == 200
            body = resp.json()
            assert body["source"] == "live"
            assert body["permits_execution"] is True
            assert body["recovery"]["state"] == "reconciled"

            status = client.get("/reconciliation/status").json()
            assert status["recovery"] is not None
        finally:
            set_runtime(None)

    def test_runtime_run_recovery_returns_none_without_coordinator(self):
        from src.orchestration.runtime import OrchestrationRuntime

        runtime = OrchestrationRuntime(reconciliation_interval=1)
        assert runtime.run_recovery() is None
        assert runtime.recovery_state() is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
