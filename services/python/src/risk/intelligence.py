# -*- coding: utf-8 -*-
"""Risk Intelligence — EPIC 05 implementations.

This module provides the AI risk department: RiskLead plus four
specialist analysts (Account, Position, Portfolio, Drawdown). The
department produces advisory reports and recommendations only — it
cannot alter deterministic hard limits enforced by the RiskGate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.base import AgentPriority, BaseAgent


@dataclass
class RiskAssessmentReport:
    """Result of a specialist risk analysis."""

    analyst: str
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    score: float  # 0.0 (safe) to 1.0 (max risk)
    evidence: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class RiskCommitteeDecision:
    """Synthesized risk committee decision (advisory only)."""

    department: str
    overall_risk: str
    score: float
    reports: list[RiskAssessmentReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "department": self.department,
            "overall_risk": self.overall_risk,
            "score": self.score,
            "reports": [
                {
                    "analyst": r.analyst,
                    "risk_level": r.risk_level,
                    "score": r.score,
                    "evidence": r.evidence,
                    "warnings": r.warnings,
                }
                for r in self.reports
            ],
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


def _score_to_level(score: float) -> str:
    """Map a 0-1 risk score to a level string."""
    if score < 0.25:
        return "LOW"
    if score < 0.5:
        return "MEDIUM"
    if score < 0.75:
        return "HIGH"
    return "CRITICAL"


class AccountRiskAnalyst(BaseAgent):
    """Account-level risk analyst (margin, equity, daily loss)."""

    def __init__(self):
        super().__init__(
            name="Account Risk Analyst",
            agent_type="analyst",
            description="Evaluates account-level risk metrics",
            permissions=["ANALYZE_RISK"],
        )

    def analyze(self, data: dict[str, Any]) -> RiskAssessmentReport:
        """Produce account risk report."""
        balance = data.get("balance", 10000.0)
        equity = data.get("equity", balance)
        daily_loss = abs(data.get("daily_loss", 0.0))
        margin_used = data.get("margin_used", 0.0)
        free_margin = data.get("free_margin", balance - margin_used)

        score = 0.0
        warnings: list[str] = []

        # Daily loss as fraction of balance
        if balance > 0:
            loss_frac = daily_loss / balance
            score += min(loss_frac * 5.0, 0.4)
            if loss_frac > 0.02:
                warnings.append(f"Daily loss {loss_frac:.1%} of balance")

        # Margin usage
        if balance > 0 and margin_used > 0:
            margin_ratio = margin_used / balance
            score += min(margin_ratio * 0.3, 0.3)
            if margin_ratio > 0.3:
                warnings.append(f"Margin usage {margin_ratio:.1%}")

        # Equity drawdown from balance
        if balance > 0 and equity < balance:
            eq_ratio = (balance - equity) / balance
            score += min(eq_ratio * 2.0, 0.3)

        score = min(score, 1.0)
        return RiskAssessmentReport(
            analyst="AccountRiskAnalyst",
            risk_level=_score_to_level(score),
            score=score,
            evidence=(
                f"Balance: {balance}, Equity: {equity}, "
                f"Daily loss: {daily_loss}, "
                f"Margin used: {margin_used}, "
                f"Free margin: {free_margin}"
            ),
            warnings=warnings,
        )

    def execute(self, task):
        return {"status": "ok"}


class PositionRiskAnalyst(BaseAgent):
    """Position-level risk analyst (concentration, per-position PnL)."""

    def __init__(self):
        super().__init__(
            name="Position Risk Analyst",
            agent_type="analyst",
            description="Evaluates open position risk and concentration",
            permissions=["ANALYZE_RISK"],
        )

    def analyze(self, data: dict[str, Any]) -> RiskAssessmentReport:
        """Produce position risk report."""
        positions = data.get("positions", [])
        total_lots = data.get("total_open_lots", 0.0)

        score = 0.0
        warnings: list[str] = []

        if not positions:
            return RiskAssessmentReport(
                analyst="PositionRiskAnalyst",
                risk_level="LOW",
                score=0.0,
                evidence="No open positions",
            )

        # Total loss across positions
        total_loss = sum(abs(p.get("pnl", 0.0)) for p in positions if p.get("pnl", 0) < 0)
        if total_loss > 0:
            score += min(total_loss / 1000.0, 0.3)

        # Concentration — single position lots vs total
        if total_lots > 0:
            for p in positions:
                vol = p.get("volume", 0.0)
                if vol / total_lots > 0.5:
                    score += 0.15
                    warnings.append(f"High concentration in {p.get('symbol', '?')}")

        # Number of positions
        if len(positions) > 5:
            score += 0.1
            warnings.append(f"Many open positions: {len(positions)}")

        score = min(score, 1.0)
        return RiskAssessmentReport(
            analyst="PositionRiskAnalyst",
            risk_level=_score_to_level(score),
            score=score,
            evidence=(
                f"Positions: {len(positions)}, "
                f"Total lots: {total_lots}, "
                f"Total loss: {total_loss}"
            ),
            warnings=warnings,
        )

    def execute(self, task):
        return {"status": "ok"}


class PortfolioRiskAnalyst(BaseAgent):
    """Portfolio-level risk analyst (correlation, net exposure)."""

    def __init__(self):
        super().__init__(
            name="Portfolio Risk Analyst",
            agent_type="analyst",
            description="Evaluates portfolio correlations and exposure",
            permissions=["ANALYZE_RISK"],
        )

    def analyze(self, data: dict[str, Any]) -> RiskAssessmentReport:
        """Produce portfolio risk report."""
        symbols = data.get("symbols", [])
        correlation = data.get("correlation_matrix", {})
        net_exposure = data.get("net_exposure_usd", 0.0)

        score = 0.0
        warnings: list[str] = []

        # High correlation increases portfolio risk
        high_corr_count = 0
        for pair, corr in correlation.items():
            if abs(corr) > 0.7:
                high_corr_count += 1
                score += 0.1
        if high_corr_count > 0:
            warnings.append(f"{high_corr_count} high correlation pair(s)")

        # Net exposure relative to a notional $10k account
        if net_exposure > 0:
            exposure_ratio = net_exposure / 10000.0
            score += min(exposure_ratio * 0.2, 0.3)

        score = min(score, 1.0)
        return RiskAssessmentReport(
            analyst="PortfolioRiskAnalyst",
            risk_level=_score_to_level(score),
            score=score,
            evidence=(
                f"Symbols: {len(symbols)}, "
                f"Correlations: {len(correlation)}, "
                f"Net exposure: ${net_exposure}"
            ),
            warnings=warnings,
        )

    def execute(self, task):
        return {"status": "ok"}


class DrawdownAnalyst(BaseAgent):
    """Drawdown analyst (peak-to-trough assessment)."""

    def __init__(self):
        super().__init__(
            name="Drawdown Analyst",
            agent_type="analyst",
            description="Assesses current and max drawdown",
            permissions=["ANALYZE_RISK"],
        )

    def analyze(self, data: dict[str, Any]) -> RiskAssessmentReport:
        """Produce drawdown risk report."""
        current_dd = data.get("current_drawdown_pct", 0.0)
        max_dd = data.get("max_drawdown_pct", 100.0)

        score = 0.0
        warnings: list[str] = []

        # Current drawdown as fraction of max allowed
        if max_dd > 0:
            dd_ratio = current_dd / max_dd
            score = min(dd_ratio, 1.0)
            if dd_ratio > 0.6:
                warnings.append(f"Drawdown {current_dd:.1f}% approaching " f"max {max_dd:.1f}%")

        return RiskAssessmentReport(
            analyst="DrawdownAnalyst",
            risk_level=_score_to_level(score),
            score=score,
            evidence=(f"Current DD: {current_dd:.1f}%, " f"Max DD: {max_dd:.1f}%"),
            warnings=warnings,
        )

    def execute(self, task):
        return {"status": "ok"}


class RiskDepartment:
    """Risk Intelligence Department."""

    def __init__(self, lead: RiskLead):
        self.lead = lead
        self.specialists = [
            AccountRiskAnalyst(),
            PositionRiskAnalyst(),
            PortfolioRiskAnalyst(),
            DrawdownAnalyst(),
        ]


class RiskLead(BaseAgent):
    """Risk Intelligence Department Lead (advisory only)."""

    def __init__(self):
        super().__init__(
            name="Risk Lead",
            agent_type="lead",
            description="Leads risk intelligence analysis (advisory)",
            permissions=["ANALYZE_RISK"],
            priority=AgentPriority.HIGH,
        )
        self.department: RiskDepartment | None = None

    def create_department(self) -> RiskDepartment:
        """Create and manage risk department."""
        self.department = RiskDepartment(self)
        return self.department

    def synthesize(self, risk_data: dict[str, Any]) -> RiskCommitteeDecision:
        """Synthesize advisory risk assessment from specialists."""
        if not self.department:
            self.create_department()

        reports = []
        for specialist in self.department.specialists:
            report = specialist.analyze(risk_data)
            reports.append(report)

        scores = [r.score for r in reports]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        all_warnings = []
        all_recommendations = []
        for r in reports:
            all_warnings.extend(r.warnings)

        if avg_score < 0.25:
            all_recommendations.append("Proceed with normal sizing")
        elif avg_score < 0.5:
            all_recommendations.append("Reduce position size by 25%")
        elif avg_score < 0.75:
            all_recommendations.append("Reduce position size by 50%")
            all_recommendations.append("No new entries until risk lowers")
        else:
            all_recommendations.append("Halt new entries immediately")
            all_recommendations.append("Consider closing worst positions")

        return RiskCommitteeDecision(
            department="risk",
            overall_risk=_score_to_level(avg_score),
            score=avg_score,
            reports=reports,
            warnings=all_warnings,
            recommendations=all_recommendations,
        )

    def can_handle(self, task_type: str) -> bool:
        return task_type == "risk_analysis"

    def execute(self, task):
        return {"status": "ok"}

    def analyze(self, data: dict[str, Any]) -> RiskAssessmentReport:
        """BaseAgent abstract method implementation."""
        decision = self.synthesize(data)
        return RiskAssessmentReport(
            analyst="RiskLead",
            risk_level=decision.overall_risk,
            score=decision.score,
            evidence=(f"Consensus from {len(decision.reports)} specialists"),
        )
