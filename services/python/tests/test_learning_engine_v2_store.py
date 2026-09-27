# -*- coding: utf-8 -*-
"""Tests for the Learning Engine 2.0 store + review bridge (PRD §43)."""

from __future__ import annotations

import os
from types import SimpleNamespace

from learning.engine_v2 import EvidenceLevel, LearningEngineV2, Lesson
from learning.engine_v2_store import JsonlEngineV2Store, get_engine_v2_store, set_engine_v2_store
from learning.feedback import record_review_lesson_v2


def _review_record(
    trade_id="t1",
    symbol="EURUSD",
    outcome="win",
    root_cause="entry timing",
    summary="good entry",
    regime="trend",
    direction="BUY",
):
    review = SimpleNamespace(outcome=outcome, symbol=symbol, summary=summary)
    root = SimpleNamespace(primary_cause=root_cause)
    return SimpleNamespace(
        trade_id=trade_id,
        review=review,
        root_cause=root,
        trade_result={
            "symbol": symbol,
            "outcome": outcome,
            "regime": regime,
            "direction": direction,
        },
    )


def test_store_persists_and_reloads(tmp_path):
    path = str(tmp_path / "v2.jsonl")
    store = JsonlEngineV2Store(path)
    store.add_lesson({"lesson_id": "a", "trade_id": "t1", "category": "OTHER"})
    assert len(store) == 1

    reloaded = JsonlEngineV2Store(path)
    assert len(reloaded) == 1
    assert reloaded.all_lessons()[0]["lesson_id"] == "a"


def test_store_skips_corrupt_lines(tmp_path):
    path = str(tmp_path / "v2.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write('{"lesson_id": "ok", "trade_id": "t"}\n')
    store = JsonlEngineV2Store(path)
    assert len(store) == 1
    assert store.all_lessons()[0]["lesson_id"] == "ok"


def test_bridge_records_observation_and_persists(tmp_path):
    store = JsonlEngineV2Store(str(tmp_path / "v2.jsonl"))
    engine = LearningEngineV2()
    recorded = record_review_lesson_v2(engine, store, _review_record())

    assert recorded is not None
    # A single trade is always an OBSERVATION — never promoted.
    assert recorded.evidence_level == EvidenceLevel.OBSERVATION.value
    assert recorded.category == "ENTRY_TIMING"
    assert len(store) == 1
    assert engine.lessons()[0].trade_id == "t1"


def test_bridge_is_fail_safe_on_bad_record(tmp_path):
    store = JsonlEngineV2Store(str(tmp_path / "v2.jsonl"))
    engine = LearningEngineV2()
    # A record with no attributes must not raise; returns None.
    result = record_review_lesson_v2(engine, store, object())
    # Either records a bare OBSERVATION or returns None — never raises.
    assert result is None or result.evidence_level == EvidenceLevel.OBSERVATION.value


def test_snapshot_rehydrates_patterns(tmp_path):
    store = JsonlEngineV2Store(str(tmp_path / "v2.jsonl"))
    engine = LearningEngineV2(min_pattern_sample=3)
    for i in range(3):
        record_review_lesson_v2(engine, store, _review_record(trade_id=f"t{i}"))

    # Rehydrate a fresh engine from the persisted store.
    rehydrated = LearningEngineV2(min_pattern_sample=3)
    for lesson_dict in store.all_lessons():
        rehydrated.record_lesson(Lesson(**lesson_dict))
    aggregates = rehydrated.aggregate_patterns()
    assert len(aggregates) == 1
    assert aggregates[0].sample_size == 3


def test_global_store_setter():
    previous = get_engine_v2_store()
    try:
        sentinel = JsonlEngineV2Store(os.path.join("logs", "test_v2.jsonl"))
        set_engine_v2_store(sentinel)
        assert get_engine_v2_store() is sentinel
    finally:
        set_engine_v2_store(previous)
