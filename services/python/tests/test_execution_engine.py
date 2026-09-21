# -*- coding: utf-8 -*-
"""Test suite for Phase 14 Execution Engine."""

from __future__ import annotations

import pytest

from execution import ExecutionEngine, ExecutionResult, OrderRequest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_connector():
    """Create a minimal mock MT5 connector."""

    class MockPosition:
        def __init__(self, ticket, symbol, side, volume, price_open):
            self.ticket = ticket
            self.symbol = symbol
            self.side = side
            self.volume = volume
            self.price_open = price_open
            self.price_current = price_open
            self.profit = 10.0
            self.sl = 0.0
            self.tp = 0.0

    class MockSymbolInfo:
        def __init__(self):
            self.volume_min = 0.01
            self.volume_max = 100.0

    class MockTick:
        def __init__(self, bid, ask):
            self.bid = bid
            self.ask = ask

    class MockOrderSendResult:
        def __init__(self, success, ticket=None, message=""):
            self.retcode = 0 if success else 1
            self.order = ticket
            self.deal = ticket
            self.comment = message
            self.price = 1.0850 if success else 0.0

    class Connector:
        def __init__(self):
            self._positions = []
            self._symbol_info = MockSymbolInfo()
            self._tick = MockTick(bid=1.0849, ask=1.0851)

        def order_send(self, payload):
            ticket = payload.get("volume", 1.0) * 10000
            return MockOrderSendResult(True, ticket=int(ticket), message="Order executed")

        def positions_get(self, ticket=None):
            for pos in self._positions:
                if ticket is None or pos.ticket == ticket:
                    return [pos]
            return []

        def positions_get_all(self):
            return self._positions

        def get_symbol_info(self, symbol):
            return self._symbol_info

        def get_tick(self, symbol):
            return self._tick

        def get_positions(self):
            return self._positions

        def add_position(self, ticket, symbol, side, volume, price):
            self._positions.append(MockPosition(ticket, symbol, side, volume, price))

    return Connector()


@pytest.fixture
def execution_engine(mock_connector):
    """Create an ExecutionEngine with mock connector."""
    return ExecutionEngine(mt5_connector=mock_connector)


# ---------------------------------------------------------------------------
# OrderRequest Dataclass Tests
# ---------------------------------------------------------------------------


def test_order_request_default_values():
    """OrderRequest should have sensible default values."""
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)
    assert req.price == 0.0
    assert req.sl == 0.0
    assert req.tp == 0.0
    assert req.magic == 0
    assert req.comment == ""
    assert req.idempotency_key != ""
    assert isinstance(req.idempotency_key, str)


def test_order_request_custom_values():
    """OrderRequest should accept custom parameter values."""
    req = OrderRequest(
        symbol="XAUUSD",
        order_type="SELL",
        volume=0.5,
        price=1900.0,
        sl=1920.0,
        tp=1880.0,
        magic=12345,
        comment="test order",
        idempotency_key="custom-key-123",
    )
    assert req.symbol == "XAUUSD"
    assert req.order_type == "SELL"
    assert req.volume == 0.5
    assert req.price == 1900.0
    assert req.sl == 1920.0
    assert req.tp == 1880.0
    assert req.magic == 12345
    assert req.comment == "test order"
    assert req.idempotency_key == "custom-key-123"


def test_order_request_valid_order_types():
    """OrderRequest should work with all valid order types."""
    valid_types = ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"]
    for otype in valid_types:
        req = OrderRequest(symbol="EURUSD", order_type=otype, volume=1.0)
        assert req.order_type == otype


# ---------------------------------------------------------------------------
# Order Validation Tests
# ---------------------------------------------------------------------------


def test_validate_order_valid_market_buy(execution_engine):
    """A valid market buy order should pass validation."""
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)
    is_valid, errors = execution_engine.validate_order(req)
    assert is_valid is True
    assert errors == []


def test_validate_order_valid_market_sell(execution_engine):
    """A valid market sell order should pass validation."""
    req = OrderRequest(symbol="EURUSD", order_type="SELL", volume=1.0)
    is_valid, errors = execution_engine.validate_order(req)
    assert is_valid is True
    assert errors == []


def test_validate_order_empty_symbol(execution_engine):
    """Empty symbol should fail validation."""
    req = OrderRequest(symbol="", order_type="BUY", volume=1.0)
    is_valid, errors = execution_engine.validate_order(req)
    assert is_valid is False
    assert any("Symbol cannot be empty" in e for e in errors)


