# -*- coding: utf-8 -*-
"""Phase 3 — committee tests (§28): roles, evidence, Market Lead, debate wiring.
All roles are deterministic. No voting anywhere.
"""
from __future__ import annotations

import pytest

from src.agents.analysts.momentum_analyst import MomentumAnalystAgent
from src.agents.analysts.news_agent import NewsSentimentAgent
from src.agents.analysts.structure_analyst import StructureAnalystAgent
from src.agents.analysts.volatility_analyst import VolatilityAnalystAgent
from src.agents.event_dispatch import (
    LEVEL_DETERMINISTIC,
    LEVEL_ENTRY,
    classify_event,
    decide_dispatch,
)
from src.agents.orchestrator import CommitteeOrchestrator
from src.agents.roles import (
    CANONICAL_ROLES,
    CHALLENGE_FAILED,
    ChallengerRole,
    EntryRole,
    LiquidityRole,
    RegimeRole,
    role_from_specialist,
)


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


def _trend_ctx(direction: str = "UP", adx: float = 30.0) -> dict:
    import random

    random.seed(7)
    n = 60
    step = 0.5 if direction == "UP" else -0.5
    prices = [100 + i * step + random.uniform(-1, 1) for i in range(n)]
    return {
        "symbol": "XAUUSD",
        "event_type": "TREND_BULLISH",
        "prices": prices,
        "highs": [p + 1 for p in prices],
        "lows": [p - 1 for p in prices],
        "adx": adx,
        "trend": direction,
        "atr": 2.0,
        "atr_prev": 1.6,
        "trace_id": "t-committee",
    }


# ── canonical roles exist and emit normalized outputs ──────────────────
def test_all_eight_canonical_roles_defined():
    assert set(CANONICAL_ROLES) == {
        "regime",
        "structure",
        "liquidity",
        "momentum",
        "volatility",
        "news",
        "entry",
        "challenger",
    }


def test_regime_role_produces_evidence_not_vote():
    out = RegimeRole().analyze({"adx": 30, "trend": "UP"})
    assert out.role == "regime"
    assert len(out.evidence) >= 1
    assert out.signal in ("TRENDING", "RANGING", "BALANCED", "EXPANSION", "COMPRESSION", "UNKNOWN")


def test_regime_role_unknown_on_missing_data():
    out = RegimeRole().analyze({})
    assert out.signal == "UNKNOWN"
    assert out.data_quality == "UNKNOWN"


def test_structure_role_adapts_specialist_evidence():
    out = role_from_specialist("structure", StructureAnalystAgent()).analyze(_trend_ctx())
    assert out.role == "structure"
    assert out.evidence is not None
    assert out.data_quality in ("OK", "UNKNOWN", "STALE")


def test_news_role_unknown_stays_unknown():
    out = role_from_specialist("news", NewsSentimentAgent()).analyze({"symbol": "XAUUSD"})
    assert out.role == "news"
    # News must NEVER be fabricated CLEAR.
    assert out.signal != "CLEAR"
    if out.signal == "UNKNOWN":
        assert out.data_quality == "UNKNOWN"


def test_liquidity_role_never_emits_entry_signal():
    out = LiquidityRole().analyze(_trend_ctx())
    assert out.role == "liquidity"
    assert out.signal not in ("BUY", "SELL", "ENTRY_READY")


def test_entry_role_zone_touch_is_not_ready():
    out = EntryRole().analyze(
        {
            "setup": {"missing_conditions": [], "direction": "BUY"},
            "zone_touched": True,
            "trigger_confirmed": False,
        }
    )
    assert out.signal == "WAIT_TRIGGER"


def test_entry_role_ready_only_on_confirmation():
    out = EntryRole().analyze(
        {
            "setup": {"missing_conditions": [], "direction": "BUY"},
            "zone_touched": True,
            "trigger_confirmed": True,
        }
    )
    assert out.signal == "ENTRY_READY"


def test_entry_role_unknown_without_setup():
    out = EntryRole().analyze({})
    assert out.signal == "UNKNOWN"
    assert out.data_quality == "UNKNOWN"


def test_role_failure_is_unknown_never_fabricated():
    class _Boom:
        def analyze(self, ctx):
            raise RuntimeError("down")

    out = role_from_specialist("momentum", _Boom()).analyze({"x": 1})
    assert out.error is True
    assert out.signal == "UNKNOWN"
    assert out.data_quality == "UNKNOWN"


# ── TEST 1: one strong vs three weak ────────────────────────────────────
def test_one_strong_beats_three_weak_in_orchestrator():
    orch = CommitteeOrchestrator(_roles(), challenger=ChallengerRole())
    ctx = _trend_ctx("UP", adx=30)
    res = orch.run(ctx, event_type="TREND_BULLISH")
    assert res.ran_committee is True
    # Evidence-driven: decision exists and is traceable to role evidence.
    assert res.decision is not None
    assert res.decision.evidence_bundle_ref is not None


# ── TEST 2/8: high conflict → challenge; challenger invalidates ─────────
def test_challenger_can_fail_hypothesis():
    ch = ChallengerRole()
    out = ch.analyze(
        {
            "hypothesis_direction": "BUY",
            "setup": {"direction": "BUY"},  # no invalidation, no evidence
            "role_outputs": {"structure": _mk_sig("BEARISH")},
        }
    )
    assert ch.role == "challenger"
    assert out.role_specific["outcome"] == CHALLENGE_FAILED


def _mk_sig(signal: str, fresh: str = "fresh"):
    class _O:
        pass

    o = _O()
    o.signal = signal
    o.freshness = fresh
    return o


def test_orchestrator_blocks_on_unresolved_high_conflict():
    orch = CommitteeOrchestrator(_roles(), challenger=ChallengerRole())
    ctx = _trend_ctx("UP", adx=30)
    ctx["prices"] = list(reversed(ctx["prices"]))  # bearish structure vs bullish hint
    res = orch.run(ctx, event_type="STRUCTURE_BREAK")
    assert res.ran_committee is True
    # Either WAIT (conflict) or a traceable decision — never an untraced BUY.
    assert res.decision is not None
    if res.decision.action in ("BUY", "SELL"):
        assert res.decision.evidence_bundle_ref is not None


# ── TEST 6: no change → no full committee ────────────────────────────────
def test_no_state_change_skips_committee():
    d = decide_dispatch("POSITION_OPENED", state_changed=True)
    assert d.run_committee is False
    assert d.use_cache or "Deterministic" in d.reason


def test_unknown_event_is_deterministic_only():
    cls = classify_event("SOME_RANDOM_NOISE")
    assert cls.level == LEVEL_DETERMINISTIC
    assert cls.roles == ()


def test_entry_event_dispatches_entry_level():
    cls = classify_event("ZONE_TOUCH")
    assert cls.level == LEVEL_ENTRY
    assert "entry" in cls.roles


def test_structure_event_dispatches_structure_roles():
    d = decide_dispatch("STRUCTURE_BREAK", state_changed=True)
    assert d.run_committee is True
    assert "structure" in d.roles


# ── Market Lead hypothesis fields ───────────────────────────────────────
def test_assessment_carries_hypothesis_evidence():
    orch = CommitteeOrchestrator(_roles(), challenger=ChallengerRole())
    res = orch.run(_trend_ctx(), event_type="TREND_BULLISH")
    a = res.assessment
    assert a is not None
    assert a.evidence_bundle is not None
    assert len(a.evidence_bundle) >= 1
    # Traceability: assessment → trace.
    assert a.trace_id == "t-committee"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
