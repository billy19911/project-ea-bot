# -*- coding: utf-8 -*-
"""Agent Synthesis & Supervisor Planning — Phase 12.

Provides:
- TradeProposal: structured trade recommendation with direction, confidence, SL/TP
- SynthesisResult: aggregated multi-agent output with agreement score & conflicts
- AgentSynthesizer: task planning, signal aggregation, conflict detection, trade proposals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TradeDirection(str, Enum):
    """Trade direction enumeration."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeProposal:
    """Synthesised trade proposal from multi-agent consensus.

    Attributes:
        symbol: Trading symbol (e.g., "EURUSD").
        direction: Trade direction (BUY, SELL, HOLD).
        confidence: Consensus confidence (0.0–1.0).
        reasoning: Human-readable synthesis reasoning.
        agent_signals: Mapping of agent_name -> {signal, confidence, reasoning}.
        target_sl: Suggested stop-loss price (optional).
        target_tp: Suggested take-profit price (optional).
        requires_escalation: True if conflict or low confidence flags human review.
        created_at: ISO timestamp of proposal creation.
    """

    symbol: str
    direction: TradeDirection
    confidence: float
    reasoning: str
    agent_signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    target_sl: float | None = None
    target_tp: float | None = None
    requires_escalation: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict."""
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "agent_signals": self.agent_signals,
            "target_sl": self.target_sl,
            "target_tp": self.target_tp,
            "requires_escalation": self.requires_escalation,
            "created_at": self.created_at,
        }


@dataclass
class SynthesisResult:
    """Result of the synthesis pipeline.

    Attributes:
        proposal: The generated TradeProposal (or None if synthesis failed).
        agreement_score: Fraction of agents whose signal aligns with proposal (0.0–1.0).
        conflicts_found: List of human-readable conflict descriptions.
        agent_count: Number of agents that contributed.
        skipped_agents: Agents that were skipped (token budget, filtering, etc.).
    """

    proposal: TradeProposal | None
    agreement_score: float
    conflicts_found: list[str] = field(default_factory=list)
    agent_count: int = 0
    skipped_agents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict."""
        return {
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "agreement_score": self.agreement_score,
            "conflicts_found": self.conflicts_found,
            "agent_count": self.agent_count,
            "skipped_agents": self.skipped_agents,
        }


