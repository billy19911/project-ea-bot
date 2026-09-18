# -*- coding: utf-8 -*-
"""Market Intelligence — EPIC 04 implementations.

Contains two layers:

* the legacy 5-analyst committee (``TechnicalAnalyst``, ``StructureAnalyst``,
  ``MomentumAnalyst``, ``VolatilityAnalyst``, ``NewsSentimentAnalyst``) kept
  for backward compatibility of the ``synthesize`` API, and
* :class:`MarketLead` — the department lead the Supervisor delegates market
  events to (``agent_type == "department_lead"``). It detects the current
  market regime, runs the REAL production analyst agents with adaptive
  regime weights, and returns a Supervisor-compatible assessment dict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agents.base import AgentPriority, BaseAgent
from learning.feedback import format_lessons_reason

logger = logging.getLogger(__name__)


@dataclass
class AnalystReport:
    """Result of specialist analysis."""

    analyst: str
    direction: str  # BULLISH, BEARISH, NEUTRAL
    confidence: float  # 0.0 to 1.0
    evidence: str
    reliability: float = 0.5


@dataclass
class CommitteeDecision:
    """Synthesized market decision.

    The decision is produced by deterministic, *evidence-weighted* synthesis
    (see :meth:`MarketLead.synthesize`), never by majority vote. The outcome
    is explainable via ``rationale`` and any ``dissent`` is recorded.
    """

    department: str
    direction: str
    confidence: float
    reports: list[AnalystReport] = field(default_factory=list)
    agreements: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    rationale: str = ""
    dissent: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "department": self.department,
            "direction": self.direction,
            "confidence": self.confidence,
            "reports": [
                {
                    "analyst": r.analyst,
                    "direction": r.direction,
                    "confidence": r.confidence,
                    "evidence": r.evidence,
                }
                for r in self.reports
            ],
            "agreements": self.agreements,
            "conflicts": self.conflicts,
            "rationale": self.rationale,
            "dissent": self.dissent,
        }


class TechnicalAnalyst(BaseAgent):
    """Technical analysis specialist.

    Note (PRD_V2 §25): this is intentionally *distinct* from
    :class:`agents.base.TechnicalAnalystAgent`. They are not trivially
    deduplicable — they differ in registered name (\"Technical Analyst\" vs
    \"technical_analyst\"), agent_type (\"analyst\" vs \"technical\") and return
    contract (:class:`AnalystReport` for the market-department committee vs a
    plain signal dict for the supervisor). Merging them would break the
    department-committee API, so both are kept.
    """

    def __init__(self):
        super().__init__(
            name="Technical Analyst",
            agent_type="analyst",
            description="Analyzes price action, trends, and indicators",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce technical analysis report."""
        trend = market_data.get("trend", "NEUTRAL")
        rsi = market_data.get("rsi", 50.0)

        if trend == "UP" and rsi > 60:
            direction = "BULLISH"
            confidence = 0.7
        elif trend == "DOWN" and rsi < 40:
            direction = "BEARISH"
            confidence = 0.7
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="TechnicalAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"Trend: {trend}, RSI: {rsi}",
        )

    def execute(self, task):
        return {"status": "ok"}


