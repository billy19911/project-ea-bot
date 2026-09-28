# -*- coding: utf-8 -*-
"""Tests for the T3b entry-context bridge (production learning-loop closure).

Background: T3 wired the two AI learning loops into ``_on_review``, but the
loops could never fire in production because ``ReviewRecord`` did not carry
the raw close context (``trade_result`` / ``agent_outputs`` / ``news_events``)
— and the close path (broker position disappearance) has no agent context of
its own.

T3b closes that gap:

1. ``review.entry_context`` — a bounded, ticket-keyed registry written when an
   entry executes and read when the position closes;
2. ``TradingPipeline._remember_entry_context`` — captures agent outputs /
   news events / regime at execution time;
3. ``ReviewRecord`` now carries ``trade_result`` / ``agent_outputs`` /
   ``news_events``, and ``_to_review_record`` passes them through;
4. ``PositionCloseDetector`` merges the registered entry context into the
   synthetic close record so the learning loops receive real material.

Everything is fail-safe: a missing entry context never breaks the close path.
"""

from __future__ import annotations

import pytest

from orchestration.pipeline import STATUS_EXECUTED, TradingPipeline
from review.auto_trigger import ReviewAutoTrigger, _to_review_record
from review.close_detector import PositionCloseDetector
from review.entry_context import (
    clear_entry_contexts,
    entry_context_size,
    get_entry_context,
    pop_entry_context,
    remember_entry_context,
    set_entry_context_store,
)
from risk.gate import GateDecision


@pytest.fixture(autouse=True)
def _clean_registry():
    # Isolate the in-memory registry: disable persistence so these tests never
    # touch a real JSONL file (persistence has its own dedicated tests).
    set_entry_context_store(None, disabled=True)
    clear_entry_contexts()
    yield
    set_entry_context_store(None, disabled=True)
    clear_entry_contexts()


# ---------------------------------------------------------------------------
# Fakes (mirror test_entry_cooldown_guard.py — simplest EXECUTED cycle)
# ---------------------------------------------------------------------------
class FakeSupervisor:
    def __init__(self, result=None) -> None:
        self._result = result

    def analyze(self, context):
        return self._result


class FakeRiskGate:
    def __init__(self, decision: GateDecision | None = None) -> None:
        self._decision = decision

    def validate_proposal(self, proposal, account_state, current_positions, market_info):
        return self._decision


class FakeExecutionEngine:
    def __init__(self, result=None) -> None:
        self._result = result

    def execute_order(self, request):
        return self._result


class _ExecResult:
    success = True
    ticket = 777
    error_code = 0
    error_message = ""
    retries = 0
    position_opened = {"symbol": "EURUSD", "positions_count": 1}


def _approved() -> GateDecision:
    return GateDecision(
        approved=True,
        reason="All risk checks passed",
        checks_passed={"stop_loss": True},
        metrics_snapshot={"risk_reward_ratio": 2.0},
    )


def _synthesis():
    return {
        "agent": "supervisor",
        "event_type": "BREAKOUT",
        "overall_signal": "BUY",
        "overall_confidence": 0.8,
        "agent_results": {
            "momentum": {"confidence": 0.8, "signal": "BUY"},
            "structure": {"confidence": 0.6, "signal": "BUY"},
        },
        "summary": "stub",
        "proposal": {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1100,
            "size": 0.1,
            "confidence": 0.8,
        },
    }


def _event():
    return {
        "event_id": "evt-t3b",
        "event_type": "BREAKOUT",
        "symbol": "EURUSD",
        "severity": 0.9,
        "description": "price broke out",
    }


def _context():
    return {
        "event_type": "BREAKOUT",
        "symbol": "EURUSD",
        "regime": "trending",
        "sentiment": {
            "economic_events": [
                {
                    "title": "NFP",
                    "country": "US",
                    "impact": "High",
                    "forecast": "200K",
                    "actual": "150K",
                }
            ]
        },
        "account_state": {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
            "used_margin": 100.0,
        },
        "current_positions": [],
        "market_info": {"spread_pips": 1.0, "ask": 1.1001, "bid": 1.0999},
    }


# ---------------------------------------------------------------------------
# 1. Registry — roundtrip, pop, bounding
# ---------------------------------------------------------------------------
def test_registry_roundtrip():
    remember_entry_context(101, {"symbol": "EURUSD", "regime": "trending"})
    ctx = get_entry_context(101)
    assert ctx["symbol"] == "EURUSD"
    assert ctx["regime"] == "trending"
    assert entry_context_size() == 1


def test_registry_pop_consumes():
    remember_entry_context("202", {"symbol": "XAUUSD"})
    assert pop_entry_context("202")["symbol"] == "XAUUSD"
    assert pop_entry_context("202") == {}
    assert entry_context_size() == 0


def test_registry_ignores_empty_ticket():
    remember_entry_context(None, {"symbol": "EURUSD"})
    remember_entry_context("", {"symbol": "EURUSD"})
    assert entry_context_size() == 0


