# -*- coding: utf-8 -*-
"""Tests for committee conflict handling (audit P2-4).

An unresolved committee conflict with only a weak winner must NOT be forced into
a trade — the supervisor suppresses the proposal so the pipeline yields
WAIT/NO_TRADE.
"""

from __future__ import annotations

from agents.supervisor import SupervisorAgent


def _outputs(*, unresolved: bool, signal: str, confidence: float) -> dict:
    lead = {
        "agent": "market_lead",
        "signal": signal,
        "confidence": confidence,
        "unresolved_conflict": unresolved,
        "reasons": ["stub"],
    }
    specialist = {"agent": "momentum", "signal": signal, "confidence": confidence}
    return {"market_lead": lead, "momentum": specialist}


def test_unresolved_conflict_weak_consensus_suppresses_proposal():
    sup = SupervisorAgent()
    sup._has_unresolved_conflict  # sanity: attribute exists
    results = _outputs(unresolved=True, signal="BULLISH", confidence=0.5)
    synthesis, proposal = sup._synthesise("BREAKOUT", {"symbol": "EURUSD"}, results)
    # A BUY consensus exists but the conflict + weak confidence suppresses it.
    assert proposal is None


def test_unresolved_conflict_strong_consensus_still_proposes():
    sup = SupervisorAgent()
    results = _outputs(unresolved=True, signal="BULLISH", confidence=0.9)
    synthesis, proposal = sup._synthesise("BREAKOUT", {"symbol": "EURUSD"}, results)
    # Strong agreement overrides the recorded conflict.
    assert proposal is not None
    assert proposal["direction"] == "BUY"


def test_no_conflict_weak_consensus_proposes():
    sup = SupervisorAgent()
    results = _outputs(unresolved=False, signal="BULLISH", confidence=0.5)
    synthesis, proposal = sup._synthesise("BREAKOUT", {"symbol": "EURUSD"}, results)
    # No conflict → the (weak) BUY still flows to the risk gate.
    assert proposal is not None


def test_helpers():
    sup = SupervisorAgent()
    assert sup._has_unresolved_conflict({"a": {"unresolved_conflict": True}}) is True
    assert sup._has_unresolved_conflict({"a": {"unresolved_conflict": False}}) is False
    assert sup._has_unresolved_conflict({}) is False
    assert sup._is_weak_consensus({"confidence": 0.4}) is True
    assert sup._is_weak_consensus({"confidence": 0.8}) is False
    assert sup._is_weak_consensus({}) is True  # missing → treat as weak (safe)


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
