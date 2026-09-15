# -*- coding: utf-8 -*-
"""Test suite for EPIC 08.03 OrderBuilder and EPIC 08.07 ExecutionRecoveryEngine.

Tests cover:
- OrderBuilder.build_order_request() — schema mapping, normalization, defaults
- ExecutionRecoveryEngine — audit_reconciliation, is_execution_blocked, clear_recovery_block
"""

from __future__ import annotations

import pytest

from execution import (
    ExecutionEngine,
    ExecutionRecoveryEngine,
    OrderBuilder,
    OrderRequest,
    RecoveryState,
)

# ---------------------------------------------------------------------------
# OrderBuilder Tests
# ---------------------------------------------------------------------------


class TestOrderBuilderBasics:
    """Basic OrderBuilder instantiation and configuration."""

    def test_default_construction(self) -> None:
        """OrderBuilder constructs with sensible defaults."""
        builder = OrderBuilder()
        assert builder.default_magic == 70000
        assert builder.symbol_prefix == ""
        assert builder.symbol_suffix == ""

    def test_custom_construction(self) -> None:
        """OrderBuilder accepts custom prefix, suffix, magic."""
        builder = OrderBuilder(
            default_magic=99999,
            symbol_prefix="PRODIGY_",
            symbol_suffix=".FX",
        )
        assert builder.default_magic == 99999
        assert builder.symbol_prefix == "PRODIGY_"
        assert builder.symbol_suffix == ".FX"