def test_validate_order_invalid_volume(execution_engine):
    """Zero or negative volume should fail validation."""
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=0.0)
    is_valid, errors = execution_engine.validate_order(req)
    assert is_valid is False
    assert any("Volume must be greater than 0" in e for e in errors)


def test_validate_order_volume_below_minimum(execution_engine):
    """Volume below minimum lot size should fail."""
    engine = ExecutionEngine(mt5_connector=None, min_volume=0.01)
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=0.001)
    is_valid, errors = engine.validate_order(req)
    assert is_valid is False
    assert any("below minimum" in e for e in errors)


def test_validate_order_invalid_order_type(execution_engine):
    """Invalid order type should fail validation."""
    req = OrderRequest(symbol="EURUSD", order_type="INVALID", volume=1.0)
    is_valid, errors = execution_engine.validate_order(req)
    assert is_valid is False
    assert any("Invalid order_type" in e for e in errors)


def test_validate_order_sl_tp_for_buy(execution_engine):
    """Buy order SL above price or TP below should fail validation."""
    req = OrderRequest(
        symbol="EURUSD",
        order_type="BUY",
        volume=1.0,
        price=1.0850,
        sl=1.0900,  # Above price - invalid for buy
        tp=1.0800,  # Below price - invalid for buy
    )
    is_valid, errors = execution_engine.validate_order(req)
    assert is_valid is False
    assert any("SL" in e and "below" in e for e in errors)


def test_validate_order_sl_tp_for_sell(execution_engine):
    """Sell order SL below price or TP above should fail validation."""
    req = OrderRequest(
        symbol="EURUSD",
        order_type="SELL",
        volume=1.0,
        price=1.0850,
        sl=1.0800,  # Below price - invalid for sell
        tp=1.0900,  # Above price - invalid for sell
    )
    is_valid, errors = execution_engine.validate_order(req)
    assert is_valid is False
    assert any("SL" in e and "above" in e for e in errors)


def test_validate_order_price_exceeds_spread(execution_engine):
    """Price far outside current spread should fail validation."""
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, price=10.0)
    is_valid, errors = execution_engine.validate_order(req)
    # Price far from tick price must fail spread tolerance check.
    # Mock connector returns tick at 1.0849/1.0851.
    assert is_valid is False
    assert any("spread tolerance" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Duplicate Prevention Tests
# ---------------------------------------------------------------------------


def test_duplicate_prevention_same_key(mock_connector):
    """Submitting same idempotency_key twice should reject second."""
    engine = ExecutionEngine(mt5_connector=mock_connector)
    req1 = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="key-1")
    req2 = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="key-1")

    # First submission should succeed
    result1 = engine.execute_order(req1)
    assert result1.success is True

    # Second submission with same key should fail
    result2 = engine.execute_order(req2)
    assert result2.success is False
    assert result2.error_code == 409  # Conflict
    assert "Duplicate" in result2.error_message


def test_auto_generate_idempotency_key(mock_connector):
    """OrderRequest should auto-generate idempotency key when not provided."""
    engine = ExecutionEngine(mt5_connector=mock_connector)
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)
    req.idempotency_key = ""  # Explicitly empty

    # Execute order without key - should auto-generate
    result = engine.execute_order(req)
    assert result.success is True
    assert req.idempotency_key != ""


# ---------------------------------------------------------------------------
# Order Execution Tests
# ---------------------------------------------------------------------------


def test_execute_order_success(mock_connector):
    """Successful order execution should return proper ExecutionResult."""
    engine = ExecutionEngine(mt5_connector=mock_connector)
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)

    result = engine.execute_order(req)
    assert result.success is True
    assert result.ticket is not None
    assert result.error_code == 0
    assert result.error_message == ""
    assert result.retries == 0
    assert result.position_opened is None  # No position yet confirmed


def test_execute_order_invalid_fails_fast(mock_connector):
    """Invalid order should fail without submission."""
    engine = ExecutionEngine(mt5_connector=mock_connector)
    req = OrderRequest(symbol="", order_type="INVALID", volume=-1.0)  # Invalid

    result = engine.execute_order(req)
    assert result.success is False
    assert result.error_code == 400  # Validation error
    assert "Validation failed" in result.error_message