class AgentSynthesizer:
    """Supervisor planning & synthesis engine.

    Responsibilities:
    1. Task planning: given an Event/MarketState, plan which sub-agents to invoke.
    2. Result aggregation: combine outputs from multiple market agents
       (Structure, Momentum, Volatility, News).
    3. Conflict detection: detect opposing signals, calculate agreement score.
    4. Trade proposal generation: synthesise consensus into TradeProposal.
    5. Escalation: flag high-conflict or low-confidence proposals for review.
    """

    # Mapping of agent types to their canonical signal keys
    SIGNAL_KEY = "signal"
    CONFIDENCE_KEY = "confidence"
    REASONING_KEY = "reasoning"

    # Signal buckets for conflict detection
    BULLISH_SIGNALS = {"BULLISH", "STRONG_BULLISH", "BUY"}
    BEARISH_SIGNALS = {"BEARISH", "STRONG_BEARISH", "SELL"}
    NEUTRAL_SIGNALS = {"NEUTRAL", "HOLD", "UNKNOWN", "LOW", "NORMAL", "HIGH"}

    def __init__(
        self,
        min_confidence: float = 0.6,
        escalation_conflict_threshold: int = 2,
        escalation_confidence_threshold: float = 0.5,
    ) -> None:
        """Initialise the synthesizer.

        Args:
            min_confidence: Minimum consensus confidence to propose a trade.
            escalation_conflict_threshold: Number of conflicting agent pairs
                that triggers escalation.
            escalation_confidence_threshold: Below this consensus confidence,
                escalation is triggered.
        """
        self.min_confidence = min_confidence
        self.escalation_conflict_threshold = escalation_conflict_threshold
        self.escalation_confidence_threshold = escalation_confidence_threshold

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def plan_agents(
        self,
        event_type: str,
        market_state: dict[str, Any] | None = None,
        available_agents: list[str] | None = None,
    ) -> list[str]:
        """Plan which agents to invoke for a given event/market state.

        Args:
            event_type: The detected event type (e.g., "TREND_BULLISH").
            market_state: Current market state dict.
            available_agents: List of registered agent names (optional).

        Returns:
            Ordered list of agent names to invoke.
        """
        # Default agent set covering all analytical domains
        default_plan = [
            "structure_analyst",
            "momentum_analyst",
            "volatility_analyst",
            "news_sentiment",
        ]

        if available_agents:
            # Filter to only available agents, preserving priority order
            plan = [a for a in default_plan if a in available_agents]
            # Add any extra available agents not in default plan
            for a in available_agents:
                if a not in plan:
                    plan.append(a)
            return plan

        return default_plan

    def aggregate_signals(self, agent_outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Aggregate raw agent outputs into a unified signal map.

        Args:
            agent_outputs: Mapping of agent_name -> agent result dict.
                Each result dict must contain keys: "signal", "confidence",
                "reasoning" (or "reasons").

        Returns:
            Aggregated dict with:
            - signals: list of (agent_name, signal, confidence, reasoning)
            - bullish_count: number of bullish signals
            - bearish_count: number of bearish signals
            - neutral_count: number of neutral signals
            - avg_confidence: mean confidence across agents
            - weighted_bullish: confidence-weighted bullish score
            - weighted_bearish: confidence-weighted bearish score
        """
        signals: list[dict[str, Any]] = []
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        confidences: list[float] = []
        weighted_bullish = 0.0
        weighted_bearish = 0.0

        for agent_name, output in agent_outputs.items():
            signal = output.get(self.SIGNAL_KEY, "NEUTRAL")
            confidence = float(output.get(self.CONFIDENCE_KEY, 0.0))
            reasoning = output.get(self.REASONING_KEY, output.get("reasons", ""))

            if isinstance(reasoning, list):
                reasoning = "; ".join(str(r) for r in reasoning)

            signals.append(
                {
                    "agent": agent_name,
                    "signal": signal,
                    "confidence": confidence,
                    "reasoning": reasoning,
                }
            )

            confidences.append(confidence)

            if signal in self.BULLISH_SIGNALS:
                bullish_count += 1
                weighted_bullish += confidence
            elif signal in self.BEARISH_SIGNALS:
                bearish_count += 1
                weighted_bearish += confidence
            else:
                neutral_count += 1

        return {
            "signals": signals,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "neutral_count": neutral_count,
            "avg_confidence": (sum(confidences) / len(confidences) if confidences else 0.0),
            "weighted_bullish": weighted_bullish,
            "weighted_bearish": weighted_bearish,
            "total_agents": len(signals),
        }

    def detect_conflicts(self, agent_outputs: dict[str, dict[str, Any]]) -> list[str]:
        """Detect opposing signals among agents.

        Args:
            agent_outputs: Mapping of agent_name -> agent result dict.

        Returns:
            List of human-readable conflict descriptions.
        """
        conflicts: list[str] = []
        agents = list(agent_outputs.items())

        for i, (name_a, out_a) in enumerate(agents):
            sig_a = out_a.get(self.SIGNAL_KEY, "NEUTRAL")
            conf_a = out_a.get(self.CONFIDENCE_KEY, 0.0)

            for name_b, out_b in agents[i + 1 :]:
                sig_b = out_b.get(self.SIGNAL_KEY, "NEUTRAL")
                conf_b = out_b.get(self.CONFIDENCE_KEY, 0.0)

                # Check for direct opposition
                a_bullish = sig_a in self.BULLISH_SIGNALS
                a_bearish = sig_a in self.BEARISH_SIGNALS
                b_bullish = sig_b in self.BULLISH_SIGNALS
                b_bearish = sig_b in self.BEARISH_SIGNALS

                if (a_bullish and b_bearish) or (a_bearish and b_bullish):
                    conflicts.append(
                        f"Conflict: {name_a}={sig_a} (conf={conf_a:.2f}) vs "
                        f"{name_b}={sig_b} (conf={conf_b:.2f})"
                    )

        return conflicts

    def generate_proposal(
        self,
        event: dict[str, Any] | None,
        agent_outputs: dict[str, dict[str, Any]],
        min_confidence: float = 0.6,
        market_state: dict[str, Any] | None = None,
    ) -> SynthesisResult:
        """Synthesise agent outputs into a TradeProposal.

        Args:
            event: The triggering event dict (must contain 'symbol').
            agent_outputs: Mapping of agent_name -> agent result dict.
            market_state: Current market state (for SL/TP calculation).
            min_confidence: Override default minimum confidence threshold.

        Returns:
            SynthesisResult containing the proposal, agreement score, and conflicts.
        """
        symbol = (
            event.get("symbol", "UNKNOWN")
            if isinstance(event, dict)
            else getattr(event, "symbol", "UNKNOWN")
        )

        # Aggregate signals
        agg = self.aggregate_signals(agent_outputs)
        signals = agg["signals"]

        if not signals:
            return SynthesisResult(
                proposal=None,
                agreement_score=0.0,
                conflicts_found=["No agent outputs to synthesise"],
                agent_count=0,
            )

        # Detect conflicts
        conflicts = self.detect_conflicts(agent_outputs)

        # Calculate agreement score: fraction of agents aligned with majority
        bullish = agg["bullish_count"]
        bearish = agg["bearish_count"]
        neutral = agg["neutral_count"]
        total = agg["total_agents"]

        majority = max(bullish, bearish, neutral)
        agreement_score = majority / total if total > 0 else 0.0

        # Determine consensus direction
        if bullish > bearish and bullish >= neutral:
            direction = TradeDirection.BUY
            weighted_confidence = agg["weighted_bullish"] / bullish if bullish > 0 else 0.0
        elif bearish > bullish and bearish >= neutral:
            direction = TradeDirection.SELL
            weighted_confidence = agg["weighted_bearish"] / bearish if bearish > 0 else 0.0
        else:
            direction = TradeDirection.HOLD
            weighted_confidence = agg["avg_confidence"]

        # Build reasoning summary
        reasoning_parts = [
            f"Consensus: {direction.value} ({bullish}B/{bearish}S/{neutral}N)",
            f"Agreement: {agreement_score:.0%}",
            f"Avg confidence: {agg['avg_confidence']:.2f}",
        ]
        if conflicts:
            reasoning_parts.append(f"Conflicts: {len(conflicts)}")

        reasoning = " | ".join(reasoning_parts)

        # Calculate SL/TP from market state if available
        target_sl = None
        target_tp = None
        if market_state and isinstance(market_state, dict):
            close = market_state.get("close") or market_state.get("price")
            atr = market_state.get("atr")
            if close and atr and atr > 0:
                if direction == TradeDirection.BUY:
                    target_sl = round(close - atr * 2.0, 5)
                    target_tp = round(close + atr * 4.0, 5)  # 2:1 R:R
                elif direction == TradeDirection.SELL:
                    target_sl = round(close + atr * 2.0, 5)
                    target_tp = round(close - atr * 4.0, 5)

        # Determine escalation
        requires_escalation = self.check_escalation(
            SynthesisResult(
                proposal=TradeProposal(
                    symbol=symbol,
                    direction=direction,
                    confidence=weighted_confidence,
                    reasoning=reasoning,
                    agent_signals={s["agent"]: s for s in signals},
                    target_sl=target_sl,
                    target_tp=target_tp,
                ),
                agreement_score=agreement_score,
                conflicts_found=conflicts,
                agent_count=total,
            )
        )

        proposal = TradeProposal(
            symbol=symbol,
            direction=direction,
            confidence=round(weighted_confidence, 2),
            reasoning=reasoning,
            agent_signals={s["agent"]: s for s in signals},
            target_sl=target_sl,
            target_tp=target_tp,
            requires_escalation=requires_escalation,
        )

        return SynthesisResult(
            proposal=proposal,
            agreement_score=round(agreement_score, 3),
            conflicts_found=conflicts,
            agent_count=total,
        )

    def check_escalation(self, synthesis_result: SynthesisResult) -> bool:
        """Determine if a synthesis result requires human/manual review.

        Escalation triggers:
        - Consensus confidence below threshold
        - Conflict count above threshold
        - Proposal is HOLD with conflicting bullish/bearish signals

        Args:
            synthesis_result: Result from generate_proposal().

        Returns:
            True if escalation required.
        """
        if synthesis_result.proposal is None:
            return True

        prop = synthesis_result.proposal

        # Low confidence escalation
        if prop.confidence < self.escalation_confidence_threshold:
            return True

        # High conflict escalation
        if len(synthesis_result.conflicts_found) >= self.escalation_conflict_threshold:
            return True

        # HOLD with strong opposing signals
        if prop.direction == TradeDirection.HOLD:
            bullish_agents = sum(
                1 for s in prop.agent_signals.values() if s.get("signal") in self.BULLISH_SIGNALS
            )
            bearish_agents = sum(
                1 for s in prop.agent_signals.values() if s.get("signal") in self.BEARISH_SIGNALS
            )
            if bullish_agents >= 2 and bearish_agents >= 2:
                return True

        return False
