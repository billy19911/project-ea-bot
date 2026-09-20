# -*- coding: utf-8 -*-
"""Tests for Learning Engine 2.0 (Phase 43)."""

from src.learning.engine_v2 import EvidenceLevel, LearningEngineV2, Lesson, LessonCategory


def _lesson(outcome: str = "WIN", symbol: str = "XAUUSD", category: str = "ENTRY_TIMING") -> Lesson:
    return Lesson(
        lesson_id="L1",
        trade_id="T1",
        symbol=symbol,
        strategy_version="v12",
        category=category,
        outcome=outcome,
        context={"hour": 14},
        lesson="entered too early",
        confidence="LOW",
        sample_size=1,
    )


def test_single_trade_is_only_observation() -> None:
    engine = LearningEngineV2()
    stored = engine.record_lesson(_lesson())
    assert stored.evidence_level == EvidenceLevel.OBSERVATION.value
    patterns = engine.aggregate_patterns()
    # A single trade can never become more than an OBSERVATION.
    assert patterns[0].evidence_level == EvidenceLevel.OBSERVATION.value


def test_pattern_promotion_thresholds() -> None:
    engine = LearningEngineV2(min_pattern_sample=3, min_evidence_sample=5, min_validated_sample=10)
    for _ in range(3):
        engine.record_lesson(_lesson())
    agg = engine.aggregate_patterns()[0]
    assert agg.evidence_level == EvidenceLevel.HYPOTHESIS.value

    for _ in range(4):  # total 7 -> EVIDENCE
        engine.record_lesson(_lesson())
    agg = engine.aggregate_patterns()[0]
    assert agg.evidence_level == EvidenceLevel.EVIDENCE.value

    for _ in range(5):  # total 12 -> VALIDATED_FINDING
        engine.record_lesson(_lesson())
    agg = engine.aggregate_patterns()[0]
    assert agg.evidence_level == EvidenceLevel.VALIDATED_FINDING.value


def test_promotion_guardrail_rejects_weak_evidence() -> None:
    engine = LearningEngineV2(min_pattern_sample=3, min_evidence_sample=5, min_validated_sample=10)
    for _ in range(3):
        engine.record_lesson(_lesson())
    agg = engine.aggregate_patterns()[0]
    allowed, reason = engine.can_promote_to_candidate(agg)
    assert allowed is False
    assert "below" in reason


def test_promotion_guardrail_allows_validated() -> None:
    engine = LearningEngineV2(min_pattern_sample=3, min_evidence_sample=5, min_validated_sample=10)
    for _ in range(12):
        engine.record_lesson(_lesson())
    agg = engine.aggregate_patterns()[0]
    allowed, _ = engine.can_promote_to_candidate(agg)
    assert allowed is True


def test_pattern_aggregation_by_category_and_symbol() -> None:
    engine = LearningEngineV2(min_pattern_sample=1)
    engine.record_lesson(_lesson(symbol="XAUUSD", category="ENTRY_TIMING"))
    engine.record_lesson(_lesson(symbol="EURUSD", category="ENTRY_TIMING"))
    patterns = engine.aggregate_patterns()
    assert len(patterns) == 2
    keys = {p.key for p in patterns}
    assert keys == {"ENTRY_TIMING:XAUUSD", "ENTRY_TIMING:EURUSD"}


def test_win_rate() -> None:
    engine = LearningEngineV2(min_pattern_sample=1)
    engine.record_lesson(_lesson(outcome="WIN"))
    engine.record_lesson(_lesson(outcome="LOSS"))
    engine.record_lesson(_lesson(outcome="WIN"))
    agg = engine.aggregate_patterns()[0]
    assert agg.wins == 2
    assert agg.losses == 1
    assert round(agg.win_rate, 2) == round(2 / 3 * 100, 2)


def test_ingestion_forces_observation_level() -> None:
    engine = LearningEngineV2()
    forged = Lesson(
        lesson_id="L2",
        trade_id="T2",
        symbol="BTCUSD",
        strategy_version="v1",
        category=LessonCategory.OTHER.value,
        outcome="WIN",
        evidence_level=EvidenceLevel.VALIDATED_FINDING.value,
    )
    stored = engine.record_lesson(forged)
    assert stored.evidence_level == EvidenceLevel.OBSERVATION.value
