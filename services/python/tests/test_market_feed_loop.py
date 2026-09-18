# -*- coding: utf-8 -*-
"""Tests for the MarketFeedLoop (Phase 6).

The feed loop is the *only* component that reads MT5 OHLC on a schedule and
enqueues detected market events into the runtime queue, so the scheduler can
analyse the market autonomously (no manual trigger).

Contract:

* ``poll_once()`` — read OHLC (read-only) → detect events → dedupe → enqueue;
  returns the number of events actually enqueued.
* Fail-safe — MT5/connector errors and detector errors skip the symbol/cycle;
  the loop never dies.
* Dedup — identical consecutive polls do not double-enqueue.
* ``run()``/``stop()`` — clean async lifecycle (no CancelledError leaks).
* Safety invariant — the module must never import execution/order code and
  the loop must expose no order-placing methods.

No real MT5 and no network are used (fake connectors only).
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import time
from types import SimpleNamespace

from src.trading import feed_loop as feed_module
from src.trading.event_engine import EventHistory, EventQueue
from src.trading.feed_loop import MarketFeedLoop


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------
def _bars(symbol: str = "EURUSD", n: int = 40, start: float = 1.0, step: float = 0.0005):
    """Build a trending bar series (oldest → newest) shaped like MT5 OHLC."""
    bars = []
    price = start
    for i in range(n):
        open_ = price
        close = price + step
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


class FakeConnector:
    """In-memory connector returning canned bars per symbol."""

    def __init__(self, bars_by_symbol: dict) -> None:
        self._bars = bars_by_symbol
        self.calls: list[tuple] = []

    def get_ohlc(self, symbol: str, timeframe: str = "H1", count: int = 100):
        self.calls.append((symbol, timeframe, count))
        return list(self._bars.get(symbol, []))


class ExplodingConnector:
    """Connector that always raises (MT5 down)."""

    def get_ohlc(self, *args, **kwargs):
        raise RuntimeError("mt5 down")


class SelectiveConnector:
    """Connector that raises for one symbol and serves bars for another."""

    def __init__(self, bad_symbol: str, bars_by_symbol: dict) -> None:
        self._bad = bad_symbol
        self._bars = bars_by_symbol

    def get_ohlc(self, symbol: str, timeframe: str = "H1", count: int = 100):
        if symbol == self._bad:
            raise RuntimeError("symbol unavailable")
        return list(self._bars.get(symbol, []))


def _loop(**overrides) -> MarketFeedLoop:
    """Build a loop with sane test defaults."""
    kwargs = {
        "queue": EventQueue(),
        "symbols": ["EURUSD"],
        "timeframe": "M5",
        "interval_s": 0.01,
        "count": 200,
        "connector": FakeConnector({"EURUSD": _bars()}),
    }
    kwargs.update(overrides)
    return MarketFeedLoop(**kwargs)


# ---------------------------------------------------------------------------
# poll_once — happy path
# ---------------------------------------------------------------------------
def test_poll_once_enqueues_detected_events() -> None:
    queue = EventQueue()
    loop = _loop(queue=queue)

    queued = loop.poll_once()

    assert queued > 0
    assert len(queue) == queued
    assert queue.peek(), "expected detected events in the production queue"


def test_poll_once_passes_symbol_timeframe_count_to_connector() -> None:
    connector = FakeConnector({"XAUUSD": _bars("XAUUSD")})
    loop = _loop(symbols=["XAUUSD"], connector=connector, timeframe="M15", count=150)

    loop.poll_once()

    assert connector.calls == [("XAUUSD", "M15", 150)]


def test_history_records_emitted_events() -> None:
    history = EventHistory()
    loop = _loop(history=history)

    queued = loop.poll_once()

    assert queued > 0
    assert len(history) == queued


# ---------------------------------------------------------------------------
# poll_once — fail-safe paths
# ---------------------------------------------------------------------------
def test_poll_once_returns_zero_on_connector_failure() -> None:
    loop = _loop(connector=ExplodingConnector())

    assert loop.poll_once() == 0  # must not raise


def test_poll_once_returns_zero_on_empty_bars() -> None:
    loop = _loop(connector=FakeConnector({}))  # symbol has no data

    assert loop.poll_once() == 0


def test_connector_failure_on_one_symbol_does_not_block_other() -> None:
    queue = EventQueue()
    loop = _loop(
        queue=queue,
        symbols=["BAD", "EURUSD"],
        connector=SelectiveConnector("BAD", {"EURUSD": _bars()}),
    )

    queued = loop.poll_once()

    assert queued > 0
    assert len(queue) == queued


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def test_second_poll_of_identical_bars_is_deduplicated() -> None:
    loop = _loop()

    first = loop.poll_once()
    second = loop.poll_once()

    assert first > 0
    assert second == 0, "identical bars within the dedup window must not re-emit"


# ---------------------------------------------------------------------------
# Async lifecycle
# ---------------------------------------------------------------------------
def test_run_stops_cleanly_after_stop() -> None:
    loop = _loop()

    async def scenario() -> None:
        task = asyncio.create_task(loop.run())
        await asyncio.sleep(0.05)
        loop.stop()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(scenario())
    assert loop.running is False


def test_run_survives_poll_exceptions() -> None:
    loop = _loop(connector=ExplodingConnector())

    async def scenario() -> None:
        task = asyncio.create_task(loop.run())
        await asyncio.sleep(0.05)
        assert not task.done(), "the loop must survive connector failures"
        loop.stop()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------
def test_module_does_not_import_execution_or_order_code() -> None:
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


def test_loop_exposes_no_order_placing_methods() -> None:
    forbidden = ("place_order", "send_order", "execute_order", "open_position", "close_position")
    for name in forbidden:
        assert not hasattr(MarketFeedLoop, name), f"unexpected method: {name}"


# ---------------------------------------------------------------------------
# Config defaults (MARKET_FEED_ENABLED default OFF)
# ---------------------------------------------------------------------------
def test_settings_default_market_feed_disabled(monkeypatch) -> None:
    for key in (
        "MARKET_FEED_ENABLED",
        "MARKET_FEED_SYMBOLS",
        "MARKET_FEED_TIMEFRAME",
        "MARKET_FEED_INTERVAL_S",
    ):
        monkeypatch.delenv(key, raising=False)

    from src.config import Settings

    settings = Settings(_env_file=None)
    assert settings.market_feed_enabled is False
    assert settings.market_feed_symbols == "XAUUSD"
    assert settings.market_feed_timeframe == "M5"
    assert settings.market_feed_interval_s == 60.0


# ---------------------------------------------------------------------------
# Lifespan wiring — enabled only when the operator switches it on
# ---------------------------------------------------------------------------
class _RecordingFeed:
    """Stand-in feed that records construction/start/stop."""

    instances: list["_RecordingFeed"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.stopped = False
        self.started = False
        _RecordingFeed.instances.append(self)

    async def run(self) -> None:
        self.started = True
        while not self.stopped:
            await asyncio.sleep(0.01)

    def stop(self) -> None:
        self.stopped = True


def test_lifespan_starts_and_stops_feed_when_enabled(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import src.main as main_module

    _RecordingFeed.instances.clear()
    monkeypatch.setattr(feed_module, "MarketFeedLoop", _RecordingFeed)
    monkeypatch.setattr(main_module.settings, "market_feed_enabled", True)
    monkeypatch.setattr(main_module.settings, "scheduler_enabled", False)
    monkeypatch.setattr(main_module.settings, "mt5_live_data", False)

    with TestClient(main_module.app):
        assert _RecordingFeed.instances, "feed must be constructed when enabled"
        instance = _RecordingFeed.instances[-1]
        deadline = time.time() + 1.0
        while not instance.started and time.time() < deadline:
            time.sleep(0.01)

    assert instance.started, "feed.run() must be scheduled at startup"
    assert instance.stopped, "feed.stop() must be called at shutdown"
    assert instance.kwargs["queue"] is not None


def test_lifespan_does_not_start_feed_when_disabled(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import src.main as main_module

    _RecordingFeed.instances.clear()
    monkeypatch.setattr(feed_module, "MarketFeedLoop", _RecordingFeed)
    monkeypatch.setattr(main_module.settings, "market_feed_enabled", False)
    monkeypatch.setattr(main_module.settings, "scheduler_enabled", False)
    monkeypatch.setattr(main_module.settings, "mt5_live_data", False)

    with TestClient(main_module.app):
        pass

    assert _RecordingFeed.instances == [], "feed must stay OFF by default"


# ---------------------------------------------------------------------------
# Scheduler-driven cycles are recorded (feed → /decisions visibility)
# ---------------------------------------------------------------------------
def test_scheduler_driven_cycle_is_recorded_in_runtime_history() -> None:
    """A cycle the scheduler runs directly (feed events) must be recorded.

    The scheduler calls ``pipeline.run()`` on its own; without the recording
    proxy those decisions would never surface in ``/decisions``.
    """
    from src.orchestration.runtime import OrchestrationRuntime

    runtime = OrchestrationRuntime()
    queue = runtime.queue
    queue.enqueue(_detected_event())

    processed = runtime.scheduler.process_available()

    assert processed == 1
    decisions = runtime.recent_decisions(limit=5)
    assert decisions, "scheduler-driven cycle must appear in /decisions"
    assert decisions[0]["event_type"] == "TREND_BULLISH"


def _detected_event():
    """Build one real DetectedEvent for the scheduler to consume."""
    from src.trading.events import DetectedEvent, EventTypes

    return DetectedEvent(
        event_type=EventTypes.TREND_BULLISH,
        severity=0.6,
        description="test event",
        timestamp="2024-01-01T00:00:00+00:00",
        symbol="EURUSD",
    )