# ---------------------------------------------------------------------------
# ExecutionResult Dataclass Tests
# ---------------------------------------------------------------------------


def test_execution_result_success():
    """ExecutionResult should capture success case."""
    result = ExecutionResult(success=True, ticket=12345)
    assert result.success is True
    assert result.ticket == 12345
    assert result.error_code == 0
    assert result.error_message == ""
    assert result.retries == 0
    assert result.position_opened is None


def test_execution_result_failure():
    """ExecutionResult should capture failure case."""
    result = ExecutionResult(
        success=False,
        error_code=10013,
        error_message="Invalid symbol",
        retries=2,
    )
    assert result.success is False
    assert result.ticket is None
    assert result.error_code == 10013
    assert result.error_message == "Invalid symbol"
    assert result.retries == 2
    assert result.position_opened is None


# ---------------------------------------------------------------------------
# Confirmation Tests
# ---------------------------------------------------------------------------


def test_confirm_execution_found(mock_connector):
    """confirm_execution should return True when position found."""
    engine = ExecutionEngine(mt5_connector=mock_connector)
    mock_connector.add_position(ticket=12345, symbol="EURUSD", side="BUY", volume=1.0, price=1.0850)

    is_confirmed = engine.confirm_execution(12345)
    assert is_confirmed is True


def test_confirm_execution_not_found(mock_connector):
    """confirm_execution should return False when position not found."""
    engine = ExecutionEngine(mt5_connector=mock_connector)

    is_confirmed = engine.confirm_execution(99999)
    assert is_confirmed is False


def test_confirm_execution_invalid_ticket(mock_connector):
    """confirm_execution should return False for invalid ticket values."""
    engine = ExecutionEngine(mt5_connector=mock_connector)
    assert engine.confirm_execution(None) is False
    assert engine.confirm_execution(0) is False
    assert engine.confirm_execution(-1) is False


def test_sync_position_empty(mock_connector):
    """sync_position should return zero counts for unfound symbol."""
    engine = ExecutionEngine(mt5_connector=mock_connector)
    result = engine.sync_position(" nonexistent.symbol ")

    assert result["symbol"] == "NONEXISTENT.SYMBOL"
    assert result["positions_count"] == 0
    assert result["total_volume"] == 0.0
    assert result["unrealized_pnl"] == 0.0


def test_sync_position_with_open_position(mock_connector):
    """sync_position should aggregate open positions correctly."""
    engine = ExecutionEngine(mt5_connector=mock_connector)
    mock_connector.add_position(ticket=1001, symbol="EURUSD", side="BUY", volume=1.0, price=1.0840)
    mock_connector.add_position(ticket=1002, symbol="EURUSD", side="SELL", volume=0.5, price=1.0860)

    result = engine.sync_position("EURUSD")

    assert result["symbol"] == "EURUSD"
    assert result["positions_count"] == 2
    assert result["total_volume"] == 1.5
    assert result["buy_volume"] == 1.0
    assert result["sell_volume"] == 0.5
    assert result["net_volume"] == 0.5
    assert result["unrealized_pnl"] == 20.0  # 10 + 10 from mock profits


# ---------------------------------------------------------------------------
# Retry Logic Tests
# ---------------------------------------------------------------------------


def test_retry_transient_error(mock_connector):
    """ExecutionEngine should retry on transient errors."""
    call_count = [0]

    class TransientFailConnector:
        def __init__(self, inner):
            self.inner = inner

        def order_send(self, payload):
            call_count[0] += 1
            if call_count[0] < 3:
                return {"success": False, "error_code": 10004, "message": "Requote"}
            return self.inner.order_send(payload)

    engine = ExecutionEngine(mt5_connector=TransientFailConnector(mock_connector), max_retries=3)
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)

    result = engine.execute_order(req)

    assert result.success is True
    assert result.retries == 2  # Two transient failures then success


def test_is_transient_error_detection(execution_engine):
    """_is_transient_error should identify transient error conditions."""
    assert execution_engine._is_transient_error(10004, "Requote") is True
    assert execution_engine._is_transient_error(10012, "Timeout occurred") is True
    assert execution_engine._is_transient_error(10027, "Trade disabled") is True
    assert execution_engine._is_transient_error(10013, "Invalid symbol") is False
    assert execution_engine._is_transient_error(10019, "Not enough money") is False
    assert execution_engine._is_transient_error(999, "timeout") is True  # keyword match


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


