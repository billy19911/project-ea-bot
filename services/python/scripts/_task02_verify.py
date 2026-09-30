# -*- coding: utf-8 -*-
"""TASK 02 runtime verification (read-only, no MT5, no execution).

Exercises the REAL production objects end-to-end:

    MarketFeedLoop (fake connector) → EventQueue → AutonomousScheduler(event_gate)
    → EventGate → (pipeline stub)

and prints the wake-cause trace so the exact cause of every analysis is visible.

Run:  .venv/Scripts/python.exe scripts/_task02_verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from trading.event_classes import EventGate, classify_event_class  # noqa: E402
from trading.event_engine import EventQueue  # noqa: E402
from trading.feed_loop import MarketFeedLoop  # noqa: E402
from trading.scheduler import AutonomousScheduler  # noqa: E402


class _FakeConnector:
    """Minimal read-only connector returning a fixed OHLC series."""

    def __init__(self, bars):
        self._bars = bars

    def get_ohlc(self, symbol, timeframe, count):  # noqa: ARG002
        return list(self._bars)


class _CountingPipeline:
    """Records every committee cycle the scheduler actually runs."""

    def __init__(self):
        self.calls = []

    def run(self, event, context=None):  # noqa: ARG002
        et = getattr(event.event_type, "value", event.event_type)
        sym = getattr(event, "symbol", "")
        self.calls.append((sym, et))
        from orchestration.pipeline import PipelineResult

        return PipelineResult(event_id=sym, decision="WAIT", status="NO_TRADE")


def _bars(closes, start=0):
    out = []
    for i, c in enumerate(closes):
        out.append(
            {
                "symbol": "XAUUSD",
                "open": c,
                "high": c + 1,
                "low": c - 1,
                "close": c,
                "volume": 100.0,
                "time": f"2024-01-01T00:{start + i:02d}:00",
            }
        )
    return out


def main() -> int:
    failures = []
    print("=" * 72)
    print("TASK 02 RUNTIME VERIFICATION — event-driven supervisor / wake model")
    print("=" * 72)

    # ------------------------------------------------------------------
    # Scenario A: NO EVENT → supervisor idle (no fixed timer)
    # ------------------------------------------------------------------
    queue = EventQueue()
    pipeline = _CountingPipeline()
    scheduler = AutonomousScheduler(
        queue=queue, pipeline=pipeline, poll_interval=0.01, event_gate=EventGate()
    )
    processed = scheduler.process_available()
    print(f"\n[A] NO EVENT        -> processed={processed} committee_calls={len(pipeline.calls)}")
    if processed != 0 or pipeline.calls:
        failures.append("A: idle supervisor ran a cycle with an empty queue")

    # ------------------------------------------------------------------
    # Scenario B: QUALIFYING EVENT → wake → committee
    # ------------------------------------------------------------------
    queue = EventQueue()
    pipeline = _CountingPipeline()
    scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
    from trading.events import DetectedEvent, EventTypes

    qual = DetectedEvent(
        event_type=EventTypes.BREAKOUT,
        severity=0.7,
        description="breakout",
        timestamp="2024-01-01T00:05:00",
        symbol="XAUUSD",
    )
    qual.bar_time = "bar-A"
    queue.enqueue(qual)
    processed = scheduler.process_available()
    print(f"\n[B] QUALIFYING EVENT -> processed={processed} committee_calls={pipeline.calls}")
    if processed != 1 or pipeline.calls != [("XAUUSD", "BREAKOUT")]:
        failures.append("B: qualifying event did not run the committee exactly once")

    # ------------------------------------------------------------------
    # Scenario C: DUPLICATE EVENT → no duplicate committee cycle
    # ------------------------------------------------------------------
    queue = EventQueue()
    pipeline = _CountingPipeline()
    scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
    for _ in range(4):
        dup = DetectedEvent(
            event_type=EventTypes.BREAKOUT,
            severity=0.7,
            description="breakout",
            timestamp="2024-01-01T00:05:00",
            symbol="XAUUSD",
        )
        dup.bar_time = "bar-A"
        queue.enqueue(dup)
    processed = scheduler.process_available()
    print(
        f"\n[C] DUPLICATE x4    -> processed={processed} committee_calls={len(pipeline.calls)}"
        f" gated={scheduler.stats()['events_gated']}"
    )
    if processed != 1 or len(pipeline.calls) != 1:
        failures.append("C: duplicate events created duplicate committee cycles")

    # ------------------------------------------------------------------
    # Scenario D: HOUSEKEEPING (RISK_*) → never a trade proposal
    # ------------------------------------------------------------------
    queue = EventQueue()
    pipeline = _CountingPipeline()
    scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
    queue.enqueue({"event_type": "RISK_DRAWDOWN", "symbol": "XAUUSD", "drawdown": 0.2})
    queue.enqueue({"event_type": "RECONCILIATION", "symbol": "XAUUSD"})
    queue.enqueue({"event_type": "HEALTH_CHECK", "symbol": "XAUUSD"})
    processed = scheduler.process_available()
    print(
        f"\n[D] HOUSEKEEPING x3 -> processed={processed} committee_calls={len(pipeline.calls)}"
        f" gated={scheduler.stats()['events_gated']}"
    )
    if processed != 0 or pipeline.calls:
        failures.append("D: housekeeping events reached the committee")

    # ------------------------------------------------------------------
    # Scenario E: REAL feed loop → queue → gated scheduler
    # ------------------------------------------------------------------
    queue = EventQueue()
    pipeline = _CountingPipeline()
    scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
    connector = _FakeConnector(_bars([100 + i * 0.5 for i in range(40)]))
    feed = MarketFeedLoop(
        queue=queue,
        symbols=["XAUUSD"],
        interval_s=15.0,
        connector=connector,
        session_provider=lambda s: {"open": True, "reason": "test"},  # noqa: ARG005
        on_emit=scheduler.wake,
    )
    # Poll three times with IDENTICAL data (deduped by feed fingerprint) then
    # once with new data.
    emitted_1 = feed.poll_once()
    emitted_2 = feed.poll_once()  # identical → feed fingerprint dedup
    connector._bars = _bars(
        [100 + i * 0.5 for i in range(40)] + [_bars([120])[0]["close"]], start=40
    )
    emitted_3 = feed.poll_once()
    print(
        f"\n[E] FEED POLLS      -> emitted(1st)={emitted_1} emitted(identical)={emitted_2}"
        f" emitted(new-data)={emitted_3} queue={len(queue)}"
    )
    if emitted_2 != 0:
        failures.append("E: identical feed poll was not deduped")
    processed = scheduler.process_available()
    print(f"    -> processed={processed} committee_calls={len(pipeline.calls)}")

    # ------------------------------------------------------------------
    # Wake-cause trace
    # ------------------------------------------------------------------
    print("\n[TRACE] recent event wake causes (newest first):")
    for entry in scheduler.recent_event_traces(limit=10):
        print(
            f"    {entry['event_type']:18} cause={entry['wake_cause']:28}"
            f" allowed={entry['gate_allowed']} status={entry['status']}"
        )

    print("\n" + "=" * 72)
    print("CLASSIFY SAMPLE:")
    for et in (
        "BREAKOUT",
        "TREND_BULLISH",
        "RISK_DRAWDOWN",
        "RECONCILIATION",
        "NEWS_HIGH_IMPACT",
        "TRADE_CLOSE",
        "RANDOM_X",
    ):
        print(f"    {et:18} -> {classify_event_class(et).value}")

    print("\n" + "=" * 72)
    if failures:
        print("RUNTIME VERIFICATION: FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("RUNTIME VERIFICATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