def test_registry_is_bounded():
    for i in range(600):
        remember_entry_context(i, {"symbol": "S"})
    assert entry_context_size() == 500
    # Oldest evicted, newest retained.
    assert get_entry_context(0) == {}
    assert get_entry_context(599)["symbol"] == "S"


def test_registry_missing_returns_empty():
    assert get_entry_context("nope") == {}


# ---------------------------------------------------------------------------
# 2. Pipeline — captures entry context on a successful execution
# ---------------------------------------------------------------------------
def _pipeline() -> TradingPipeline:
    return TradingPipeline(
        supervisor=FakeSupervisor(_synthesis()),
        risk_gate=FakeRiskGate(_approved()),
        execution_engine=FakeExecutionEngine(_ExecResult()),
    )


def test_pipeline_remembers_entry_context_on_success():
    pipeline = _pipeline()
    result = pipeline.run(_event(), _context())

    assert result.status == STATUS_EXECUTED
    ctx = get_entry_context(777)
    assert ctx, "entry context must be registered under the execution ticket"
    assert ctx["symbol"] == "EURUSD"
    assert ctx["direction"] == "BUY"
    assert ctx["agent_outputs"] == {
        "momentum": {"confidence": 0.8, "signal": "BUY"},
        "structure": {"confidence": 0.6, "signal": "BUY"},
    }
    assert ctx["news_events"] == [
        {
            "title": "NFP",
            "country": "US",
            "impact": "High",
            "forecast": "200K",
            "actual": "150K",
        }
    ]
    assert ctx["regime"] == "trending"
    assert ctx["entry_price"] == pytest.approx(1.1000)


def test_pipeline_regime_from_market_state_fallback():
    pipeline = _pipeline()
    context = _context()
    context.pop("regime")
    context["market_state"] = {"regime": "ranging"}
    result = pipeline.run(_event(), context)

    assert result.status == STATUS_EXECUTED
    assert get_entry_context(777)["regime"] == "ranging"


def test_pipeline_skips_capture_when_no_ticket():
    class _NoTicket:
        success = True
        ticket = None
        error_code = 0
        error_message = ""
        retries = 0
        position_opened = None

    pipeline = TradingPipeline(
        supervisor=FakeSupervisor(_synthesis()),
        risk_gate=FakeRiskGate(_approved()),
        execution_engine=FakeExecutionEngine(_NoTicket()),
    )
    result = pipeline.run(_event(), _context())

    assert result.status == STATUS_EXECUTED
    assert entry_context_size() == 0


# ---------------------------------------------------------------------------
# 3. ReviewRecord — carries the raw close context
# ---------------------------------------------------------------------------
def _closed_trade_with_context() -> dict:
    return {
        "trade_id": "T-42",
        "ticket": 777,
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_price": 1.1000,
        "close_price": 1.1050,
        "pnl": 120.0,
        "status": "CLOSED",
        "regime": "trending",
        "agent_outputs": {"momentum": {"confidence": 0.8}},
        "news_events": [{"title": "NFP", "country": "US", "impact": "High"}],
    }


def test_to_review_record_keeps_context():
    record = _to_review_record(_closed_trade_with_context())
    assert record["symbol"] == "EURUSD"
    assert record["agent_outputs"] == {"momentum": {"confidence": 0.8}}
    assert record["news_events"] == [{"title": "NFP", "country": "US", "impact": "High"}]
    # regime fallback: regime_at_entry missing -> regime key used
    assert record["regime_at_entry"] == "trending"


def test_review_record_carries_context_to_callback():
    seen: list = []
    trigger = ReviewAutoTrigger(on_review=seen.append)
    trigger.on_position_closed(_closed_trade_with_context())

    assert len(seen) == 1
    rec = seen[0]
    # The exact attributes ``_on_review`` reads in production:
    assert rec.agent_outputs == {"momentum": {"confidence": 0.8}}
    assert rec.news_events == [{"title": "NFP", "country": "US", "impact": "High"}]
    assert rec.trade_result["symbol"] == "EURUSD"
    assert rec.trade_result["direction"] == "BUY"
    assert rec.trade_result["pnl"] == 120.0
    assert rec.trade_result["regime"] == "trending"
    # to_dict stays JSON-safe (learning payloads are NOT serialised there).
    payload = rec.to_dict()
    assert payload["trade_id"] == "T-42"
    assert "agent_outputs" not in payload


def test_review_record_defaults_keep_old_constructor_working():
    trigger = ReviewAutoTrigger()
    rec = trigger.on_position_closed(
        {
            "trade_id": "T-OLD",
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.1,
            "close_price": 1.2,
            "pnl": 10.0,
            "status": "CLOSED",
        }
    )
    assert rec is not None
    assert rec.agent_outputs == {}
    assert rec.news_events == []
    assert rec.trade_result["symbol"] == "EURUSD"


