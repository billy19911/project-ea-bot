# -*- coding: utf-8 -*-
"""Tests for the Entry/SL/TP1/TP2/TPmax reporting wiring (FOKUS #2).

Covers the seam between the pipeline and the Telegram reports:

* ``TradingPipeline`` attaches a ``levels`` ladder to every result — the real
  order ladder when a proposal exists (source "order"), an indicative ATR
  ladder for no-trade cycles (source "analysis"), nothing when evidence is
  missing (never fabricated),
* ``format_pipeline_report`` / ``format_pipeline_digest`` render the ladder
  as a readable multi-line "📐 RENCANA" block (Entry → TP1 → TP2 → TPmax → SL),
* ``summarize_pipeline_result`` passes the ladder through to the digest.

No network and no MT5 are used.
"""

from __future__ import annotations

from orchestration.pipeline import TradingPipeline
from risk.gate import GateDecision
from src.telegram.notifier import (
    format_pipeline_digest,
    format_pipeline_report,
    summarize_pipeline_result,
)

# ---------------------------------------------------------------------------
# Test doubles (mirrors of test_pipeline_orchestration — self-contained)
# ---------------------------------------------------------------------------


class FakeSupervisor:
    def __init__(self, result=None) -> None:
        self._result = result
        self.calls: list[dict] = []

    def analyze(self, context):
        self.calls.append(context)
        return self._result


class FakeRiskGate:
    def __init__(self, decision: GateDecision | None = None) -> None:
        self._decision = decision
        self.calls: list[tuple] = []

    def validate_proposal(
        self, proposal, account_state, current_positions, market_info
    ):
        self.calls.append((proposal, account_state, current_positions, market_info))
        return self._decision


class _ExecResult:
    success = True
    ticket = 555
    error_code = 0
    error_message = ""
    retries = 0
    position_opened = {"symbol": "EURUSD", "positions_count": 1}


class FakeExecutionEngine:
    def __init__(self) -> None:
        self.calls: list = []

    def execute_order(self, request):
        self.calls.append(request)
        return _ExecResult()


def _approved() -> GateDecision:
    return GateDecision(
        approved=True,
        reason="All risk checks passed",
        checks_passed={"stop_loss": True, "risk_reward": True},
        metrics_snapshot={"risk_reward_ratio": 2.0},
    )


def _pipeline(supervisor, gate) -> TradingPipeline:
    return TradingPipeline(
        supervisor=supervisor,
        risk_gate=gate,
        execution_engine=FakeExecutionEngine(),
    )


