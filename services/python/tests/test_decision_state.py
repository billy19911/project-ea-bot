# -*- coding: utf-8 -*-
"""Tests for PRD_V2 §9 Decision State + §10.2 dimensions.

Covers the three separated dimensions (market_bias, setup, action), the
non-raising ``validate()`` invariant checks, and serialization.
"""

from __future__ import annotations

from agents.decision_state import ActionType, DecisionState, MarketBias, SetupType


class TestConstruction:
    def test_defaults(self):
        state = DecisionState(decision_id="d1")
        assert state.decision_id == "d1"
        assert state.market_bias == MarketBias.NEUTRAL
        assert state.setup == SetupType.NONE
        assert state.action == ActionType.WAIT
        assert state.confidence == 0.0
        assert state.created_at
        assert state.strategy_version == ""

    def test_from_strings(self):
        state = DecisionState(
            decision_id="d1",
            market_bias="BULLISH",
            setup="BREAKOUT",
            action="BUY",
            confidence=0.8,
            rationale="clean breakout",
        )
        assert state.market_bias == MarketBias.BULLISH
        assert state.setup == SetupType.BREAKOUT
        assert state.action == ActionType.BUY
        assert state.confidence == 0.8
        assert state.rationale == "clean breakout"

    def test_evidence_bundle_ref(self):
        state = DecisionState(decision_id="d1", evidence_bundle_ref="bundle-1")
        assert state.evidence_bundle_ref == "bundle-1"


class TestValidate:
    def test_valid_buy(self):
        state = DecisionState(
            decision_id="d1",
            market_bias=MarketBias.BULLISH,
            setup=SetupType.BREAKOUT,
            action=ActionType.BUY,
        )
        assert state.validate() == []
        assert state.is_valid()

    def test_valid_sell(self):
        state = DecisionState(
            decision_id="d1",
            market_bias=MarketBias.BEARISH,
            setup=SetupType.PULLBACK,
            action=ActionType.SELL,
        )
        assert state.validate() == []

    def test_buy_requires_non_neutral_bias(self):
        state = DecisionState(
            decision_id="d1",
            market_bias=MarketBias.NEUTRAL,
            setup=SetupType.BREAKOUT,
            action=ActionType.BUY,
        )
        violations = state.validate()
        assert any("bias" in v.lower() for v in violations)
        assert not state.is_valid()

    def test_action_requires_setup(self):
        state = DecisionState(
            decision_id="d1",
            market_bias=MarketBias.BULLISH,
            setup=SetupType.NONE,
            action=ActionType.BUY,
            require_setup=True,
        )
        violations = state.validate()
        assert any("setup" in v.lower() for v in violations)

    def test_setup_check_configurable(self):
        state = DecisionState(
            decision_id="d1",
            market_bias=MarketBias.BULLISH,
            setup=SetupType.NONE,
            action=ActionType.BUY,
        )
        # Strictness off by default -> no setup violation.
        assert all("setup" not in v.lower() for v in state.validate())

    def test_wait_action_no_violations(self):
        state = DecisionState(decision_id="d1", action=ActionType.WAIT)
        assert state.validate() == []

    def test_constructor_does_not_raise(self):
        # Illegal combination must NOT raise on construction.
        state = DecisionState(
            decision_id="d1",
            market_bias=MarketBias.NEUTRAL,
            action=ActionType.BUY,
        )
        assert state.action == ActionType.BUY


class TestSerialization:
    def test_to_dict(self):
        state = DecisionState(
            decision_id="d1",
            market_bias=MarketBias.BEARISH,
            setup=SetupType.RANGE,
            action=ActionType.SELL,
            confidence=0.66,
            strategy_version="v2",
        )
        data = state.to_dict()
        assert data["decision_id"] == "d1"
        assert data["market_bias"] == "BEARISH"
        assert data["setup"] == "RANGE"
        assert data["action"] == "SELL"
        assert data["confidence"] == 0.66
        assert data["strategy_version"] == "v2"