# ---------------------------------------------------------------------------
# 4. Close detector — bridges entry context into the close record
# ---------------------------------------------------------------------------
def test_close_detector_bridges_entry_context():
    remember_entry_context(
        777,
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "agent_outputs": {"momentum": {"confidence": 0.8}},
            "news_events": [{"title": "NFP", "country": "US"}],
            "regime": "trending",
            "entry_price": 1.1000,
        },
    )
    detector = PositionCloseDetector()
    detector.observe(
        [
            {
                "ticket": 777,
                "symbol": "EURUSD",
                "side": "BUY",
                "price_open": 1.1,
                "profit": 5.0,
            }
        ]
    )
    closed = detector.observe([])

    assert len(closed) == 1
    rec = closed[0]
    assert rec["agent_outputs"] == {"momentum": {"confidence": 0.8}}
    assert rec["news_events"] == [{"title": "NFP", "country": "US"}]
    assert rec["regime"] == "trending"


def test_close_detector_without_context_is_unchanged():
    detector = PositionCloseDetector()
    detector.observe(
        [
            {
                "ticket": 9,
                "symbol": "EURUSD",
                "side": "BUY",
                "price_open": 1.1,
                "profit": 1.0,
            }
        ]
    )
    closed = detector.observe([])

    assert len(closed) == 1
    assert "agent_outputs" not in closed[0]
    assert "news_events" not in closed[0]


# ---------------------------------------------------------------------------
# 6. Paper-trading close path — same bridge via _trigger_review
# ---------------------------------------------------------------------------
def test_paper_trigger_review_merges_entry_context():
    from types import SimpleNamespace

    from paper.simulated_execution import SimulatedExecutionEngine

    engine = SimulatedExecutionEngine(spread_config={"EURUSD": 0.0002})
    remember_entry_context(
        555,
        {
            "agent_outputs": {"momentum": {"confidence": 0.9}},
            "news_events": [{"title": "CPI", "country": "US"}],
            "regime": "volatile",
        },
    )
    position = SimpleNamespace(
        ticket=555,
        side="BUY",
        entry_price=1.1000,
    )
    close_trade = SimpleNamespace(slippage_applied=0.0)

    seen: list = []
    import review.auto_trigger as auto_trigger_mod

    original = auto_trigger_mod.on_position_closed
    auto_trigger_mod.on_position_closed = seen.append
    try:
        engine._trigger_review(
            trade_id="555",
            symbol="EURUSD",
            side="BUY",
            position=position,
            close_price=1.1050,
            pnl=50.0,
            close_trade=close_trade,
        )
    finally:
        auto_trigger_mod.on_position_closed = original

    assert len(seen) == 1
    payload = seen[0]
    assert payload["agent_outputs"] == {"momentum": {"confidence": 0.9}}
    assert payload["news_events"] == [{"title": "CPI", "country": "US"}]
    assert payload["regime"] == "volatile"
    assert payload["ticket"] == 555
    # Context consumed — a duplicate close cannot reuse stale material.
    assert pop_entry_context(555) == {}


def test_paper_trigger_review_without_context_is_safe():
    from types import SimpleNamespace

    from paper.simulated_execution import SimulatedExecutionEngine

    engine = SimulatedExecutionEngine(spread_config={"EURUSD": 0.0002})
    position = SimpleNamespace(side="BUY", entry_price=1.1000)  # no ticket
    close_trade = SimpleNamespace(slippage_applied=0.0)

    seen: list = []
    import review.auto_trigger as auto_trigger_mod

    original = auto_trigger_mod.on_position_closed
    auto_trigger_mod.on_position_closed = seen.append
    try:
        engine._trigger_review(
            trade_id="EURUSD",
            symbol="EURUSD",
            side="BUY",
            position=position,
            close_price=1.1050,
            pnl=50.0,
            close_trade=close_trade,
        )
    finally:
        auto_trigger_mod.on_position_closed = original

    assert len(seen) == 1
    assert "agent_outputs" not in seen[0]


# ---------------------------------------------------------------------------
# 5. End-to-end: entry -> close -> review callback receives real material
# ---------------------------------------------------------------------------
def test_end_to_end_entry_to_close_learning_material():
    pipeline = _pipeline()
    assert pipeline.run(_event(), _context()).status == STATUS_EXECUTED

    seen: list = []
    trigger = ReviewAutoTrigger(on_review=seen.append)
    detector = PositionCloseDetector(on_close=trigger.on_position_closed)

    detector.observe(
        [
            {
                "ticket": 777,
                "symbol": "EURUSD",
                "side": "BUY",
                "price_open": 1.1,
                "profit": 25.0,
            }
        ]
    )
    detector.observe([])  # position closed

    assert len(seen) == 1
    rec = seen[0]
    assert rec.agent_outputs == {
        "momentum": {"confidence": 0.8, "signal": "BUY"},
        "structure": {"confidence": 0.6, "signal": "BUY"},
    }
    assert rec.news_events[0]["title"] == "NFP"
    assert rec.trade_result["regime"] == "trending"
    # Exactly what ``_on_review`` gates on before feeding the loops:
    assert rec.trade_result and rec.agent_outputs