def _context(**extra) -> dict:
    base = {
        "event_type": "MARKET_SCAN",
        "symbol": "XAUUSD",
        "account_state": {"equity": 10_000.0, "balance": 10_000.0},
        "current_positions": [],
        "market_info": {"spread_pips": 1.0},
        "volatility": {"price": 2000.0, "atr": 2.0},
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Pipeline → levels on the result
# ---------------------------------------------------------------------------
def test_no_trade_cycle_gets_indicative_ladder() -> None:
    analysis = {
        "agent": "supervisor",
        "overall_signal": "BULLISH",
        "overall_confidence": 0.55,
        "summary": "market_lead: BULLISH (conf=0.55)",
    }
    result = _pipeline(FakeSupervisor(analysis), FakeRiskGate(_approved())).run(
        {"event_type": "MARKET_SCAN", "symbol": "XAUUSD"}, _context()
    )

    levels = result.levels
    assert levels is not None
    assert levels["source"] == "analysis"
    assert levels["direction"] == "BUY"
    assert levels["entry"] == 2000.0
    assert levels["sl"] == 1997.0  # 1.5 x ATR
    assert levels["tp1"] == 2003.0  # 1R
    assert levels["tp2"] == 2006.0  # 2R (= project TP)
    assert levels["tpmax"] == 2009.0  # 3R


def test_proposal_cycle_gets_order_ladder() -> None:
    analysis = {
        "agent": "supervisor",
        "event_type": "BREAKOUT",
        "overall_signal": "BUY",
        "overall_confidence": 0.8,
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
    result = _pipeline(FakeSupervisor(analysis), FakeRiskGate(_approved())).run(
        {"event_id": "e1", "event_type": "BREAKOUT", "symbol": "EURUSD"},
        _context(symbol="EURUSD"),
    )

    levels = result.levels
    assert levels is not None
    assert levels["source"] == "order"
    assert levels["sl"] == 1.0950  # the exact proposal stop
    assert levels["tp1"] == 1.1050
    assert levels["tp2"] == 1.1100  # proposal TP preserved
    assert levels["tpmax"] == 1.1150
    # The ladder is serialised with the result for the notifier.
    assert result.to_dict()["levels"]["source"] == "order"


def test_proposal_without_stop_is_completed_from_market_evidence() -> None:
    """A live proposal without SL/TP is completed from the ATR in the market
    evidence (``volatility.atr``), so the report ladder reflects the completed
    order values — consistent with what the gate validates.

    Regression: previously the completion step could not see the ATR living in
    ``volatility`` (feed-loop shape), the gate rejected ``stop_loss``, and the
    report fell back to an indicative ladder. Now completion succeeds and the
    ladder source is ``order``.
    """
    analysis = {
        "agent": "supervisor",
        "overall_signal": "BULLISH",
        "overall_confidence": 0.7,
        "summary": "market_lead: BULLISH (conf=0.70)",
        "proposal": {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2000.0,
            "confidence": 0.8,
            # no stop_loss / take_profit → completed from volatility ATR below.
        },
    }
    rejected = GateDecision(
        approved=False,
        reason="REJECTED: failed checks \u2014 stop_loss",
        checks_passed={"stop_loss": False},
        metrics_snapshot={},
    )
    result = _pipeline(FakeSupervisor(analysis), FakeRiskGate(rejected)).run(
        {"event_id": "e2", "event_type": "BREAKOUT", "symbol": "XAUUSD"}, _context()
    )

    assert result.risk_approved is False
    levels = result.levels
    assert levels is not None
    assert levels["source"] == "order"  # completed from the volatility ATR
    assert levels["entry"] == 2000.0
    assert levels["sl"] == 1997.0  # 1.5 x ATR completed into the proposal


def test_proposal_stop_is_never_overridden_by_completion() -> None:
    """A proposal that already carries a stop keeps it verbatim in the ladder."""
    analysis = {
        "agent": "supervisor",
        "overall_signal": "BULLISH",
        "overall_confidence": 0.7,
        "summary": "market_lead: BULLISH (conf=0.70)",
        "proposal": {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2000.0,
            "stop_loss": 1998.5,  # explicit stop, must never be overridden
            "confidence": 0.8,
        },
    }
    result = _pipeline(FakeSupervisor(analysis), FakeRiskGate(_approved())).run(
        {"event_id": "e3", "event_type": "BREAKOUT", "symbol": "XAUUSD"}, _context()
    )

    levels = result.levels
    assert levels is not None
    assert levels["sl"] == 1998.5  # the exact proposal stop, not the ATR stop


def test_no_levels_without_market_evidence() -> None:
    analysis = {
        "agent": "supervisor",
        "overall_signal": "BULLISH",
        "summary": "market_lead: BULLISH",
    }
    result = _pipeline(FakeSupervisor(analysis), FakeRiskGate(_approved())).run(
        {"event_type": "MARKET_SCAN", "symbol": "XAUUSD"},
        {"event_type": "MARKET_SCAN", "symbol": "XAUUSD"},
    )
    # No price/ATR anywhere → no fabricated ladder.
    assert result.levels is None


def test_neutral_cycle_without_direction_gets_no_ladder() -> None:
    analysis = {
        "agent": "supervisor",
        "overall_signal": "NEUTRAL",
        "summary": "no consensus",
    }
    result = _pipeline(FakeSupervisor(analysis), FakeRiskGate(_approved())).run(
        {"event_type": "MARKET_SCAN", "symbol": "XAUUSD"}, _context()
    )
    assert result.levels is None


# ---------------------------------------------------------------------------
# Notifier rendering
# ---------------------------------------------------------------------------
_LADDER = {
    "direction": "BUY",
    "entry": 2000.0,
    "sl": 1997.0,
    "tp1": 2003.0,
    "tp2": 2006.0,
    "tpmax": 2009.0,
    "risk_distance": 3.0,
    "source": "analysis",
}


def _summary(**overrides) -> dict:
    base = {
        "event_type": "MOMENTUM_BULLISH",
        "decision": "WAIT",
        "status": "WAIT",
        "confidence": 1.0,
        "summary": "market_lead: BULLISH (conf=1.00)",
        "risk_reason": "no actionable proposal",
        "executed": False,
        "trace_id": "trace-1",
        "symbol": "XAUUSD",
        "queued_at": 1_700_000_000.0,
        "levels": _LADDER,
    }
    base.update(overrides)
    return base


def test_report_renders_level_ladder() -> None:
    text = format_pipeline_report(_summary())
    assert "📐 RENCANA BUY (indikatif)" in text  # indicative ladder is labelled
    # One level per row, top-to-bottom: Entry → TP1 → TP2 → TPmax → SL.
    assert (
        "Entry : 2000.00\n"
        "TP1   : 2003.00\n"
        "TP2   : 2006.00\n"
        "TPmax : 2009.00\n"
        "SL    : 1997.00"
    ) in text


def test_report_order_ladder_not_labelled_indicative() -> None:
    text = format_pipeline_report(_summary(levels=dict(_LADDER, source="order")))
    assert "📐 RENCANA BUY" in text
    assert "(indikatif)" not in text


def test_report_without_levels_has_no_level_line() -> None:
    text = format_pipeline_report(_summary(levels=None))
    assert "📐" not in text


def test_digest_renders_one_level_line_and_prefers_order_ladder() -> None:
    items = [
        _summary(),
        _summary(levels=dict(_LADDER, source="order", entry=2001.0, sl=1998.0)),
    ]
    text = format_pipeline_digest(items)
    assert text.count("📐 RENCANA") == 1
    assert "Entry : 2001.00" in text  # the real order ladder wins


def test_digest_without_levels_has_no_level_line() -> None:
    text = format_pipeline_digest([_summary(levels=None)])
    assert "📐" not in text


def test_summarize_passes_levels_through() -> None:
    assert summarize_pipeline_result(_summary())["levels"] == _LADDER
    assert summarize_pipeline_result({})["levels"] is None
    assert summarize_pipeline_result({"levels": "nope"})["levels"] is None
