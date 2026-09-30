# -*- coding: utf-8 -*-
"""Phase 3 — failure-mode tests (§28 TEST 4/9/10/11/12): crash, correlation,
malformed output, RiskGate authority, volume authority."""

from __future__ import annotations

import pytest

from src.agents.analysts.momentum_analyst import MomentumAnalystAgent
from src.agents.analysts.news_agent import NewsSentimentAgent
from src.agents.analysts.structure_analyst import StructureAnalystAgent
from src.agents.analysts.volatility_analyst import VolatilityAnalystAgent
from src.agents.canonical import EvidenceItem, EvidenceKind
from src.agents.orchestrator import CommitteeOrchestrator
from src.agents.roles import (
    ChallengerRole,
    EntryRole,
    LiquidityRole,
    RegimeRole,
    role_from_specialist,
)
from src.risk.base import RiskThreshold
from src.risk.engine import RiskEngine
from src.risk.gate import RiskGate
from src.risk.money_management import MoneyManager


def _roles() -> dict:
    return {
        "regime": RegimeRole(),
        "structure": role_from_specialist("structure", StructureAnalystAgent()),
        "liquidity": LiquidityRole(),
        "momentum": role_from_specialist("momentum", MomentumAnalystAgent()),
        "volatility": role_from_specialist("volatility", VolatilityAnalystAgent()),
        "news": role_from_specialist("news", NewsSentimentAgent()),
        "entry": EntryRole(),
    }


# ── TEST 4: specialist failure → SPECIALIST_ERROR, WAIT when required ────


def test_crash_never_fabricates_signal():
    class _Boom:
        def analyze(self, ctx):
            raise RuntimeError("provider down")

    out = role_from_specialist("structure", _Boom()).analyze({"x": 1})
    assert out.signal == "UNKNOWN"
    assert out.error is True
    assert out.data_quality == "UNKNOWN"


def test_orchestrator_survives_role_crash():
    class _BoomRegime(RegimeRole):
        def analyze_impl(self, ctx):
            raise RuntimeError("regime provider down")

    roles = _roles()
    roles["regime"] = _BoomRegime()
    orch = CommitteeOrchestrator(roles, challenger=ChallengerRole())
    res = orch.run(
        {"symbol": "XAUUSD", "event_type": "TREND_BULLISH", "trace_id": "t"},
        event_type="TREND_BULLISH",
    )
    assert res.ran_committee is True
    assert "regime" in res.role_outputs
    assert res.role_outputs["regime"].error is True


# ── TEST 9: correlated evidence shares provenance ─────────────────────────


def test_correlated_evidence_shows_shared_source():
    a = EvidenceItem(
        kind=EvidenceKind.FACT,
        content="RSI>70",
        source="momentum",
        quality=0.8,
        source_id="rsi_14",
        source_type="indicator",
        derived_from="close_prices",
    )
    b = EvidenceItem(
        kind=EvidenceKind.FACT,
        content="RSI>70",
        source="technical",
        quality=0.8,
        source_id="rsi_14",
        source_type="indicator",
        derived_from="close_prices",
    )
    assert a.source_id == b.source_id == "rsi_14"
    assert a.derived_from == b.derived_from == "close_prices"
    d = a.to_dict()
    assert d["provenance"]["source_id"] == "rsi_14"


# ── TEST 10: malformed output → safe handling, no trade ───────────────────


@pytest.mark.parametrize("bad", [None, "BUY", 42, ["x"], object()])
def test_malformed_agent_output_never_trades(bad):
    from src.agents.committee import AgentOutputAdapter

    bundle = AgentOutputAdapter().to_evidence("weird", bad, domain="structure")
    assert bundle is not None
    assert bundle.is_empty() is True


# ── TEST 11: RiskGate still authoritative over ENTRY_READY ─────────────────


def _gate() -> RiskGate:
    eng = RiskEngine()
    eng.set_threshold(RiskThreshold.MAX_DRAWDOWN, 0.2)
    eng.set_threshold(RiskThreshold.DAILY_LOSS_LIMIT, 0.1)
    eng.set_threshold(RiskThreshold.MAX_POSITIONS, 5)
    eng.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.3)
    return RiskGate(eng, MoneyManager(), max_spread_pips=5.0)


def _acct() -> dict:
    return {
        "equity": 10_000.0,
        "balance": 10_000.0,
        "peak_equity": 10_000.0,
        "daily_pnl": 0.0,
        "used_margin": 0.0,
        "margin_call_level": 500.0,
    }


def test_committee_entry_ready_still_blocked_by_risk_gate():
    gate = _gate()
    # Committee says ENTRY_READY with a sane setup — but the proposal is an
    # absurd size the gate must reject.
    d = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 115.0,
            "size": 500.0,
        },
        _acct(),
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0},
    )
    assert d.approved is False
    assert d.checks_passed.get("max_position_size") is False


# ── TEST 12: committee-requested lot is advisory only ─────────────────────


def test_ai_suggested_volume_never_authoritative():
    from src.orchestration.pipeline import TradingPipeline

    pipe = TradingPipeline(supervisor=None, risk_gate=None, execution_engine=None)
    pipe.max_lot_per_trade = 0.05
    # A malicious/AI-suggested 25.0 lots must be capped deterministically.
    proposal = {"symbol": "EURUSD", "size": 25.0}
    pipe._cap_lot(proposal)
    assert proposal["size"] == 0.05


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