class TestOrderBuilderBuild:
    """OrderBuilder.build_order_request() tests."""

    def test_build_basic_market_buy(self) -> None:
        """Build a basic market BUY order from a trade proposal."""
        builder = OrderBuilder()
        proposal = {
            "symbol": "eurusd",
            "side": "buy",
            "volume": 0.1,
            "sl": 1.0800,
            "tp": 1.0900,
            "magic": 12345,
        }
        req = builder.build_order_request(proposal)
        assert isinstance(req, OrderRequest)
        assert req.symbol == "EURUSD"
        assert req.order_type == "BUY"
        assert req.volume == 0.1
        assert req.sl == 1.0800
        assert req.tp == 1.0900
        assert req.magic == 12345

    def test_build_normalizes_symbol_to_uppercase(self) -> None:
        """Symbol should be normalized to uppercase + trimmed."""
        builder = OrderBuilder()
        proposal = {"symbol": "  gbpjpy ", "side": "buy", "volume": 0.5}
        req = builder.build_order_request(proposal)
        assert req.symbol == "GBPJPY"

    def test_build_applies_symbol_prefix(self) -> None:
        """Symbol prefix is added when missing."""
        builder = OrderBuilder(symbol_prefix="PRODIGY_")
        proposal = {"symbol": "EURUSD", "side": "buy", "volume": 0.1}
        req = builder.build_order_request(proposal)
        assert req.symbol == "PRODIGY_EURUSD"

    def test_build_does_not_double_prefix(self) -> None:
        """Existing prefix is not duplicated."""
        builder = OrderBuilder(symbol_prefix="PRODIGY_")
        proposal = {"symbol": "PRODIGY_EURUSD", "side": "buy", "volume": 0.1}
        req = builder.build_order_request(proposal)
        assert req.symbol == "PRODIGY_EURUSD"

    def test_build_applies_symbol_suffix(self) -> None:
        """Symbol suffix is added when missing."""
        builder = OrderBuilder(symbol_suffix=".FX")
        proposal = {"symbol": "EURUSD", "side": "buy", "volume": 0.1}
        req = builder.build_order_request(proposal)
        assert req.symbol == "EURUSD.FX"

    def test_build_maps_long_to_buy(self) -> None:
        """Side 'LONG' maps to 'BUY'."""
        builder = OrderBuilder()
        proposal = {"symbol": "EURUSD", "side": "long", "volume": 0.1}
        req = builder.build_order_request(proposal)
        assert req.order_type == "BUY"

    def test_build_maps_short_to_sell(self) -> None:
        """Side 'SHORT' maps to 'SELL'."""
        builder = OrderBuilder()
        proposal = {"symbol": "EURUSD", "side": "short", "volume": 0.1}
        req = builder.build_order_request(proposal)
        assert req.order_type == "SELL"

    def test_build_preserves_pending_order_types(self) -> None:
        """BUY_LIMIT, SELL_STOP, etc. are preserved as-is."""
        builder = OrderBuilder()
        for otype in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
            proposal = {"symbol": "EURUSD", "side": otype, "volume": 0.1}
            req = builder.build_order_request(proposal)
            assert req.order_type == otype

    def test_build_extracts_volume_from_lots_key(self) -> None:
        """'lots' is accepted as volume alternative."""
        builder = OrderBuilder()
        proposal = {"symbol": "EURUSD", "side": "buy", "lots": 2.5}
        req = builder.build_order_request(proposal)
        assert req.volume == 2.5

    def test_build_extracts_volume_from_size_key(self) -> None:
        """'size' is accepted as volume alternative."""
        builder = OrderBuilder()
        proposal = {"symbol": "EURUSD", "side": "buy", "size": 0.75}
        req = builder.build_order_request(proposal)
        assert req.volume == 0.75

    def test_build_autopopulates_price_from_ask_for_buy(self) -> None:
        """BUY market order autopopulates price from ask when price missing."""
        builder = OrderBuilder()
        proposal = {"symbol": "EURUSD", "side": "buy", "volume": 0.1}
        quote = {"bid": 1.0850, "ask": 1.0852}
        req = builder.build_order_request(proposal, market_quote=quote)
        assert req.price == 1.0852

    def test_build_autopopulates_price_from_bid_for_sell(self) -> None:
        """SELL market order autopopulates price from bid when price missing."""
        builder = OrderBuilder()
        proposal = {"symbol": "EURUSD", "side": "sell", "volume": 0.1}
        quote = {"bid": 1.0850, "ask": 1.0852}
        req = builder.build_order_request(proposal, market_quote=quote)
        assert req.price == 1.0850

    def test_build_uses_default_magic_when_not_provided(self) -> None:
        """Default magic is applied when proposal omits it."""
        builder = OrderBuilder(default_magic=55555)
        proposal = {"symbol": "EURUSD", "side": "buy", "volume": 0.1}
        req = builder.build_order_request(proposal)
        assert req.magic == 55555

    def test_build_uses_custom_comment(self) -> None:
        """Custom comment is preserved."""
        builder = OrderBuilder()
        proposal = {"symbol": "EURUSD", "side": "buy", "volume": 0.1, "comment": "scalper-v1"}
        req = builder.build_order_request(proposal)
        assert req.comment == "scalper-v1"

    def test_build_defaults_comment_when_not_provided(self) -> None:
        """Default comment is auto-generated."""
        builder = OrderBuilder()
        proposal = {"symbol": "EURUSD", "side": "buy", "volume": 0.1}
        req = builder.build_order_request(proposal)
        assert "EA-Bot" in req.comment

    def test_build_preserves_idempotency_key(self) -> None:
        """Idempotency key from proposal is preserved."""
        builder = OrderBuilder()
        proposal = {
            "symbol": "EURUSD",
            "side": "buy",
            "volume": 0.1,
            "idempotency_key": "order-abc-123",
        }
        req = builder.build_order_request(proposal)
        assert req.idempotency_key == "order-abc-123"


