# -*- coding: utf-8 -*-
"""Tests for market/sessions module (Phase 39).

Market session awareness: detect closed/holiday markets + crypto 24/7 support.

Contract:
* ``classify_symbol(symbol)`` returns "crypto" or "non_crypto".
* ``get_market_session(symbol, connector=None, max_age_s=1800, now=None)``
  returns a dict with keys: symbol, asset_class, open, reason, bar_age_s,
  tick_age_s, checked_at.
* Crypto => always open (trades 24/7), regardless of data age.
* Non-crypto => data-driven age check using min(bar_age, tick_age).
* Fail-open: exceptions and missing data => open=True with a fail-open reason.
* Naive datetimes are treated as UTC.

TDD: no real MT5, no network - fake connectors only.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.market.sessions import classify_symbol, get_market_session
from src.trading import feed_loop as feed_module
from src.trading.event_engine import EventQueue
from src.trading.feed_loop import MarketFeedLoop


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------
class Tick:
    """Minimal Tick-shaped object (matches mt5.schemas.Tick fields we use)."""

    def __init__(self, symbol: str, time: datetime) -> None:
        self.symbol = symbol
        self.bid = 2345.3
        self.ask = 2345.7
        self.last = 2345.5
        self.volume = 500.0
        self.time = time


def _bar(symbol: str, age_seconds: float, naive: bool = False) -> SimpleNamespace:
    """Build one OHLC-bar-shaped object *age_seconds* old."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    if naive:
        ts = ts.replace(tzinfo=None)
    return SimpleNamespace(
        symbol=symbol,
        open=2345.0,
        high=2346.0,
        low=2344.0,
        close=2345.5,
        volume=1000.0,
        time=ts,
    )


