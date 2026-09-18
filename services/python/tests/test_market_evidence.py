# -*- coding: utf-8 -*-
"""Tests for the market-evidence bridge (feed loop → analysis context).

The production bug these tests pin down: the feed loop detected events and
enqueued them, but the *evidence behind each event* (close/high/low series,
computed market state, detected events, volatility inputs) was discarded —
only the event object travelled to the pipeline. The analysis committee then
ran blind (momentum/structure/technical/volatility had no data), so every
cycle degraded to NEUTRAL.

Contract:

* ``MarketFeedLoop`` attaches a ``market_snapshot`` to every emitted event and
  caches the latest snapshot per symbol (``trading.market_snapshot``).
* ``TradingPipeline`` merges that snapshot into the analysis context before
  the Supervisor runs — an event carrying evidence wins, else the cached
  snapshot for the symbol is used, else nothing changes (backward compatible).
* Explicit caller-provided context keys always win over the snapshot.

No network and no real MT5 are used (fake connectors only).
"""

from __future__ import annotations

from types import SimpleNamespace

from orchestration.pipeline import TradingPipeline
from trading.event_engine import EventQueue
from trading.feed_loop import MarketFeedLoop
from trading.market_snapshot import clear_latest_snapshots, get_latest_snapshot, set_latest_snapshot


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------
def _bars(symbol: str = "XAUUSD", n: int = 60, start: float = 2000.0, step: float = 1.5):
    """Build a strongly trending bar series (oldest → newest)."""
    bars = []
    price = start
    for i in range(n):
        open_ = price
        close = price + step
        bars.append(
            SimpleNamespace(
                symbol=symbol,
                open=open_,
                high=close + 0.3,
                low=open_ - 0.3,
                close=close,
                volume=1000.0,
                time=f"2026-09-19T01:{i:02d}:00",
            )
        )
        price = close
    return bars


class FakeConnector:
    """In-memory connector returning canned bars per symbol."""

    def __init__(self, bars_by_symbol: dict) -> None:
        self._bars = bars_by_symbol

    def get_ohlc(self, symbol: str, timeframe: str = "M5", count: int = 200):
        return list(self._bars.get(symbol, []))


class _CapturingSupervisor:
    """Supervisor stub that records the analysis context it receives."""

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def analyze(self, context):
        self.contexts.append(dict(context))
        return {
            "overall_signal": "NEUTRAL",
            "overall_confidence": 0.0,
            "agent_results": {},
            "summary": "stub summary",
        }


class _NeverCalledGate:
    """Risk gate stub that must never run (no actionable proposal)."""

    def validate_proposal(self, *args):  # pragma: no cover - must not run
        raise AssertionError("risk gate should not be called for a NEUTRAL synthesis")


def _pipeline(supervisor) -> TradingPipeline:
    return TradingPipeline(supervisor=supervisor, risk_gate=_NeverCalledGate())


def _loop(queue: EventQueue) -> MarketFeedLoop:
    return MarketFeedLoop(
        queue=queue,
        symbols=["XAUUSD"],
        timeframe="M5",
        connector=FakeConnector({"XAUUSD": _bars()}),
        event_cooldown_s=300.0,
    )


# ---------------------------------------------------------------------------
# Feed loop attaches the evidence
# ---------------------------------------------------------------------------
def test_emitted_event_carries_market_snapshot() -> None:
    queue = EventQueue()
    loop = _loop(queue)

    assert loop.poll_once() > 0

    event = queue.peek()[0]
    snapshot = getattr(event, "market_snapshot", None)
    assert isinstance(snapshot, dict) and snapshot, "event must carry market evidence"
    assert len(snapshot["prices"]) == 60
    assert len(snapshot["highs"]) == 60
    assert len(snapshot["lows"]) == 60
    assert snapshot["detected_events"], "the detected events must travel with the snapshot"
    assert snapshot["market_state"] is not None
    assert snapshot["volatility"]["atr"] > 0


def test_latest_snapshot_is_cached_per_symbol() -> None:
    queue = EventQueue()
    loop = _loop(queue)

    loop.poll_once()

    cached = get_latest_snapshot("XAUUSD")
    assert cached is not None
    assert len(cached["prices"]) == 60
    # Symbol lookup is case-insensitive.
    assert get_latest_snapshot("xauusd") is cached