class TestOrderBuilderValidation:
    """OrderBuilder input validation tests."""

    def test_build_rejects_non_dict_proposal(self) -> None:
        """Non-dict proposal raises OrderBuilderError."""
        builder = OrderBuilder()
        with pytest.raises(ValueError):
            builder.build_order_request("not-a-dict")  # type: ignore[arg-type]

    def test_build_rejects_missing_symbol(self) -> None:
        """Missing symbol raises OrderBuilderError."""
        builder = OrderBuilder()
        with pytest.raises(ValueError, match="symbol"):
            builder.build_order_request({"side": "buy", "volume": 0.1})

    def test_build_rejects_empty_symbol(self) -> None:
        """Empty symbol raises OrderBuilderError."""
        builder = OrderBuilder()
        with pytest.raises(ValueError, match="symbol"):
            builder.build_order_request({"symbol": "   ", "side": "buy", "volume": 0.1})

    def test_build_rejects_missing_side(self) -> None:
        """Missing side raises OrderBuilderError."""
        builder = OrderBuilder()
        with pytest.raises(ValueError, match="side"):
            builder.build_order_request({"symbol": "EURUSD", "volume": 0.1})

    def test_build_rejects_unsupported_side(self) -> None:
        """Unsupported side raises OrderBuilderError."""
        builder = OrderBuilder()
        with pytest.raises(ValueError, match="Unsupported"):
            builder.build_order_request({"symbol": "EURUSD", "side": "buy-or-sell", "volume": 0.1})

    def test_build_rejects_negative_volume(self) -> None:
        """Negative volume raises OrderBuilderError."""
        builder = OrderBuilder()
        with pytest.raises(ValueError, match=r"(?i)volume"):
            builder.build_order_request({"symbol": "EURUSD", "side": "buy", "volume": -0.1})

    def test_build_rejects_zero_volume(self) -> None:
        """Zero volume raises OrderBuilderError."""
        builder = OrderBuilder()
        with pytest.raises(ValueError, match=r"(?i)volume"):
            builder.build_order_request({"symbol": "EURUSD", "side": "buy", "volume": 0.0})

    def test_build_rejects_invalid_volume_string(self) -> None:
        """Non-numeric volume string raises OrderBuilderError."""
        builder = OrderBuilder()
        with pytest.raises(ValueError, match="volume"):
            builder.build_order_request({"symbol": "EURUSD", "side": "buy", "volume": "abc"})


# ---------------------------------------------------------------------------
# ExecutionRecoveryEngine Tests
# ---------------------------------------------------------------------------


class TestExecutionRecoveryInitialState:
    """Initial state of the recovery engine."""

    def test_initial_state_normal(self) -> None:
        """Recovery engine starts in NORMAL state with no history."""
        engine = ExecutionRecoveryEngine()
        assert engine.state == RecoveryState.NORMAL
        assert engine.is_execution_blocked() is False
        assert engine.mismatch_history == []

    def test_accepts_custom_threshold(self) -> None:
        """Critical mismatch threshold is configurable."""
        engine = ExecutionRecoveryEngine(critical_mismatch_threshold=3)
        assert engine.critical_mismatch_threshold == 3


