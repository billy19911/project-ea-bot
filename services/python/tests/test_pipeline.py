# -*- coding: utf-8 -*-
"""Tests for the signal confidence filter in TradingPipeline.

Verifies that proposals with confidence below the MIN_SIGNAL_CONFIDENCE
threshold are not actionable, even when direction is BUY/SELL.

Constraints:
* NEUTRAL direction is never actionable, regardless of confidence.
* Fail-closed: missing confidence is treated as 0.0 (not actionable).
"""

from __future__ import annotations

from orchestration.pipeline import TradingPipeline


def _bare_pipeline() -> TradingPipeline:
    """A TradingPipeline with no injected deps, for testing pure helpers.

    ``_is_actionable`` is now an instance method (it consults the ACTIVE
    strategy's min_confidence when one is wired). Constructing via
    ``object.__new__`` avoids needing a supervisor/risk gate for a pure check.
    """
    pipeline = object.__new__(TradingPipeline)
    pipeline._strategy_config = {}
    pipeline._strategy_config_provider = None
    return pipeline


def test_low_confidence_not_actionable(monkeypatch):
    """A BUY proposal with confidence 0.3 (threshold 0.7) is NOT actionable."""
    monkeypatch.setattr("orchestration.pipeline.settings.min_signal_confidence", 0.7)
    proposal = {"direction": "BUY", "confidence": 0.3}
    assert _bare_pipeline()._is_actionable(proposal) is False


def test_high_confidence_actionable(monkeypatch):
    """A BUY proposal with confidence 0.9 (threshold 0.7) IS actionable."""
    monkeypatch.setattr("orchestration.pipeline.settings.min_signal_confidence", 0.7)
    proposal = {"direction": "BUY", "confidence": 0.9}
    assert _bare_pipeline()._is_actionable(proposal) is True


def test_neutral_direction_not_actionable(monkeypatch):
    """A NEUTRAL proposal is never actionable, regardless of confidence."""
    monkeypatch.setattr("orchestration.pipeline.settings.min_signal_confidence", 0.7)
    proposal = {"direction": "NEUTRAL", "confidence": 0.99}
    assert _bare_pipeline()._is_actionable(proposal) is False


def test_missing_confidence_not_actionable(monkeypatch):
    """Missing confidence is fail-closed: treated as 0.0 (not actionable)."""
    monkeypatch.setattr("orchestration.pipeline.settings.min_signal_confidence", 0.7)
    proposal = {"direction": "BUY"}
    assert _bare_pipeline()._is_actionable(proposal) is False


def test_sell_high_confidence_actionable(monkeypatch):
    """A SELL proposal with high confidence is actionable."""
    monkeypatch.setattr("orchestration.pipeline.settings.min_signal_confidence", 0.7)
    proposal = {"direction": "SELL", "confidence": 0.85}
    assert _bare_pipeline()._is_actionable(proposal) is True


def test_confidence_at_threshold_actionable(monkeypatch):
    """Confidence exactly at threshold is actionable (>= comparison)."""
    monkeypatch.setattr("orchestration.pipeline.settings.min_signal_confidence", 0.7)
    proposal = {"direction": "BUY", "confidence": 0.7}
    assert _bare_pipeline()._is_actionable(proposal) is True


def test_sell_low_confidence_not_actionable(monkeypatch):
    """A SELL proposal with low confidence is NOT actionable."""
    monkeypatch.setattr("orchestration.pipeline.settings.min_signal_confidence", 0.7)
    proposal = {"direction": "SELL", "confidence": 0.3}
    assert _bare_pipeline()._is_actionable(proposal) is False


def test_strategy_min_confidence_overrides_global(monkeypatch):
    """An ACTIVE strategy's min_confidence wins over the global default."""
    monkeypatch.setattr("orchestration.pipeline.settings.min_signal_confidence", 0.7)
    pipeline = _bare_pipeline()
    pipeline._strategy_config_provider = lambda: {"min_confidence": 0.4, "version": "v2"}
    # 0.5 is below the global 0.7 but above the strategy's 0.4 → actionable.
    assert pipeline._is_actionable({"direction": "BUY", "confidence": 0.5}) is True
    # And the strategy version is surfaced on the pipeline for traceability.
    assert pipeline.strategy_version == "v2"
