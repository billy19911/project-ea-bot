# -*- coding: utf-8 -*-
"""Tests for Phase 4 — PostTradeReviewAgent (review department specialist).

The review agent reviews CLOSED trades to extract deterministic, rule-based
lessons and persists them to the existing review infrastructure
(``review.TradeReviewer`` + ``review.classify_root_cause`` +
``learning.LearningMemory``) without touching MT5 or the risk gate.

Contract:
* identity — ``name="post_trade_review"``, ``agent_type="review"``;
* ``can_handle`` — accepts ``TRADE_CLOSE*`` / ``POST_TRADE_REVIEW``, rejects
  market events (``TREND_*``) and risk events (``RISK_*``);
* ``analyze`` — Supervisor-compatible dict
  (``agent``/``signal``/``confidence``/``reasons``), never raises;
* fail-closed — missing closed-trade data yields ``UNSUPPORTED`` with
  confidence 0.0 and no lessons stored;
* lessons — deterministic rules (not narrative), stored in an injectable
  lesson store; win/loss/breakeven handled distinctly;
* safety — never touches MT5 / risk gate (no forbidden permissions).
"""

from __future__ import annotations

import pytest

from agents.analysts.review_agent import PostTradeReviewAgent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _RecordingLessonStore:
    """Minimal lesson sink used to observe persistence."""

    def __init__(self) -> None:
        self.lessons: list[dict] = []

    def add_lesson(self, lesson: dict) -> None:
        self.lessons.append(dict(lesson))


def _closed_trade(**overrides):
    trade = {
        "trade_id": "T-100",
        "symbol": "XAUUSD",
        "side": "buy",
        "entry_price": 2000.0,
        "exit_price": 2010.0,
        "pnl": 100.0,
        "outcome": "win",
        "signal": "BULLISH",
        "actual_direction": "BULLISH",
        "duration": 3600,
        "price_history": [2000.0, 2005.0, 2010.0],
    }
    trade.update(overrides)
    return trade


@pytest.fixture()
def store():
    return _RecordingLessonStore()


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_identity():
    agent = PostTradeReviewAgent()
    assert agent.name == "post_trade_review"
    assert agent.agent_type == "review"


def test_priority_is_low():
    """Post-trade review is not time-critical."""
    from agents.base import AgentPriority

    assert PostTradeReviewAgent().priority == AgentPriority.LOW


def test_no_forbidden_permissions():
    """Review must never be able to reach MT5 / risk gate / execution."""
    agent = PostTradeReviewAgent()
    forbidden = {"SUBMIT_TO_RISK_GATE", "PROPOSE_EXECUTION", "SEND_TO_MT5"}
    assert not (set(agent.permissions) & forbidden)


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


def test_can_handle_trade_close_events():
    agent = PostTradeReviewAgent()
    assert agent.can_handle("TRADE_CLOSE", {}) is True
    assert agent.can_handle("TRADE_CLOSED", {}) is True
    assert agent.can_handle("POST_TRADE_REVIEW", {}) is True


def test_can_handle_rejects_market_and_risk_events():
    agent = PostTradeReviewAgent()
    assert agent.can_handle("TREND_BULLISH", {}) is False
    assert agent.can_handle("MOMENTUM_BULLISH", {}) is False
    assert agent.can_handle("RISK_CHECK", {}) is False
    assert agent.can_handle("DRAWDOWN_WARNING", {}) is False


# ---------------------------------------------------------------------------
# analyze — win / loss / breakeven
# ---------------------------------------------------------------------------


def test_analyze_win_returns_supervisor_dict(store):
    agent = PostTradeReviewAgent(lesson_store=store)
    result = agent.analyze({"closed_trade": _closed_trade()})

    assert result["agent"] == "post_trade_review"
    assert result["signal"] == "NEUTRAL"  # review never signals direction
    assert isinstance(result["confidence"], float)
    assert result["confidence"] > 0
    assert isinstance(result["reasons"], list) and result["reasons"]
    assert result["outcome"] == "win"


