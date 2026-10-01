# -*- coding: utf-8 -*-
"""TASK 09 — Market freshness tests.

Pins the contract that stale market data can never produce a trade:

* Every snapshot carries ``bar_timestamp`` / ``received_at`` / ``age_seconds``
  / ``timeframe`` / ``symbol`` (the feed loop stamps them).
* The freshness gate is TIMEFRAME-AWARE (M1 strict, M5/H1/D1 wider).
* Clock anomalies are rejected fail-closed:
  - ``received_at < bar_timestamp`` (clock runs backwards),
  - future timestamps,
  - negative age.
* A stale snapshot is rejected BEFORE the committee is convened, so it can
  never reach the committee as trade-ready context.
* Staleness is visible through the ops read model / endpoint surface.

No network and no real MT5: fake connectors only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from orchestration.pipeline import STATUS_STALE_MARKET_DATA, TradingPipeline
from trading.event_engine import EventQueue
from trading.feed_loop import MarketFeedLoop
from trading.market_freshness import (
    DEFAULT_MAX_AGE_SECONDS,
    TIMEFRAME_MAX_AGE_SECONDS,
    evaluate_freshness,
    max_allowed_age,
)
from trading.market_snapshot import clear_latest_snapshots, set_latest_snapshot


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------
def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _snapshot(
    *,
    timeframe: str = "M5",
    symbol: str = "XAUUSD",
    age_seconds: float = 0.0,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    bar = now - timedelta(seconds=age_seconds)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_timestamp": _iso(bar),
        "received_at": _iso(now),
        "age_seconds": age_seconds,
        "prices": [1.0, 2.0],
        "volatility": {"atr": 0.5},
    }


def _bars(symbol: str = "XAUUSD", n: int = 40):
    base = datetime.now(timezone.utc)
    bars = []
    price = 2000.0
    for i in range(n):
        bar_time = base.timestamp() - (n - 1 - i) * 60
        bars.append(
            SimpleNamespace(
                symbol=symbol,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 1.5,
                volume=1000.0,
                time=datetime.fromtimestamp(bar_time, tz=timezone.utc),
            )
        )
        price += 1.5
    return bars


class FakeConnector:
    def __init__(self, bars_by_symbol: dict) -> None:
        self._bars = bars_by_symbol

    def get_ohlc(self, symbol: str, timeframe: str = "M5", count: int = 200):
        return list(self._bars.get(symbol, []))


class _CapturingSupervisor:
    """Records whether/how often it is called (committee proxy)."""

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def analyze(self, context):
        self.contexts.append(dict(context))
        return {
            "overall_signal": "NEUTRAL",
            "overall_confidence": 0.0,
            "agent_results": {},
            "summary": "stub",
        }


class _NeverCalledGate:
    def validate_proposal(self, *args):  # pragma: no cover
        raise AssertionError("risk gate must never run for a stale cycle")


def _pipeline(supervisor) -> TradingPipeline:
    return TradingPipeline(supervisor=supervisor, risk_gate=_NeverCalledGate())


# ---------------------------------------------------------------------------
# threshold contract
# ---------------------------------------------------------------------------
def test_timeframe_thresholds_are_timeframe_aware() -> None:
    # M1 is strict; M5/H1/D1 scale up with the bar length.
    assert max_allowed_age("M1") < max_allowed_age("M5") < max_allowed_age("H1")
    assert max_allowed_age("H1") < max_allowed_age("H4") < max_allowed_age("D1")
    # Not one universal value.
    assert len(set(TIMEFRAME_MAX_AGE_SECONDS.values())) > 1
    # Unknown/empty timeframe → documented default (M5), never a silent zero.
    assert max_allowed_age("") == DEFAULT_MAX_AGE_SECONDS
    assert max_allowed_age("ZZZ") == DEFAULT_MAX_AGE_SECONDS


def test_stale_snapshot_rejected_for_m1() -> None:
    # 120s is stale for M1 (limit 120s -> just over) but fresh for M5.
    verdict = evaluate_freshness(_snapshot(timeframe="M1", age_seconds=121))
    assert verdict.accepted is False
    assert "age_exceeded" in verdict.reason
    assert verdict.max_allowed_age == TIMEFRAME_MAX_AGE_SECONDS["M1"]


def test_fresh_snapshot_accepted() -> None:
    verdict = evaluate_freshness(_snapshot(timeframe="M5", age_seconds=5))
    assert verdict.accepted is True
    assert verdict.reason == ""
    assert verdict.age_seconds is not None and verdict.age_seconds < 10


def test_snapshot_without_timestamps_is_rejected_fail_closed() -> None:
    verdict = evaluate_freshness({"prices": [1.0], "timeframe": "M5"})
    assert verdict.accepted is False
    assert verdict.reason == "timestamp_unknown"


def test_non_dict_snapshot_is_rejected() -> None:
    assert evaluate_freshness(None).accepted is False
    assert evaluate_freshness({}).accepted is False


# ---------------------------------------------------------------------------
# clock anomalies
# ---------------------------------------------------------------------------
def test_clock_running_backwards_rejected() -> None:
    now = datetime.now(timezone.utc)
    snap = {
        "symbol": "XAUUSD",
        "timeframe": "M5",
        # received BEFORE the bar → clock runs backwards.
        "bar_timestamp": _iso(now),
        "received_at": _iso(now - timedelta(seconds=30)),
    }
    verdict = evaluate_freshness(snap)
    assert verdict.accepted is False
    assert verdict.clock_anomaly is True
    assert "clock_anomaly" in verdict.reason


def test_negative_age_is_rejected_not_fresh() -> None:
    now = datetime.now(timezone.utc)
    snap = {
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "bar_timestamp": _iso(now + timedelta(seconds=10)),
        "received_at": _iso(now),
        "age_seconds": -10.0,
    }
    verdict = evaluate_freshness(snap)
    assert verdict.accepted is False
    assert verdict.clock_anomaly is True


def test_future_timestamp_rejected() -> None:
    now = datetime.now(timezone.utc)
    snap = {
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "bar_timestamp": _iso(now + timedelta(seconds=600)),
        "received_at": _iso(now + timedelta(seconds=600)),
    }
    verdict = evaluate_freshness(snap, now=now)
    assert verdict.accepted is False
    assert verdict.clock_anomaly is True
    assert "future" in verdict.reason


def test_small_clock_skew_is_tolerated() -> None:
    now = datetime.now(timezone.utc)
    snap = {
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "bar_timestamp": _iso(now + timedelta(seconds=2)),
        "received_at": _iso(now + timedelta(seconds=2)),
    }
    assert evaluate_freshness(snap, now=now).accepted is True


# ---------------------------------------------------------------------------
# feed loop stamps the freshness triple
# ---------------------------------------------------------------------------
def _loop(queue: EventQueue) -> MarketFeedLoop:
    return MarketFeedLoop(
        queue=queue,
        symbols=["XAUUSD"],
        timeframe="M5",
        connector=FakeConnector({"XAUUSD": _bars()}),
        event_cooldown_s=300.0,
    )


def test_feed_loop_snapshot_carries_freshness_fields() -> None:
    clear_latest_snapshots()
    queue = EventQueue()
    loop = _loop(queue)
    assert loop.poll_once() > 0

    event = queue.peek()[0]
    snap = event.market_snapshot
    for field in ("bar_timestamp", "received_at", "age_seconds", "timeframe", "symbol"):
        assert field in snap, f"snapshot must carry {field}"
    assert snap["timeframe"] == "M5"
    assert snap["symbol"] == "XAUUSD"
    assert snap["bar_timestamp"] is not None
    assert snap["received_at"] is not None
    # Freshly produced snapshot is fresh under its own timeframe.
    assert evaluate_freshness(snap).accepted is True


def test_feed_loop_unparseable_bar_time_yields_null_timestamp() -> None:
    """A bar with no time must not be silently stamped as fresh."""
    bars = _bars()
    bars[-1].time = None
    queue = EventQueue()
    loop = MarketFeedLoop(
        queue=queue,
        symbols=["XAUUSD"],
        timeframe="M5",
        connector=FakeConnector({"XAUUSD": bars}),
    )
    loop.poll_once()
    event = queue.peek()[0]
    assert event.market_snapshot["bar_timestamp"] is None
    # And the gate rejects it (fail-closed).
    assert evaluate_freshness(event.market_snapshot).accepted is False


# ---------------------------------------------------------------------------
# pipeline gate — stale data never reaches the committee
# ---------------------------------------------------------------------------
def test_stale_event_snapshot_blocks_before_committee() -> None:
    clear_latest_snapshots()
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)
    stale = _snapshot(timeframe="M1", age_seconds=600)

    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "XAUUSD", "market_snapshot": stale})

    assert result.status == STATUS_STALE_MARKET_DATA
    assert result.executed is False
    # The committee was NEVER convened as trade-ready context.
    assert supervisor.contexts == []


def test_stale_cached_snapshot_blocks_manual_cycle() -> None:
    clear_latest_snapshots()
    set_latest_snapshot("XAUUSD", _snapshot(timeframe="M1", age_seconds=600))
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)

    result = pipeline.run({"event_type": "MARKET_SCAN", "symbol": "XAUUSD"})

    assert result.status == STATUS_STALE_MARKET_DATA
    assert supervisor.contexts == []
    clear_latest_snapshots()


def test_fresh_snapshot_reaches_committee() -> None:
    clear_latest_snapshots()
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)
    fresh = _snapshot(timeframe="M5", age_seconds=2)

    pipeline.run({"event_type": "BREAKOUT", "symbol": "XAUUSD", "market_snapshot": fresh})

    assert len(supervisor.contexts) == 1
    assert supervisor.contexts[0]["symbol"] == "XAUUSD"


def test_clock_anomaly_blocks_before_committee() -> None:
    clear_latest_snapshots()
    now = datetime.now(timezone.utc)
    bad = {
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "bar_timestamp": _iso(now),
        "received_at": _iso(now - timedelta(seconds=30)),
        "prices": [1.0],
    }
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)

    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "XAUUSD", "market_snapshot": bad})

    assert result.status == STATUS_STALE_MARKET_DATA
    assert result.risk_reason and "clock_anomaly" in result.risk_reason
    assert supervisor.contexts == []


def test_snapshotless_cycle_is_backward_compatible() -> None:
    """No snapshot at all → no stale evidence → historic behaviour preserved."""
    clear_latest_snapshots()
    supervisor = _CapturingSupervisor()
    pipeline = _pipeline(supervisor)

    pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"})

    assert len(supervisor.contexts) == 1


def test_freshness_gate_can_be_disabled() -> None:
    clear_latest_snapshots()
    supervisor = _CapturingSupervisor()
    pipeline = TradingPipeline(
        supervisor=supervisor,
        risk_gate=_NeverCalledGate(),
        freshness_gate_enabled=False,
    )
    stale = _snapshot(timeframe="M1", age_seconds=600)

    pipeline.run({"event_type": "BREAKOUT", "symbol": "XAUUSD", "market_snapshot": stale})

    assert len(supervisor.contexts) == 1


# ---------------------------------------------------------------------------
# stale state visible in UI (ops read model)
# ---------------------------------------------------------------------------
def test_ops_market_snapshot_surfaces_staleness() -> None:
    from ops import readmodels

    clear_latest_snapshots()
    # No snapshot → honestly NO_DATA, never fake fresh.
    no_data = readmodels.market_snapshot("XAUUSD")
    assert no_data["snapshot"]["status"] == "NO_DATA"

    set_latest_snapshot("XAUUSD", _snapshot(timeframe="M5", age_seconds=2))
    fresh = readmodels.market_snapshot("XAUUSD")
    assert fresh["snapshot"]["status"] == "FRESH"
    assert fresh["snapshot"]["fresh"] is True

    set_latest_snapshot("XAUUSD", _snapshot(timeframe="M1", age_seconds=600))
    stale = readmodels.market_snapshot("XAUUSD")
    assert stale["snapshot"]["status"] == "STALE"
    assert stale["snapshot"]["fresh"] is False
    assert stale["snapshot"]["age_seconds"] is not None
    clear_latest_snapshots()


def test_market_health_endpoint_wires_snapshot_freshness() -> None:
    """`/market/health` must embed the snapshot-freshness block (TASK 09)."""
    from src.market import endpoints as market_endpoints
    from src.market import health as health_mod

    clear_latest_snapshots()
    set_latest_snapshot("XAUUSD", _snapshot(timeframe="M5", age_seconds=1))

    # Patch the MT5-reading health probe so the test stays offline; the point
    # under test is the freshness block wiring, not the connector.
    def _fake_health(symbol: str) -> dict:
        return {"symbol": symbol, "status": "HEALTHY"}

    original = health_mod.compute_market_data_health
    health_mod.compute_market_data_health = _fake_health  # type: ignore[attr-defined]
    try:
        import asyncio

        health = asyncio.new_event_loop().run_until_complete(
            market_endpoints.market_data_health("XAUUSD")
        )
        assert "snapshot_freshness" in health
        assert health["snapshot_freshness"]["status"] == "FRESH"
    finally:
        health_mod.compute_market_data_health = original  # type: ignore[attr-defined]
        clear_latest_snapshots()


def test_snapshot_freshness_status_helper() -> None:
    from src.market.endpoints import _snapshot_freshness_status

    clear_latest_snapshots()
    assert _snapshot_freshness_status("XAUUSD")["status"] == "NO_DATA"
    set_latest_snapshot("XAUUSD", _snapshot(timeframe="M5", age_seconds=1))
    assert _snapshot_freshness_status("XAUUSD")["status"] == "FRESH"
    set_latest_snapshot("XAUUSD", _snapshot(timeframe="M1", age_seconds=600))
    assert _snapshot_freshness_status("XAUUSD")["status"] == "STALE"
    clear_latest_snapshots()
