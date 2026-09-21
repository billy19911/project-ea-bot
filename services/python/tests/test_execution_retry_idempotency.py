# -*- coding: utf-8 -*-
"""Tests for idempotent retry on a lost broker response (audit P1-1 / Scenario F).

When the broker actually executed an order but the reply was lost, retrying must
NOT create a duplicate position. The engine consults an injected ``order_locator``
before resending; a match means the fill is adopted instead of duplicated.
"""

from __future__ import annotations

from execution import ExecutionEngine, OrderRequest


class _LostResponseConnector:
    """Connector that 'loses' the first reply but records the order it sent.

    First ``order_send`` → raises a connection-style error (transient) BUT the
    order was actually accepted (recorded in ``placed``). Subsequent sends would
    create duplicates — the locator must prevent that.
    """

    def __init__(self) -> None:
        self.placed: list[dict] = []
        self.send_calls = 0

    def order_send(self, payload):
        self.send_calls += 1
        self.placed.append(payload)
        # Simulate a lost reply on the first attempt.
        raise ConnectionError("connection lost after send")

    def get_symbol_info(self, symbol):
        return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

    def positions(self):
        # Broker reports the position that actually landed.
        return [
            {
                "ticket": 777,
                "symbol": p["symbol"],
                "side": "BUY",
                "volume": p["volume"],
                "price_open": 1.1,
                "profit": 0.0,
            }
            for p in self.placed
        ]


def _locator(request):
    """Locator that finds a matching position at the connector."""
    for pos in connector.positions():
        if pos["symbol"] == request.symbol and abs(pos["volume"] - request.volume) < 1e-9:
            return {"ticket": pos["ticket"]}
    return None


connector = _LostResponseConnector()


def test_lost_response_is_adopted_not_duplicated():
    engine = ExecutionEngine(
        mt5_connector=connector,
        max_retries=3,
        retry_delay=0.0,
        order_locator=_locator,
    )
    connector.placed.clear()
    connector.send_calls = 0

    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="lost-1")
    result = engine.execute_order(req)

    # The order is reported as executed (adopted), and it was sent exactly once.
    assert result.success is True
    assert result.ticket == 777
    assert connector.send_calls == 1  # no duplicate send


def test_without_locator_retry_would_resend():
    """Control: with no locator, the engine retries (documents the gap)."""
    conn = _LostResponseConnector()
    engine = ExecutionEngine(
        mt5_connector=conn,
        max_retries=2,
        retry_delay=0.0,
        order_locator=None,
    )
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="lost-2")
    result = engine.execute_order(req)

    # Without a locator the retry cannot know the order landed → it re-sends.
    assert result.success is False
    assert conn.send_calls == 3  # initial + 2 retries


def test_locator_error_does_not_break_retry():
    def boom(request):
        raise RuntimeError("locator down")

    conn = _LostResponseConnector()
    engine = ExecutionEngine(
        mt5_connector=conn,
        max_retries=1,
        retry_delay=0.0,
        order_locator=boom,
    )
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="lost-3")
    result = engine.execute_order(req)
    # Still fails safely (no crash), and the retry proceeded.
    assert result.success is False


def test_no_match_proceeds_with_retry():
    """A locator that finds nothing must not block the normal retry."""

    def empty_locator(request):
        return None

    conn = _LostResponseConnector()
    engine = ExecutionEngine(
        mt5_connector=conn,
        max_retries=1,
        retry_delay=0.0,
        order_locator=empty_locator,
    )
    req = OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="lost-4")
    result = engine.execute_order(req)
    assert result.success is False


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
