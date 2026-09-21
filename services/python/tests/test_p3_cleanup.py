# -*- coding: utf-8 -*-
"""Tests for P3 cleanup items from the deep E2E audit."""

from __future__ import annotations

import time

from execution.order_builder import ExecutionRecoveryEngine, MismatchEvent


# ---------------------------------------------------------------------------
# P3-1 — MismatchEvent.timestamp is a real epoch float
# ---------------------------------------------------------------------------
def test_mismatch_event_timestamp_is_epoch_float():
    before = time.time()
    event = MismatchEvent(symbol="EURUSD", mismatch_type="X", internal_val=1, broker_val=2)
    after = time.time()
    assert isinstance(event.timestamp, float)
    # A real recent epoch, not a format string or 0.0.
    assert before <= event.timestamp <= after


# ---------------------------------------------------------------------------
# P3-2 — SL/TP mismatch detection (docstring now matches the code)
# ---------------------------------------------------------------------------
def test_sl_mismatch_detected():
    engine = ExecutionRecoveryEngine()
    internal = [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.10, "tp": 1.20}]
    broker = [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.15, "tp": 1.20}]
    events = engine.audit_reconciliation(internal, broker)
    assert any(e.mismatch_type == "SL_MISMATCH" for e in events)


def test_tp_mismatch_detected():
    engine = ExecutionRecoveryEngine()
    internal = [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.10, "tp": 1.20}]
    broker = [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.10, "tp": 1.30}]
    events = engine.audit_reconciliation(internal, broker)
    assert any(e.mismatch_type == "TP_MISMATCH" for e in events)


def test_matching_sltp_produces_no_mismatch():
    engine = ExecutionRecoveryEngine()
    internal = [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.10, "tp": 1.20}]
    broker = [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.10, "tp": 1.20}]
    events = engine.audit_reconciliation(internal, broker)
    assert events == []


# ---------------------------------------------------------------------------
# P3-3 — symbol suffix resolution in the execution engine
# ---------------------------------------------------------------------------
def test_engine_resolves_symbol_via_resolver(monkeypatch):
    """The engine routes symbol lookups through the broker resolver."""
    from execution.engine import ExecutionEngine

    engine = ExecutionEngine()

    import sys
    import types

    fake = types.ModuleType("mt5.symbol_resolver")
    fake.resolve_symbol = lambda base: f"{base}c"  # broker-suffixed variant
    monkeypatch.setitem(sys.modules, "mt5.symbol_resolver", fake)

    assert engine._resolve_symbol("xauusd") == "XAUUSDC"


def test_engine_resolve_symbol_falls_back_to_upper(monkeypatch):
    """When the resolver is unavailable the input is upper-cased unchanged."""
    from execution.engine import ExecutionEngine

    engine = ExecutionEngine()
    assert engine._resolve_symbol("  eurusd ") == "EURUSD"


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