def test_analyze_win_stores_lesson(store):
    agent = PostTradeReviewAgent(lesson_store=store)
    agent.analyze({"closed_trade": _closed_trade()})

    assert len(store.lessons) == 1
    lesson = store.lessons[0]
    assert lesson["trade_id"] == "T-100"
    assert lesson["outcome"] == "win"
    assert isinstance(lesson["lesson"], str) and lesson["lesson"]


def test_analyze_loss_extracts_wrong_direction_lesson(store):
    """A loss where the signal was opposite the market move yields a rule."""
    agent = PostTradeReviewAgent(lesson_store=store)
    trade = _closed_trade(
        trade_id="T-200",
        side="buy",
        exit_price=1990.0,
        pnl=-100.0,
        outcome="loss",
        signal="BULLISH",
        actual_direction="BEARISH",
        price_history=[2000.0, 1995.0, 1990.0],
    )
    result = agent.analyze({"closed_trade": trade})

    assert result["outcome"] == "loss"
    assert result["followed_plan"] is False
    lesson = store.lessons[0]
    assert lesson["outcome"] == "loss"


def test_analyze_breakeven_is_neutral(store):
    agent = PostTradeReviewAgent(lesson_store=store)
    trade = _closed_trade(pnl=0.0, outcome="breakeven", exit_price=2000.0)
    result = agent.analyze({"closed_trade": trade})

    assert result["outcome"] == "breakeven"
    assert result["signal"] == "NEUTRAL"


def test_followed_plan_detection(store):
    agent = PostTradeReviewAgent(lesson_store=store)
    followed = agent.analyze(
        {"closed_trade": _closed_trade(signal="BULLISH", actual_direction="BULLISH")}
    )
    deviated = agent.analyze(
        {
            "closed_trade": _closed_trade(
                trade_id="T-300", signal="BULLISH", actual_direction="BEARISH"
            )
        }
    )
    assert followed["followed_plan"] is True
    assert deviated["followed_plan"] is False


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


def test_missing_trade_data_is_unsupported(store):
    agent = PostTradeReviewAgent(lesson_store=store)
    result = agent.analyze({})

    assert result["status"] == "UNSUPPORTED"
    assert result["confidence"] == 0.0
    assert store.lessons == []


def test_malformed_trade_data_never_raises(store):
    agent = PostTradeReviewAgent(lesson_store=store)
    for bad in (
        {"closed_trade": None},
        {"closed_trade": "not-a-dict"},
        {"closed_trade": {}},
    ):
        result = agent.analyze(bad)
        assert isinstance(result, dict)
        assert result.get("signal") == "NEUTRAL"


def test_store_failure_never_raises():
    class _BrokenStore:
        def add_lesson(self, lesson):
            raise RuntimeError("disk full")

    agent = PostTradeReviewAgent(lesson_store=_BrokenStore())
    result = agent.analyze({"closed_trade": _closed_trade()})
    # Review still succeeds; persistence failure is swallowed (fail-safe).
    assert isinstance(result, dict)
    assert result.get("signal") == "NEUTRAL"


# ---------------------------------------------------------------------------
# Lessons are rules, not narrative
# ---------------------------------------------------------------------------


def test_lessons_are_deterministic_rules(store):
    agent = PostTradeReviewAgent(lesson_store=store)
    agent.analyze({"closed_trade": _closed_trade()})
    lesson = store.lessons[0]

    assert "rule" in lesson
    # Deterministic: same input twice → identical rule text.
    store.lessons.clear()
    agent.analyze({"closed_trade": _closed_trade()})
    assert store.lessons[0]["rule"] == lesson["rule"]


def test_same_input_produces_same_result(store):
    agent = PostTradeReviewAgent(lesson_store=store)
    first = agent.analyze({"closed_trade": _closed_trade()})
    second = agent.analyze({"closed_trade": _closed_trade()})
    assert first["reasons"] == second["reasons"]
