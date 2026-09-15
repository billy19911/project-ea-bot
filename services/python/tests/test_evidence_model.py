# -*- coding: utf-8 -*-
"""Tests for PRD_V2 §8 — Evidence Model.

Covers :class:`EvidenceItem` validation and :class:`EvidenceBundle`
aggregation, filtering, and staleness detection.
"""

from __future__ import annotations

import pytest

from agents.evidence import EvidenceBundle, EvidenceItem, EvidenceKind


class TestEvidenceItem:
    def test_create_fact(self):
        item = EvidenceItem(
            kind=EvidenceKind.FACT,
            content="RSI is 72",
            source="indicator_engine",
            timeframe="H1",
            quality=0.9,
        )
        assert item.kind == EvidenceKind.FACT
        assert item.content == "RSI is 72"
        assert item.source == "indicator_engine"
        assert item.timestamp
        assert item.freshness == "fresh"
        assert item.quality == 0.9

    def test_kind_from_string(self):
        item = EvidenceItem(
            kind="INTERPRETATION",
            content="Momentum fading",
            source="momentum_analyst",
        )
        assert item.kind == EvidenceKind.INTERPRETATION

    def test_metric_optional(self):
        item = EvidenceItem(
            kind=EvidenceKind.FACT,
            content="Spread normal",
            source="mt5",
            metric_name="spread",
            metric_value=1.2,
        )
        assert item.metric_name == "spread"
        assert item.metric_value == 1.2

    def test_empty_content_rejected(self):
        with pytest.raises(ValueError):
            EvidenceItem(kind=EvidenceKind.FACT, content="", source="x")

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValueError):
            EvidenceItem(kind="GOSSIP", content="x", source="x")

    def test_quality_bounds(self):
        with pytest.raises(ValueError):
            EvidenceItem(kind=EvidenceKind.FACT, content="x", source="x", quality=1.5)
        with pytest.raises(ValueError):
            EvidenceItem(kind=EvidenceKind.FACT, content="x", source="x", quality=-0.1)

    def test_quality_boundary_values(self):
        low = EvidenceItem(kind=EvidenceKind.FACT, content="x", source="x", quality=0.0)
        high = EvidenceItem(kind=EvidenceKind.FACT, content="x", source="x", quality=1.0)
        assert low.quality == 0.0
        assert high.quality == 1.0


class TestEvidenceBundle:
    def _make_items(self):
        return [
            EvidenceItem(
                kind=EvidenceKind.FACT,
                content="Price broke resistance",
                source="structure",
                quality=0.8,
            ),
            EvidenceItem(
                kind=EvidenceKind.FACT,
                content="Volume rising",
                source="volume",
                quality=0.6,
            ),
            EvidenceItem(
                kind=EvidenceKind.INTERPRETATION,
                content="Bullish continuation likely",
                source="momentum",
                quality=0.7,
            ),
            EvidenceItem(
                kind=EvidenceKind.RECOMMENDATION,
                content="Buy on pullback",
                source="strategy",
                quality=0.9,
            ),
        ]

    def test_add_and_list(self):
        bundle = EvidenceBundle()
        for item in self._make_items():
            bundle.add(item)
        assert len(bundle) == 4
        assert len(bundle.items()) == 4

    def test_filter_by_kind(self):
        bundle = EvidenceBundle()
        for item in self._make_items():
            bundle.add(item)
        assert len(bundle.filter(EvidenceKind.FACT)) == 2
        assert len(bundle.filter(EvidenceKind.INTERPRETATION)) == 1
        assert len(bundle.filter(EvidenceKind.RECOMMENDATION)) == 1

    def test_convenience_accessors(self):
        bundle = EvidenceBundle()
        for item in self._make_items():
            bundle.add(item)
        assert len(bundle.facts()) == 2
        assert len(bundle.interpretations()) == 1
        assert len(bundle.recommendations()) == 1

    def test_empty_bundle(self):
        bundle = EvidenceBundle()
        assert bundle.facts() == []
        assert bundle.interpretations() == []
        assert bundle.recommendations() == []
        assert bundle.is_empty()

    def test_staleness(self):
        bundle = EvidenceBundle()
        bundle.add(
            EvidenceItem(
                kind=EvidenceKind.FACT,
                content="old fact",
                source="x",
                age_seconds=120,
            )
        )
        bundle.add(
            EvidenceItem(
                kind=EvidenceKind.FACT,
                content="new fact",
                source="y",
                age_seconds=10,
            )
        )
        assert bundle.is_stale(max_age=60) is True
        assert bundle.is_stale(max_age=300) is False

    def test_max_age_empty_bundle_not_stale(self):
        assert EvidenceBundle().is_stale(max_age=60) is False

    def test_to_dict(self):
        bundle = EvidenceBundle()
        bundle.add(EvidenceItem(kind=EvidenceKind.FACT, content="a", source="s"))
        data = bundle.to_dict()
        assert data["count"] == 1
        assert data["items"][0]["kind"] == EvidenceKind.FACT.value
