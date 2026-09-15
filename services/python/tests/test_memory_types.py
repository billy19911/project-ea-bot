# -*- coding: utf-8 -*-
"""Tests for PRD_V2 §17 — Memory types.

Covers working memory (TTL), semantic memory (tags + recency), strategy
memory (per-strategy isolation/stats), and research memory (findings +
outcome lookup).
"""

from __future__ import annotations

import time

from memory.research_memory import ResearchMemory, ResearchNote
from memory.semantic_memory import SemanticMemory
from memory.strategy_memory import StrategyMemory
from memory.working_memory import WorkingMemory


class TestWorkingMemory:
    def test_store_and_retrieve(self):
        wm = WorkingMemory()
        wm.put("k1", {"value": 1})
        assert wm.get("k1") == {"value": 1}

    def test_get_missing_returns_none(self):
        wm = WorkingMemory()
        assert wm.get("nope") is None

    def test_ttl_expiry(self):
        wm = WorkingMemory(default_ttl=0.05)
        wm.put("k1", "v")
        assert wm.get("k1") == "v"
        time.sleep(0.08)
        assert wm.get("k1") is None

    def test_per_item_ttl(self):
        wm = WorkingMemory(default_ttl=10.0)
        wm.put("short", "v", ttl=0.05)
        wm.put("long", "v", ttl=10.0)
        time.sleep(0.08)
        assert wm.get("short") is None
        assert wm.get("long") == "v"

    def test_bounded_size(self):
        wm = WorkingMemory(max_size=3)
        for i in range(5):
            wm.put(f"k{i}", i)
        assert len(wm) <= 3
        # Most recent retained.
        assert wm.get("k4") == 4

    def test_delete_and_clear(self):
        wm = WorkingMemory()
        wm.put("k1", 1)
        assert wm.delete("k1") is True
        assert wm.get("k1") is None
        wm.put("k2", 2)
        wm.clear()
        assert len(wm) == 0


class TestSemanticMemory:
    def test_store_and_retrieve_by_key(self):
        sm = SemanticMemory()
        sm.add("rsi_divergence", "RSI divergence precedes reversals", tags=["rsi", "reversal"])
        item = sm.get("rsi_divergence")
        assert item is not None
        assert "divergence" in item.content

    def test_reject_empty(self):
        sm = SemanticMemory()
        try:
            sm.add("", "content")
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("empty key should be rejected")

    def test_retrieve_by_tag(self):
        sm = SemanticMemory()
        sm.add("f1", "fact one", tags=["eurusd", "trend"])
        sm.add("f2", "fact two", tags=["gbpusd", "range"])
        hits = sm.retrieve(tags=["eurusd"])
        assert len(hits) == 1
        assert hits[0].key == "f1"

    def test_recency_ordering(self):
        sm = SemanticMemory()
        sm.add("old", "older fact", tags=["t"])
        time.sleep(0.01)
        sm.add("new", "newer fact", tags=["t"])
        hits = sm.retrieve(tags=["t"])
        # Most recent first.
        assert hits[0].key == "new"

    def test_bounded_size(self):
        sm = SemanticMemory(max_size=3)
        for i in range(5):
            sm.add(f"k{i}", f"content {i}")
        assert len(sm) <= 3


class TestStrategyMemory:
    def test_record_and_retrieve(self):
        sm = StrategyMemory()
        sm.record("momentum", {"notes": "strong in trends"})
        assert sm.get("momentum")["notes"] == "strong in trends"

    def test_per_strategy_isolation(self):
        sm = StrategyMemory()
        sm.record("momentum", {"notes": "a"})
        sm.record("mean_reversion", {"notes": "b"})
        assert sm.get("momentum")["notes"] == "a"
        assert sm.get("mean_reversion")["notes"] == "b"

    def test_stats_accumulate(self):
        sm = StrategyMemory()
        sm.record_outcome("momentum", pnl=10.0, win=True)
        sm.record_outcome("momentum", pnl=-5.0, win=False)
        stats = sm.stats("momentum")
        assert stats["trades"] == 2
        assert stats["wins"] == 1
        assert stats["total_pnl"] == 5.0

    def test_isolation_of_stats(self):
        sm = StrategyMemory()
        sm.record_outcome("a", pnl=1.0, win=True)
        sm.record_outcome("b", pnl=99.0, win=True)
        assert sm.stats("a")["trades"] == 1
        assert sm.stats("b")["total_pnl"] == 99.0

    def test_bounded_size(self):
        sm = StrategyMemory(max_size=2)
        for i in range(5):
            sm.record(f"s{i}", {"n": i})
        assert len(sm) <= 2


class TestResearchMemory:
    def test_add_and_lookup_by_outcome(self):
        rm = ResearchMemory()
        rm.add(
            ResearchNote(id="r1", topic="breakouts", finding="fails in low volume"),
            outcome="invalidated",
        )
        rm.add(
            ResearchNote(id="r2", topic="ranges", finding="reverts to mean"),
            outcome="confirmed",
        )
        confirmed = rm.by_outcome("confirmed")
        assert len(confirmed) == 1
        assert confirmed[0].id == "r2"

    def test_lookup_by_topic(self):
        rm = ResearchMemory()
        rm.add(ResearchNote(id="r1", topic="breakouts", finding="x"))
        rm.add(ResearchNote(id="r2", topic="volatility", finding="y"))
        assert len(rm.by_topic("breakouts")) == 1

    def test_get(self):
        rm = ResearchMemory()
        rm.add(ResearchNote(id="r1", topic="t", finding="f"))
        assert rm.get("r1").finding == "f"
        assert rm.get("missing") is None

    def test_bounded_size(self):
        rm = ResearchMemory(max_size=2)
        for i in range(5):
            rm.add(ResearchNote(id=f"r{i}", topic="t", finding="f"))
        assert len(rm) <= 2