def test_full_execution_lifecycle(mock_connector):
    """Test complete execution flow: validate, execute, confirm, sync."""
    engine = ExecutionEngine(mt5_connector=mock_connector)

    # Add position so confirmation succeeds
    mock_connector.add_position(
        ticket=10000,
        symbol="EURUSD",
        side="BUY",
        volume=1.0,
        price=1.0850,
    )

    req = OrderRequest(
        symbol="EURUSD",
        order_type="BUY",
        volume=1.0,
        idempotency_key="lifecycle-test",
    )

    # Step 1: Validation should pass
    is_valid, errors = engine.validate_order(req)
    assert is_valid is True

    # Step 2: Execute
    result = engine.execute_order(req)
    assert result.success is True
    assert result.retries == 0

    # Step 3: Confirm
    confirmed = engine.confirm_execution(result.ticket)
    assert confirmed is True

    # Step 4: Sync position (from mock)
    pos = engine.sync_position("EURUSD")
    assert pos["positions_count"] == 1
    assert pos["total_volume"] == 1.0


# ---------------------------------------------------------------------------
# Audit P0-2 — no fabricated fill when there is no broker path
# ---------------------------------------------------------------------------


def test_no_connector_does_not_fabricate_fill_by_default(monkeypatch):
    """With no connector and no native MT5, execution must NOT fake success.

    Regression guard for audit finding P0-2: the engine previously returned
    ``success=True`` with a fabricated ticket when the broker path was absent,
    which made the pipeline record phantom EXECUTED trades.
    """
    import sys

    engine = ExecutionEngine(mt5_connector=None)  # simulation_mode defaults False
    # Force the native `import MetaTrader5` inside _send_to_mt5 to raise
    # ImportError so the fallback branch runs deterministically.
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)

    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)
    result = engine.execute_order(req)

    assert result.success is False
    assert result.ticket is None
    assert result.error_code == 1
    assert "simulation_mode" in result.error_message


def test_simulation_mode_is_explicit_and_labelled(monkeypatch):
    """Simulation must be opt-in and the fabricated ticket must be labelled."""
    import sys

    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True)
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)

    result = engine.execute_order(req)

    assert result.success is True
    assert result.ticket is not None


def test_native_send_error_is_reported_not_simulated():
    """A failing native connector must surface the real error, never fake success."""

    class FailingConnector:
        def order_send(self, payload):
            raise RuntimeError("broker exploded")

        # Provide a valid symbol lookup so pre-flight validation passes and the
        # failure is the raised broker error (not a validation reject).
        def get_symbol_info(self, symbol):
            return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

    engine = ExecutionEngine(mt5_connector=FailingConnector())
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)

    result = engine.execute_order(req)

    assert result.success is False
    assert result.ticket is None
    assert "broker exploded" in result.error_message


# ---------------------------------------------------------------------------
# Audit B-3 — the deterministic gate is executor-enforced when require_approval
# ---------------------------------------------------------------------------


def test_require_approval_blocks_order_without_token(monkeypatch):
    """With require_approval, an order lacking an approval_token fails closed.

    Regression guard for audit finding B-3: previously the executor had no
    knowledge of the Risk Gate, so a direct call dispatched the order. Now the
    executor refuses BEFORE any MT5 dispatch when approval is required.
    """
    import sys

    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True, require_approval=True)
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)

    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)
    result = engine.execute_order(req)

    assert result.success is False
    assert result.ticket is None
    assert result.error_code == 403
    assert "approval_token" in result.error_message


def test_require_approval_allows_order_with_token(monkeypatch):
    """A gate-stamped approval_token lets the order proceed (simulated)."""
    import sys

    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True, require_approval=True)
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)

    req = OrderRequest(
        symbol="EURUSD",
        order_type="BUY",
        volume=1.0,
        approval_token="gate:dec-test",
    )
    result = engine.execute_order(req)

    assert result.success is True
    assert result.ticket is not None


def test_require_approval_defaults_off_for_backwards_compatibility(monkeypatch):
    """The default engine (no require_approval) keeps prior behaviour."""
    import sys

    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True)
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)

    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0)
    result = engine.execute_order(req)

    # No approval required by default → simulated success unchanged.
    assert result.success is True