class TestExecutionRecoveryAudit:
    """Reconciliation and audit tests."""

    def test_no_mismatches_returns_nothing(self) -> None:
        """No mismatch returns empty list and stays NORMAL."""
        engine = ExecutionRecoveryEngine()
        internal = [{"ticket": 1001, "symbol": "EURUSD", "volume": 0.1, "sl": 1.0800, "tp": 1.0900}]
        broker = [{"ticket": 1001, "symbol": "EURUSD", "volume": 0.1, "sl": 1.0800, "tp": 1.0900}]
        events = engine.audit_reconciliation(internal, broker)
        assert events == []
        assert engine.state == RecoveryState.NORMAL
        assert engine.is_execution_blocked() is False

    def test_orphan_broker_position_blocks_execution(self) -> None:
        """A position in MT5 but missing in internal ledger blocks execution."""
        engine = ExecutionRecoveryEngine()
        internal: list[dict] = []
        broker = [{"ticket": 2001, "symbol": "XAUUSD", "volume": 0.5}]
        events = engine.audit_reconciliation(internal, broker)
        assert len(events) == 1
        assert events[0].mismatch_type == "ORPHAN_BROKER_POSITION"
        assert events[0].severity == "CRITICAL"
        assert engine.is_execution_blocked() is True
        assert engine.state == RecoveryState.BLOCKED_CRITICAL

    def test_missing_internal_position_blocks_execution(self) -> None:
        """A position in internal ledger but missing in MT5 blocks execution."""
        engine = ExecutionRecoveryEngine()
        internal = [{"ticket": 3001, "symbol": "GBPUSD", "volume": 1.0}]
        broker: list[dict] = []
        events = engine.audit_reconciliation(internal, broker)
        assert len(events) == 1
        assert events[0].mismatch_type == "MISSING_INTERNAL_POSITION"
        assert events[0].severity == "CRITICAL"
        assert engine.is_execution_blocked() is True

    def test_volume_mismatch_blocks_execution(self) -> None:
        """Volume mismatch between ledger and broker blocks execution."""
        engine = ExecutionRecoveryEngine()
        internal = [{"ticket": 4001, "symbol": "EURUSD", "volume": 1.0}]
        broker = [{"ticket": 4001, "symbol": "EURUSD", "volume": 0.5}]
        events = engine.audit_reconciliation(internal, broker)
        assert len(events) == 1
        assert events[0].mismatch_type == "VOLUME_MISMATCH"
        assert events[0].severity == "CRITICAL"
        assert engine.is_execution_blocked() is True

    def test_multiple_mismatches_aggregate(self) -> None:
        """Multiple mismatches are appended to history."""
        engine = ExecutionRecoveryEngine()
        internal = [
            {"ticket": 5001, "symbol": "EURUSD", "volume": 1.0},
            {"ticket": 5002, "symbol": "GBPUSD", "volume": 1.0},
        ]
        broker = [{"ticket": 5001, "symbol": "EURUSD", "volume": 0.5}]
        events = engine.audit_reconciliation(internal, broker)
        assert len(events) == 2  # 1 missing + 1 volume mismatch

    def test_repeated_audit_accumulates_history(self) -> None:
        """Calling audit multiple times accumulates history."""
        engine = ExecutionRecoveryEngine()
        engine.audit_reconciliation([], [])
        engine.audit_reconciliation([], [{"ticket": 9999, "symbol": "EURUSD", "volume": 0.1}])
        assert len(engine.mismatch_history) == 1


class TestExecutionRecoveryClear:
    """Clear block and resolve tests."""

    def test_clear_recovery_block_resets_state(self) -> None:
        """clear_recovery_block returns to NORMAL state."""
        engine = ExecutionRecoveryEngine()
        engine.audit_reconciliation(
            [{"ticket": 1001, "symbol": "EURUSD", "volume": 1.0}],
            [],
        )
        assert engine.is_execution_blocked() is True

        engine.clear_recovery_block("Manually resolved orphan")
        assert engine.state == RecoveryState.NORMAL
        assert engine.is_execution_blocked() is False

    def test_clear_marks_all_events_resolved(self) -> None:
        """clear_recovery_block marks unresolved events resolved with notes."""
        engine = ExecutionRecoveryEngine()
        engine.audit_reconciliation(
            [{"ticket": 1001, "symbol": "EURUSD", "volume": 1.0}],
            [],
        )
        assert len(engine.mismatch_history) == 1
        assert engine.mismatch_history[0].resolved is False

        engine.clear_recovery_block("reconciled by operator")
        assert engine.mismatch_history[0].resolved is True
        assert "operator" in engine.mismatch_history[0].resolution_notes


class TestExecutionRecoveryIntegration:
    """Integration with ExecutionEngine."""

    def test_recovery_engine_accepts_execution_engine(self) -> None:
        """RecoveryEngine can be constructed with an ExecutionEngine."""
        ee = ExecutionEngine()
        engine = ExecutionRecoveryEngine(execution_engine=ee)
        assert engine.execution_engine is ee

    def test_recovery_engine_blocks_new_orders(self) -> None:
        """A blocked recovery engine signals blocked execution via is_execution_blocked."""
        engine = ExecutionRecoveryEngine()
        engine.audit_reconciliation(
            [{"ticket": 1234, "symbol": "EURUSD", "volume": 0.1}],
            [],
        )
        # Supervisor / agents can check is_execution_blocked() before sending orders
        assert engine.is_execution_blocked() is True

        # After manual clear, execution is allowed again
        engine.clear_recovery_block("resolved")
        assert engine.is_execution_blocked() is False
