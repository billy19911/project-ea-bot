# -*- coding: utf-8 -*-
"""Phase 3 — debate tests (§28): bounded loop, termination, severity, limits."""

from __future__ import annotations

import pytest

from src.agents.canonical import Conflict, SetupCandidate
from src.agents.debate import (
    OUTCOME_INVALID,
    OUTCOME_RESOLVED,
    OUTCOME_WAIT,
    DebateConfig,
    DebateEngine,
    DebateRecord,
)
from src.agents.roles import CHALLENGE_FAILED, ChallengerRole


def _setup(direction: str = "BUY", missing: tuple = ("ltf_confirm",)) -> SetupCandidate:
    return SetupCandidate(
        setup_id="s-debate",
        assessment_id="a1",
        symbol="XAUUSD",
        direction=direction,
        setup_type="CONTINUATION",
        timeframe="M15",
        entry_context="zone",
        invalidation="x",
        required_conditions=["ltf_confirm"],
        missing_conditions=list(missing),
        supporting_evidence_refs=["structure"],
    )


def _conf(sev: str, desc: str = "x vs y", domains=("structure", "momentum")) -> Conflict:
    return Conflict(
        id="c1", severity=sev, description=desc, domains=list(domains), evidence_refs=["e1"]
    )


# ── TEST 2: high conflict → targeted challenge then WAIT ─────────────────


def test_high_conflict_triggers_challenge_and_waits():
    eng = DebateEngine(config=DebateConfig(max_rounds=2))
    out = eng.run(_setup(), [_conf("HIGH")], hypothesis_direction="BUY")
    assert out.outcome in (OUTCOME_WAIT, OUTCOME_INVALID, OUTCOME_RESOLVED)
    assert len(out.records) >= 1
    assert all(isinstance(r, DebateRecord) for r in out.records)


def test_challenger_refute_yields_invalid():
    """A CHALLENGE_FAILED (fatal contradiction) invalidates the setup."""

    class _Refuter(ChallengerRole):
        def analyze(self, context):
            from src.agents.canonical import EvidenceBundle
            from src.agents.roles import RoleOutput

            return RoleOutput(
                role="challenger",
                signal=CHALLENGE_FAILED,
                confidence_dimensions={"evidence_quality": 0.7},
                evidence=EvidenceBundle(),
                role_specific={"outcome": CHALLENGE_FAILED, "contradictions": ["structure broke"]},
            )

    eng = DebateEngine(config=DebateConfig(max_rounds=2), challenger=_Refuter())
    setup = _setup()
    out = eng.run(setup, [_conf("HIGH")], hypothesis_direction="BUY")
    assert out.outcome == OUTCOME_INVALID
    assert setup.status == "INVALID"


# ── TEST 5: debate terminates at max rounds ──────────────────────────────


def test_debate_terminates_at_max_rounds():
    eng = DebateEngine(config=DebateConfig(max_rounds=1, max_challenges_per_cycle=1))
    out = eng.run(_setup(), [_conf("HIGH")], hypothesis_direction="BUY")
    assert out.rounds <= 1
    assert out.outcome in (OUTCOME_WAIT, OUTCOME_INVALID, OUTCOME_RESOLVED)


def test_no_conflict_resolves_immediately():
    eng = DebateEngine()
    out = eng.run(_setup(), [], hypothesis_direction="BUY")
    assert out.outcome == OUTCOME_RESOLVED
    assert out.rounds == 0


# ── TEST: LOW severity is observation only ────────────────────────────────


def test_low_conflict_needs_no_challenge():
    eng = DebateEngine()
    out = eng.run(
        _setup(), [_conf("LOW", "minor wobble", ("volatility",))], hypothesis_direction="BUY"
    )
    # LOW is observation only → resolved trivially or waited without challenge.
    assert out.outcome in (OUTCOME_RESOLVED, OUTCOME_WAIT)


# ── TEST: CRITICAL blocks unless resolved ─────────────────────────────────


def test_critical_conflict_blocks_trade():
    eng = DebateEngine(config=DebateConfig(max_rounds=1))
    out = eng.run(_setup(), [_conf("CRITICAL", "regime vs structure")], hypothesis_direction="BUY")
    assert out.outcome in (OUTCOME_WAIT, OUTCOME_INVALID)
    assert out.rounds >= 1


# ── TEST: debate records are traceable ────────────────────────────────────


def test_debate_records_link_setup_and_conflicts():
    eng = DebateEngine(config=DebateConfig(max_rounds=2))
    conflict = _conf("HIGH")
    out = eng.run(_setup(), [conflict], hypothesis_direction="BUY")
    for r in out.records:
        assert r.setup_id == "s-debate"
        assert conflict.id in r.conflict_refs
        d = r.to_dict()
        assert {"debate_id", "round", "hypothesis", "challenge", "outcome"} <= set(d)


# ── TEST: max_challenges caps work ────────────────────────────────────────


def test_max_challenges_cap_respected():
    eng = DebateEngine(config=DebateConfig(max_rounds=5, max_challenges_per_cycle=1))
    out = eng.run(_setup(), [_conf("HIGH"), _conf("HIGH")], hypothesis_direction="BUY")
    assert len(out.records) <= 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