class StructureAnalyst(BaseAgent):
    """Structure analysis specialist."""

    def __init__(self):
        super().__init__(
            name="Structure Analyst",
            agent_type="analyst",
            description="Analyzes support, resistance, and structure",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce structure analysis report."""
        current = market_data.get("current_price", 1.0)
        support = market_data.get("support", 0.95)
        resistance = market_data.get("resistance", 1.05)

        if current > (support + resistance) / 2:
            direction = "BULLISH"
            confidence = 0.6
        elif current < (support + resistance) / 2:
            direction = "BEARISH"
            confidence = 0.6
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="StructureAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"Price: {current}, S: {support}, R: {resistance}",
        )

    def execute(self, task):
        return {"status": "ok"}


class MomentumAnalyst(BaseAgent):
    """Momentum analysis specialist."""

    def __init__(self):
        super().__init__(
            name="Momentum Analyst",
            agent_type="analyst",
            description="Analyzes momentum indicators and trend strength",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce momentum analysis report."""
        rsi = market_data.get("rsi", 50.0)
        macd = market_data.get("macd", 0.0)

        if rsi > 70 and macd > 0.01:
            direction = "BULLISH"
            confidence = 0.6
        elif rsi < 30 and macd < -0.01:
            direction = "BEARISH"
            confidence = 0.6
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="MomentumAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"RSI: {rsi}, MACD: {macd}",
        )

    def execute(self, task):
        return {"status": "ok"}


class VolatilityAnalyst(BaseAgent):
    """Volatility analysis specialist."""

    def __init__(self):
        super().__init__(
            name="Volatility Analyst",
            agent_type="analyst",
            description="Analyzes volatility and risk",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce volatility analysis report."""
        iv = market_data.get("implied_volatility", 0.15)
        hv = market_data.get("historical_volatility", 0.12)

        if iv > hv * 1.2:
            direction = "NEUTRAL"
            confidence = 0.5
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="VolatilityAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"IV: {iv}, HV: {hv}",
        )

    def execute(self, task):
        return {"status": "ok"}


class NewsSentimentAnalyst(BaseAgent):
    """News and sentiment analysis specialist."""

    def __init__(self):
        super().__init__(
            name="News/Sentiment Analyst",
            agent_type="analyst",
            description="Analyzes news and sentiment",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce news/sentiment analysis report."""
        sentiment = market_data.get("sentiment_score", 0.5)

        if sentiment > 0.6:
            direction = "BULLISH"
            confidence = 0.55
        elif sentiment < 0.4:
            direction = "BEARISH"
            confidence = 0.55
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="NewsSentimentAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"Sentiment: {sentiment}",
        )

    def execute(self, task):
        return {"status": "ok"}


class MarketDepartment:
    """Market Intelligence Department."""

    def __init__(self, lead: MarketLead):
        self.lead = lead
        self.specialists = [
            TechnicalAnalyst(),
            StructureAnalyst(),
            MomentumAnalyst(),
            VolatilityAnalyst(),
            NewsSentimentAnalyst(),
        ]


# ---------------------------------------------------------------------------
# Production specialist wiring (Phase 2 upgrade)
# ---------------------------------------------------------------------------

#: Names of the REAL production analyst agents this department runs.
PRODUCTION_SPECIALIST_NAMES = (
    "technical_analyst",
    "momentum_analyst",
    "structure_analyst",
    "volatility_analyst",
    "news_sentiment",
    "fundamental_analyst",
)


def _build_default_specialists() -> dict[str, BaseAgent]:
    """Instantiate the real production analyst agents for this department.

    Imports are function-local so this module stays importable while the agent
    packages are still initialising (avoids any import cycle). Fail-closed: if
    the agents cannot be built the lead degrades to NEUTRAL instead of
    crashing the supervisor cycle.
    """
    try:
        from agents.analysts import (
            FundamentalAnalystAgent,
            MomentumAnalystAgent,
            NewsSentimentAgent,
            StructureAnalystAgent,
            VolatilityAnalystAgent,
        )
        from agents.base import TechnicalAnalystAgent

        return {
            "technical_analyst": TechnicalAnalystAgent(),
            "momentum_analyst": MomentumAnalystAgent(),
            "structure_analyst": StructureAnalystAgent(),
            "volatility_analyst": VolatilityAnalystAgent(),
            "news_sentiment": NewsSentimentAgent(),
            "fundamental_analyst": FundamentalAnalystAgent(),
        }
    except Exception:  # pragma: no cover - defensive, fail closed
        logger.exception("Failed to build production specialists for MarketLead")
        return {}