def _tick(symbol: str, age_seconds: float, naive: bool = False) -> Tick:
    """Build one Tick *age_seconds* old."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    if naive:
        ts = ts.replace(tzinfo=None)
    return Tick(symbol, ts)


class FakeConnector:
    """In-memory connector returning canned bars/tick per symbol."""

    def __init__(self, bars_by_symbol: dict, ticks_by_symbol: dict) -> None:
        self._bars = bars_by_symbol
        self._ticks = ticks_by_symbol
        self.calls: list[tuple] = []

    def get_ohlc(self, symbol: str, timeframe: str = "M5", count: int = 2):
        self.calls.append(("get_ohlc", symbol, timeframe, count))
        return list(self._bars.get(symbol, []))

    def get_tick(self, symbol: str):
        self.calls.append(("get_tick", symbol))
        return self._ticks.get(symbol)


class ExplodingConnector:
    """Connector that raises on both calls."""

    def get_ohlc(self, *args, **kwargs):
        raise RuntimeError("MT5 down")

    def get_tick(self, *args, **kwargs):
        raise RuntimeError("MT5 down")


class EmptyConnector:
    """Connector that returns empty/None."""

    def get_ohlc(self, *args, **kwargs):
        return None

    def get_tick(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# classify_symbol
# ---------------------------------------------------------------------------
def test_classify_symbol_crypto_examples() -> None:
    for symbol in ("BTCUSD", "#BTCUSD", "BTCEUR", "BTCJPY", "ETHBTC", "SOLUSD", "#ETHUSD"):
        assert classify_symbol(symbol) == "crypto", symbol


def test_classify_symbol_non_crypto_examples() -> None:
    for symbol in ("XAUUSD", "XAGUSD", "EURUSD", "US500", "#FirstSolar"):
        assert classify_symbol(symbol) == "non_crypto", symbol


def test_classify_symbol_more_crypto_tokens() -> None:
    for symbol in ("XRPUSD", "ADAUSD", "DOGEUSD", "LTCUSD", "BNBUSD"):
        assert classify_symbol(symbol) == "crypto", symbol


# ---------------------------------------------------------------------------
# get_market_session - crypto always open
# ---------------------------------------------------------------------------
def test_crypto_weekend_open_with_stale_data() -> None:
    """Crypto trades 24/7 even when data is stale (weekend)."""
    connector = FakeConnector(
        bars_by_symbol={"BTCUSD": [_bar("BTCUSD", 33 * 3600)]},
        ticks_by_symbol={"BTCUSD": _tick("BTCUSD", 33 * 3600)},
    )

    result = get_market_session("BTCUSD", connector=connector, max_age_s=1800)

    assert result["open"] is True
    assert result["asset_class"] == "crypto"
    assert "24/7" in result["reason"]


def test_crypto_open_even_without_data() -> None:
    """Crypto returns open=True even with no data (never hidden as closed)."""
    result = get_market_session("ETHUSD", connector=EmptyConnector(), max_age_s=1800)

    assert result["open"] is True
    assert result["asset_class"] == "crypto"
    assert "24/7" in result["reason"]


# ---------------------------------------------------------------------------
# get_market_session - non-crypto age-based
# ---------------------------------------------------------------------------
def test_non_crypto_closed_stale_data() -> None:
    connector = FakeConnector(
        bars_by_symbol={"XAUUSD": [_bar("XAUUSD", 33 * 3600)]},
        ticks_by_symbol={"XAUUSD": _tick("XAUUSD", 33 * 3600)},
    )

    result = get_market_session("XAUUSD", connector=connector, max_age_s=1800)

    assert result["open"] is False
    assert result["asset_class"] == "non_crypto"
    assert "closed" in result["reason"]
    assert result["bar_age_s"] is not None
    assert result["tick_age_s"] is not None


def test_non_crypto_open_fresh_data() -> None:
    connector = FakeConnector(
        bars_by_symbol={"EURUSD": [_bar("EURUSD", 2 * 60)]},
        ticks_by_symbol={"EURUSD": _tick("EURUSD", 5)},
    )

    result = get_market_session("EURUSD", connector=connector, max_age_s=1800)

    assert result["open"] is True
    assert result["asset_class"] == "non_crypto"
    assert "open" in result["reason"]


def test_non_crypto_min_age_semantics() -> None:
    """Min-age semantics: stale bar but fresh tick => open."""
    connector = FakeConnector(
        bars_by_symbol={"GBPUSD": [_bar("GBPUSD", 33 * 3600)]},
        ticks_by_symbol={"GBPUSD": _tick("GBPUSD", 5)},
    )

    result = get_market_session("GBPUSD", connector=connector, max_age_s=1800)

    assert result["open"] is True
    assert result["tick_age_s"] is not None
    assert result["tick_age_s"] <= 60


# ---------------------------------------------------------------------------
# Fail-open
# ---------------------------------------------------------------------------
def test_fail_open_connector_raises() -> None:
    result = get_market_session("XAUUSD", connector=ExplodingConnector(), max_age_s=1800)

    assert result["open"] is True
    assert "failed" in result["reason"]
    assert result["asset_class"] == "non_crypto"


def test_fail_open_connector_empty_results() -> None:
    result = get_market_session("XAUUSD", connector=EmptyConnector(), max_age_s=1800)

    assert result["open"] is True
    assert "inconclusive" in result["reason"]
    assert result["asset_class"] == "non_crypto"


def test_naive_datetimes_treated_as_utc() -> None:
    connector = FakeConnector(
        bars_by_symbol={"EURUSD": [_bar("EURUSD", 30 * 60, naive=True)]},
        ticks_by_symbol={"EURUSD": _tick("EURUSD", 30, naive=True)},
    )

    result = get_market_session("EURUSD", connector=connector, max_age_s=1800)

    assert result["open"] is True
    assert result["bar_age_s"] is not None
    assert result["tick_age_s"] is not None


# ---------------------------------------------------------------------------
# Feed loop integration
# ---------------------------------------------------------------------------
def _moving_bars(symbol: str):
    """Trending bars shaped like MT5 OHLC (enough to trigger a detector event)."""
    bars = []
    price = 1.0
    for i in range(40):
        open_ = price
        close = price + 0.0005
        bars.append(
            SimpleNamespace(
                symbol=symbol,
                open=open_,
                high=close + 0.0002,
                low=open_ - 0.0002,
                close=close,
                volume=1000.0,
                time=f"2024-01-01T00:{i:02d}:00+00:00",
            )
        )
        price = close
    return bars


def test_feed_loop_skips_closed_symbol() -> None:
    """session_provider says XAUUSD closed => zero events, no get_ohlc call."""
    queue = EventQueue()
    connector = FakeConnector({"XAUUSD": _moving_bars("XAUUSD")}, {})

    def provider(symbol: str) -> dict:
        return {"open": False, "reason": "market closed"} if symbol == "XAUUSD" else {"open": True}

    loop = MarketFeedLoop(
        queue=queue,
        symbols=["XAUUSD"],
        connector=connector,
        session_provider=provider,
    )

    emitted = loop.poll_once()

    assert emitted == 0
    assert len(queue) == 0
    assert connector.calls == [], "closed market must not be polled for OHLC"


def test_feed_loop_still_processes_open_crypto() -> None:
    """With XAUUSD closed and BTCUSD open, BTC events still flow."""
    queue = EventQueue()
    connector = FakeConnector(
        {"XAUUSD": _moving_bars("XAUUSD"), "BTCUSD": _moving_bars("BTCUSD")},
        {},
    )

    def provider(symbol: str) -> dict:
        return {"open": False} if symbol == "XAUUSD" else {"open": True}

    loop = MarketFeedLoop(
        queue=queue,
        symbols=["XAUUSD", "BTCUSD"],
        connector=connector,
        session_provider=provider,
    )

    emitted = loop.poll_once()

    assert emitted > 0, "open crypto symbol must still emit events"
    assert len(queue) > 0
    ohlc_symbols = [c[1] for c in connector.calls if c[0] == "get_ohlc"]
    assert "XAUUSD" not in ohlc_symbols
    assert "BTCUSD" in ohlc_symbols


def test_feed_loop_fail_open_on_raising_session_provider() -> None:
    """A raising session_provider must NOT stop the symbol from being polled."""
    queue = EventQueue()
    connector = FakeConnector({"EURUSD": _moving_bars("EURUSD")}, {})

    def provider(symbol: str) -> dict:
        raise RuntimeError("session service down")

    loop = MarketFeedLoop(
        queue=queue,
        symbols=["EURUSD"],
        connector=connector,
        session_provider=provider,
    )

    emitted = loop.poll_once()

    assert emitted > 0
    assert any(c[0] == "get_ohlc" for c in connector.calls)


# ---------------------------------------------------------------------------
# Safety invariants (must still hold for feed_loop)
# ---------------------------------------------------------------------------
def test_module_has_no_execution_imports() -> None:
    source = inspect.getsource(feed_module)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    assert not any("execution" in n for n in names)
    assert not any("order" in n for n in names)