def test_snapshot_cache_is_bounded_per_symbol_and_cleared() -> None:
    clear_latest_snapshots()
    set_latest_snapshot("XAUUSD", {"prices": [1.0], "symbol": "XAUUSD"})
    set_latest_snapshot("EURUSD", {"prices": [2.0], "symbol": "EURUSD"})

    assert get_latest_snapshot("XAUUSD")["prices"] == [1.0]
    assert get_latest_snapshot("EURUSD")["prices"] == [2.0]
    # An unknown symbol with two tracked symbols is honestly absent.
    assert get_latest_snapshot("GBPUSD") is None

    clear_latest_snapshots()
    assert get_latest_snapshot("XAUUSD") is None


def test_snapshot_cache_ignores_non_dict_payloads() -> None:
    clear_latest_snapshots()
    set_latest_snapshot("XAUUSD", "not-a-dict")  # type: ignore[arg-type]
    set_latest_snapshot("XAUUSD", {})

    assert get_latest_snapshot("XAUUSD") is None


# ---------------------------------------------------------------------------
# Pipeline merges the evidence into the analysis context
# ---------------------------------------------------------------------------
def test_pipeline_merges_event_snapshot_into_analysis_context() -> None:
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)
    event = {
        "event_type": "TREND_BULLISH",
        "symbol": "XAUUSD",
        "market_snapshot": {
            "prices": [1.0, 1.1, 1.2],
            "highs": [1.2, 1.3, 1.4],
            "lows": [0.9, 1.0, 1.1],
            "volatility": {"atr": 0.2},
        },
    }

    pipeline.run(event)

    context = supervisor.contexts[0]
    assert context["prices"] == [1.0, 1.1, 1.2]
    assert context["highs"] == [1.2, 1.3, 1.4]
    assert context["lows"] == [0.9, 1.0, 1.1]
    assert context["volatility"] == {"atr": 0.2}


def test_pipeline_falls_back_to_cached_snapshot_for_manual_cycles() -> None:
    """A manual /pipeline/run without evidence still analyses real data."""
    clear_latest_snapshots()
    set_latest_snapshot(
        "XAUUSD",
        {"prices": [9.0, 9.5], "symbol": "XAUUSD"},
    )
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)

    pipeline.run({"event_type": "MARKET_SCAN", "symbol": "XAUUSD"})

    assert supervisor.contexts[0]["prices"] == [9.0, 9.5]


def test_pipeline_without_snapshot_is_unchanged() -> None:
    """Backward compatible: no evidence anywhere → no snapshot keys added."""
    clear_latest_snapshots()
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)

    pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    context = supervisor.contexts[0]
    assert "prices" not in context
    assert "market_state" not in context


def test_explicit_context_wins_over_snapshot() -> None:
    """Caller-provided context must never be overwritten by cached evidence."""
    clear_latest_snapshots()
    set_latest_snapshot("XAUUSD", {"prices": [1.0, 2.0]})
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)

    pipeline.run(
        {"event_type": "TREND_BULLISH", "symbol": "XAUUSD"},
        context={"prices": [7.0, 7.5]},
    )

    assert supervisor.contexts[0]["prices"] == [7.0, 7.5]


# ---------------------------------------------------------------------------
# End-to-end: evidence reaches the real committee (the original bug)
# ---------------------------------------------------------------------------
def test_feed_evidence_reaches_market_lead_committee() -> None:
    """The committee runs on real data instead of degrading to NEUTRAL.

    Regression for the production finding: with the snapshot attached, the
    momentum/structure/technical/volatility specialists produce directional
    evidence and the committee is no longer unanimously NEUTRAL.
    """
    from market.intelligence import MarketLead

    queue = EventQueue()
    loop = _loop(queue)
    loop.poll_once()

    event = queue.peek()[0]
    snapshot = event.market_snapshot
    context = {
        "symbol": "XAUUSD",
        "event_type": str(event.event_type.value),
    }
    for key, value in snapshot.items():
        context.setdefault(key, value)

    result = MarketLead().analyze(context)

    specialists = result["specialist_results"]
    # The previously blind specialists now produce real evidence.
    assert specialists["momentum_analyst"]["confidence"] > 0
    assert specialists["structure_analyst"]["confidence"] > 0
    assert specialists["technical_analyst"]["confidence"] > 0
    # And the committee is no longer forced to NEUTRAL/0.0.
    assert not (result["signal"] == "NEUTRAL" and result["confidence"] == 0.0)