class MarketLead(BaseAgent):
    """Market Intelligence Department Lead.

    Upgraded (Phase 2) responsibilities:

    1. **Market regime detection** — classifies the current context as
       ``TRENDING`` (ADX >= 25 with a directional trend), ``RANGING``
       (ADX < 20, no directional trend), ``NEWS_SHOCK`` (high-impact
       economic event / critical news / volatility spike) or ``BALANCED``.
    2. **Adaptive specialist weighting** — the evidence weight of each
       production analyst depends on the regime (trend-following weights in a
       trend, structure weight when ranging, news/fundamental weight during
       news shocks). Weights always sum to 1.0.
    3. **Delegation to the REAL specialists** — runs ``technical_analyst``,
       ``momentum_analyst``, ``structure_analyst``, ``volatility_analyst``,
       ``news_sentiment`` and ``fundamental_analyst`` (injectable for tests).
    4. **Supervisor compatibility** — registered as ``department_lead`` with a
       ``can_handle(event_type, context)`` signature and an ``analyze`` that
       returns a plain Supervisor-compatible dict.

    The legacy committee API (``create_department`` / ``synthesize``) is kept
    unchanged for backward compatibility.
    """

    #: Event-type prefixes routed to the market department.
    MARKET_EVENT_PREFIXES = (
        "TREND_",
        "MOMENTUM_",
        "RSI_",
        "STOCH_",
        "EMA_",
        "MACD_",
        "BREAKOUT",
        "BREAKDOWN",
        "REVERSAL",
        "STRUCTURE_",
        "PRICE_ACTION",
        "LEVEL_SCAN",
        "MARKET_",
        "VOLATILITY_",
        "NEWS_",
        "SOCIAL_",
        "EARNINGS_",
        "ECONOMIC_",
        "GAP_",
        "DOJI",
    )

    #: ADX threshold above which a directional market is treated as trending.
    ADX_TREND_THRESHOLD = 25.0
    #: ADX threshold below which a directionless market is treated as ranging.
    ADX_RANGE_THRESHOLD = 20.0

    #: Adaptive specialist weights per regime (each dict sums to 1.0).
    ADAPTIVE_WEIGHTS: dict[str, dict[str, float]] = {
        "TRENDING": {
            "technical_analyst": 0.30,
            "momentum_analyst": 0.25,
            "structure_analyst": 0.15,
            "volatility_analyst": 0.10,
            "news_sentiment": 0.10,
            "fundamental_analyst": 0.10,
        },
        "RANGING": {
            "structure_analyst": 0.35,
            "technical_analyst": 0.20,
            "volatility_analyst": 0.15,
            "momentum_analyst": 0.10,
            "news_sentiment": 0.10,
            "fundamental_analyst": 0.10,
        },
        "NEWS_SHOCK": {
            "news_sentiment": 0.30,
            "fundamental_analyst": 0.30,
            "volatility_analyst": 0.15,
            "technical_analyst": 0.10,
            "momentum_analyst": 0.10,
            "structure_analyst": 0.05,
        },
        "BALANCED": {
            "technical_analyst": 0.20,
            "momentum_analyst": 0.15,
            "structure_analyst": 0.20,
            "volatility_analyst": 0.15,
            "news_sentiment": 0.15,
            "fundamental_analyst": 0.15,
        },
    }

    def __init__(self, specialists: dict[str, BaseAgent] | None = None) -> None:
        super().__init__(
            name="market_lead",
            agent_type="department_lead",
            description=(
                "Market Intelligence Department Lead — adaptive regime-weighted "
                "committee over the production analyst agents"
            ),
            role="department_lead",
            permissions=["ANALYZE_MARKET"],
            priority=AgentPriority.HIGH,
        )
        self._specialists: dict[str, BaseAgent] = (
            dict(specialists) if specialists is not None else _build_default_specialists()
        )
        self.department = None

    # ------------------------------------------------------------------
    # Legacy committee API (unchanged, backward compatible)
    # ------------------------------------------------------------------

    def create_department(self) -> MarketDepartment:
        """Create and manage market department."""
        self.department = MarketDepartment(self)
        return self.department

    def synthesize(self, market_data: dict[str, Any]) -> CommitteeDecision:
        """Synthesize a deterministic, evidence-weighted consensus.

        Mirrors :meth:`DepartmentLead._resolve_consensus`: the winning
        direction is the one supported by the greatest *evidence weight*
        (``reliability × confidence``), never the greatest headcount. Ties
        break deterministically by direction priority, so the same inputs
        always yield the same output. The result is explainable via
        ``rationale`` and any dissenting analysts are recorded in ``dissent``.
        """
        if not self.department:
            self.create_department()

        reports = []
        for specialist in self.department.specialists:
            report = specialist.analyze(market_data)
            reports.append(report)

        direction, confidence, rationale, dissent = self._weighted_consensus(reports)

        # For backward compatibility, keep ``agreements``/``conflicts`` but
        # derive them from the new (non-vote) semantics.
        agreements = [f"{direction} supported by weighted evidence"]
        conflicts = list(dissent)

        return CommitteeDecision(
            department="market",
            direction=direction,
            confidence=confidence,
            reports=reports,
            agreements=agreements,
            conflicts=conflicts,
            rationale=rationale,
            dissent=dissent,
        )

    @staticmethod
    def _weighted_consensus(
        reports: list[AnalystReport],
    ) -> tuple[str, float, str, list[str]]:
        """Resolve direction by evidence weight; return rationale + dissent.

        Weight for a report is ``reliability × confidence``. Reports with a
        non-positive weight or a neutral direction do not vote. When no report
        carries directional weight the outcome is NEUTRAL. Ties are broken by a
        fixed direction priority (BULLISH, then BEARISH) so results are stable.
        """
        directional = [r for r in reports if r.direction in ("BULLISH", "BEARISH")]
        if not directional:
            return (
                "NEUTRAL",
                0.0,
                "No directional evidence; consensus is NEUTRAL",
                [],
            )

        weights: dict[str, float] = {}
        contributors: dict[str, list[AnalystReport]] = {}
        for report in directional:
            weight = max(0.0, float(report.reliability) * float(report.confidence))
            weights[report.direction] = weights.get(report.direction, 0.0) + weight
            contributors.setdefault(report.direction, []).append(report)

        # Deterministic tie-break: fixed direction order.
        priority = {"BULLISH": 0, "BEARISH": 1}
        winner = sorted(weights.items(), key=lambda kv: (-kv[1], priority.get(kv[0], 99)))[0][0]

        winning_weight = weights.get(winner, 0.0)
        total_weight = sum(weights.values())
        confidence = (winning_weight / total_weight) if total_weight > 0 else 0.0

        winners = contributors.get(winner, [])
        dissent = [r.analyst for r in directional if r.direction != winner]

        rationale = (
            f"{winner} selected by evidence weight "
            f"({winning_weight:.3f} of {total_weight:.3f} total; "
            f"{len(winners)} supporting analyst(s))"
        )

        return winner, confidence, rationale, dissent

    # ------------------------------------------------------------------
    # Phase 2: market regime detection
    # ------------------------------------------------------------------

    def detect_regime(self, context: dict[str, Any]) -> str:
        """Classify the market regime from the analysis context.

        Deterministic, fail-safe ordering: a news shock always wins (it
        invalidates trend/structure evidence), then trend/range classification
        uses ADX and the directional trend, and anything ambiguous degrades to
        ``BALANCED``.
        """
        if self._is_news_shock(context):
            return "NEWS_SHOCK"

        adx = self._extract_adx(context)
        trend = self._extract_trend(context)
        if not trend:
            trend = self._event_trend_hint(context)
        directional = trend in (
            "UP",
            "DOWN",
            "BULLISH",
            "BEARISH",
            "STRONG_BULLISH",
            "STRONG_BEARISH",
        )

        if adx is not None:
            if adx >= self.ADX_TREND_THRESHOLD and directional:
                return "TRENDING"
            if adx < self.ADX_RANGE_THRESHOLD and not directional:
                return "RANGING"
            # ADX present but evidence conflicts (e.g. high ADX with a neutral
            # trend): fall through to the balanced default.
        elif directional:
            return "TRENDING"

        return "BALANCED"

    @staticmethod
    def _is_news_shock(context: dict[str, Any]) -> bool:
        """True when a high-impact event / volatility spike dominates."""
        for event in context.get("economic_events") or []:
            impact = (
                event.get("impact", "") if isinstance(event, dict) else getattr(event, "impact", "")
            )
            if str(impact).upper() in ("HIGH", "CRITICAL"):
                return True

        for item in context.get("news_items") or []:
            impact = (
                item.get("impact", "") if isinstance(item, dict) else getattr(item, "impact", "")
            )
            if str(impact).upper() in ("HIGH", "CRITICAL"):
                return True

        volatility = context.get("volatility")
        if isinstance(volatility, dict):
            signal = str(volatility.get("signal", "")).upper()
        elif volatility is not None:
            signal = str(getattr(volatility, "signal", "")).upper()
        else:
            signal = ""
        return signal == "HIGH"

    @staticmethod
    def _extract_adx(context: dict[str, Any]) -> float | None:
        """Extract the ADX value from ``market_state`` or the context."""
        candidates: list[Any] = []
        market_state = context.get("market_state")
        if market_state is not None:
            candidates.append(getattr(market_state, "adx_value", None))
            if isinstance(market_state, dict):
                candidates.append(market_state.get("adx_value"))
                candidates.append(market_state.get("adx"))
        candidates.append(context.get("adx_value"))
        candidates.append(context.get("adx"))

        for value in candidates:
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _extract_trend(context: dict[str, Any]) -> str:
        """Extract the directional trend from ``market_state`` or context."""
        trend: Any = None
        market_state = context.get("market_state")
        if market_state is not None:
            trend = getattr(market_state, "trend_direction", None)
            if trend is None and isinstance(market_state, dict):
                trend = market_state.get("trend_direction")
                if trend is None:
                    trend = market_state.get("trend")
        if trend is None:
            trend = context.get("trend_direction")
        if trend is None:
            trend = context.get("trend")
        return str(trend).upper() if trend else ""

    @staticmethod
    def _event_trend_hint(context: dict[str, Any]) -> str:
        """Directional hint from the triggering event (used only as fallback)."""
        event_type = str(context.get("event_type", "")).upper()
        if "BULLISH" in event_type or event_type.endswith("_UP"):
            return "BULLISH"
        if "BEARISH" in event_type or event_type.endswith("_DOWN"):
            return "BEARISH"
        return ""

    # ------------------------------------------------------------------
    # Phase 2: adaptive weighting
    # ------------------------------------------------------------------

    def get_adaptive_weights(self, regime: str) -> dict[str, float]:
        """Return the specialist weight map for ``regime`` (sums to 1.0)."""
        return dict(self.ADAPTIVE_WEIGHTS.get(regime, self.ADAPTIVE_WEIGHTS["BALANCED"]))

    # ------------------------------------------------------------------
    # Phase 2: supervisor-facing analysis
    # ------------------------------------------------------------------

    def can_handle(self, event_type: str, context: dict[str, Any] | None = None) -> bool:
        """Handle market events (and the legacy ``market_analysis`` task)."""
        if event_type == "market_analysis":
            return True
        return any(event_type.startswith(prefix) for prefix in self.MARKET_EVENT_PREFIXES)

    @staticmethod
    def _direction_of(signal: Any) -> str:
        """Map an arbitrary specialist signal onto BULLISH/BEARISH/NEUTRAL."""
        upper = str(signal or "").upper()
        if "BULLISH" in upper or upper in ("BUY", "LONG"):
            return "BULLISH"
        if "BEARISH" in upper or upper in ("SELL", "SHORT"):
            return "BEARISH"
        return "NEUTRAL"

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run the regime-weighted committee and return a Supervisor dict.

        Each production specialist is executed defensively (a failing
        specialist never breaks the cycle). Directional votes are aggregated
        by ``regime_weight × specialist_confidence`` — never by headcount —
        and any dissenting specialist is recorded for explainability.
        """
        regime = self.detect_regime(context)
        weights = self.get_adaptive_weights(regime)

        specialist_results: dict[str, dict[str, Any]] = {}
        for name, specialist in self._specialists.items():
            try:
                raw = specialist.analyze(context)
            except Exception as exc:  # defensive boundary around specialists
                specialist_results[name] = {
                    "agent": name,
                    "status": "ERROR",
                    "signal": "NEUTRAL",
                    "confidence": 0.0,
                    "reasons": [f"Specialist failed: {exc}"],
                }
                continue
            if isinstance(raw, dict):
                specialist_results[name] = raw
            else:
                specialist_results[name] = {
                    "agent": name,
                    "status": "ERROR",
                    "signal": "NEUTRAL",
                    "confidence": 0.0,
                    "reasons": ["Specialist returned an unsupported result type"],
                }

        votes: dict[str, float] = {}
        contributors: dict[str, list[str]] = {}
        for name, result in specialist_results.items():
            if result.get("status") == "ERROR":
                continue
            direction = self._direction_of(result.get("signal"))
            if direction == "NEUTRAL":
                continue
            try:
                confidence = float(result.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = min(1.0, max(0.0, confidence))
            weight = max(0.0, weights.get(name, 0.0) * confidence)
            if weight <= 0:
                continue
            votes[direction] = votes.get(direction, 0.0) + weight
            contributors.setdefault(direction, []).append(name)

        if votes:
            priority = {"BULLISH": 0, "BEARISH": 1}
            winner = sorted(votes.items(), key=lambda kv: (-kv[1], priority.get(kv[0], 99)))[0][0]
            total_weight = sum(votes.values())
            signal = winner
            confidence = (votes[winner] / total_weight) if total_weight > 0 else 0.0
            dissent = [
                name
                for direction, names in contributors.items()
                if direction != winner
                for name in names
            ]
            reasons = [
                f"Market regime detected: {regime}",
                (
                    f"{winner} selected by adaptive evidence weight "
                    f"({votes[winner]:.3f} of {total_weight:.3f})"
                ),
            ]
        else:
            signal = "NEUTRAL"
            confidence = 0.0
            dissent = []
            reasons = [
                f"Market regime detected: {regime}",
                "No directional evidence; consensus is NEUTRAL",
            ]

        for name in dissent:
            reasons.append(
                f"dissent: {name} reported " f"{specialist_results[name].get('signal', 'NEUTRAL')}"
            )

        # Phase 7 (advisory only): cite prior lessons without touching the
        # signal or confidence — the deterministic synthesis stays intact.
        lessons_reason = format_lessons_reason(context.get("lessons"))
        if lessons_reason:
            reasons.append(lessons_reason)

        return {
            "agent": self.name,
            "role": "department_lead",
            "department": "market",
            "signal": signal,
            "confidence": round(confidence, 4),
            "reasons": reasons,
            "regime": regime,
            "regime_weights": weights,
            "specialist_results": specialist_results,
            "dissent": dissent,
            "unresolved_conflict": len(votes) > 1,
        }

    def execute(self, task):
        return {"status": "ok"}

    def to_dict(self) -> dict[str, Any]:
        """Include department identity in standard agent metadata."""
        result = super().to_dict()
        result.update({"department": "market", "role": "department_lead"})
        return result
