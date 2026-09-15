# -*- coding: utf-8 -*-
"""Tests for PRD_V2 §16 — Context Builder.

Verifies that :class:`ContextBuilder` produces a filtered, size-bounded,
provenance-tagged snapshot for agents, that ordering is deterministic, and
that empty inputs still yield a minimal valid context.
"""

from __future__ import annotations

from orchestration.context_builder import ContextBuilder


class _FixedClock:
    """Deterministic clock returning a fixed ISO timestamp."""

    def __init__(self, stamp="2024-01-01T00:00:00+00:00"):
        self.stamp = stamp

    def __call__(self):
        return self.stamp


def _make_builder(**kwargs):
    return ContextBuilder(clock=_FixedClock(), **kwargs)


class TestBasicBuild:
    def test_empty_inputs_minimal_context(self):
        builder = _make_builder()
        ctx = builder.build(event=None)
        assert isinstance(ctx, dict)
        # Required keys exist even with no data.
        for key in (
            "price_window",
            "relevant_events",
            "open_positions",
            "account_state",
            "memory_hits",
            "strategy_state",
            "provenance",
        ):
            assert key in ctx
        assert ctx["price_window"] == []
        assert ctx["relevant_events"] == []

    def test_price_window_returns_recent(self):
        builder = _make_builder()
        prices = [{"ts": i, "close": 1.0 + i} for i in range(50)]
        ctx = builder.build(
            event={"symbol": "EURUSD"},
            price_window=prices,
            max_price_items=10,
        )
        assert len(ctx["price_window"]) == 10
        # Keeps the most recent entries.
        assert ctx["price_window"][-1]["ts"] == 49

    def test_relevant_events_filtered_by_symbol(self):
        builder = _make_builder()
        events = [
            {"symbol": "EURUSD", "type": "TREND_BULLISH"},
            {"symbol": "GBPUSD", "type": "TREND_BEARISH"},
            {"symbol": "EURUSD", "type": "RSI_OVERBOUGHT"},
        ]
        ctx = builder.build(event={"symbol": "EURUSD"}, events=events)
        assert len(ctx["relevant_events"]) == 2
        assert all(e["symbol"] == "EURUSD" for e in ctx["relevant_events"])

    def test_custom_filters(self):
        builder = _make_builder()
        events = [
            {"symbol": "EURUSD", "type": "TREND_BULLISH", "severity": "high"},
            {"symbol": "EURUSD", "type": "RSI_OVERBOUGHT", "severity": "low"},
        ]
        ctx = builder.build(
            event={"symbol": "EURUSD"},
            events=events,
            filters={"events": lambda e: e.get("severity") == "high"},
        )
        assert len(ctx["relevant_events"]) == 1
        assert ctx["relevant_events"][0]["type"] == "TREND_BULLISH"

    def test_max_items_respected(self):
        builder = _make_builder()
        events = [{"symbol": "EURUSD", "type": f"E{i}"} for i in range(100)]
        ctx = builder.build(
            event={"symbol": "EURUSD"},
            events=events,
            max_items=7,
        )
        assert len(ctx["relevant_events"]) <= 7

    def test_positions_and_account(self):
        builder = _make_builder()
        positions = [
            {"symbol": "EURUSD", "side": "BUY", "volume": 0.1},
            {"symbol": "GBPUSD", "side": "SELL", "volume": 0.2},
        ]
        ctx = builder.build(
            event={"symbol": "EURUSD"},
            positions=positions,
            account_state={"balance": 10000.0, "equity": 10100.0},
        )
        assert len(ctx["open_positions"]) == 1
        assert ctx["open_positions"][0]["symbol"] == "EURUSD"
        assert ctx["account_state"]["balance"] == 10000.0

    def test_memory_hits_relevance(self):
        builder = _make_builder()
        hits = [
            {"symbol": "EURUSD", "text": "past breakout", "score": 0.9},
            {"symbol": "GBPUSD", "text": "unrelated", "score": 0.4},
        ]
        ctx = builder.build(event={"symbol": "EURUSD"}, memory_hits=hits)
        assert len(ctx["memory_hits"]) == 1
        assert ctx["memory_hits"][0]["symbol"] == "EURUSD"

    def test_strategy_state_passthrough(self):
        builder = _make_builder()
        ctx = builder.build(
            event={"symbol": "EURUSD"},
            strategy_state={"strategy": "momentum", "version": "v2"},
        )
        assert ctx["strategy_state"]["strategy"] == "momentum"


class TestProvenance:
    def test_provenance_metadata(self):
        builder = _make_builder()
        ctx = builder.build(
            event={"symbol": "EURUSD"},
            events=[{"symbol": "EURUSD", "type": "BREAKOUT"}],
            account_state={"balance": 1.0},
        )
        prov = ctx["provenance"]
        assert prov["generated_at"] == "2024-01-01T00:00:00+00:00"
        # Each section records source + timestamp.
        assert "relevant_events" in prov["sections"]
        assert prov["sections"]["relevant_events"]["count"] == 1
        assert "source" in prov["sections"]["relevant_events"]


class TestDeterminism:
    def test_ordering_deterministic(self):
        builder = _make_builder()
        events = [
            {"symbol": "EURUSD", "type": "B", "priority": 2},
            {"symbol": "EURUSD", "type": "A", "priority": 1},
        ]
        ctx1 = builder.build(event={"symbol": "EURUSD"}, events=list(events))
        ctx2 = builder.build(event={"symbol": "EURUSD"}, events=list(events))
        assert [e["type"] for e in ctx1["relevant_events"]] == [
            e["type"] for e in ctx2["relevant_events"]
        ]

    def test_never_dumps_everything(self):
        builder = _make_builder()
        prices = [{"ts": i} for i in range(5000)]
        ctx = builder.build(event={"symbol": "EURUSD"}, price_window=prices)
        assert len(ctx["price_window"]) <= builder.max_items
