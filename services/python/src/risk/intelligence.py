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


#: Supervisor-facing key for each specialist report (stable contract).
_REPORT_KEYS: dict[str, str] = {
    "AccountRiskAnalyst": "account_risk",
    "PositionRiskAnalyst": "position_risk",
    "PortfolioRiskAnalyst": "portfolio_risk",
    "DrawdownAnalyst": "drawdown",
}


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
    """Risk Intelligence Department Lead (advisory only).

    Registered as ``agent_type="department_lead"`` so the Supervisor detects
    it (EPIC 01) and delegates risk events to it.  ``analyze`` returns a
    Supervisor-compatible dict; :meth:`synthesize` keeps the legacy committee
    API intact.  This agent is advisory only — it can never veto a trade,
    bypass a limit, or reach MT5.
    """

    #: Event families routed to the risk committee.
    RISK_EVENT_PREFIXES = (
        "RISK_",
        "DRAWDOWN_",
        "EXPOSURE_",
        "LIQUIDITY_",
        "MARGIN_",
        "CORRELATION_",
        "PORTFOLIO_",
    )

    def __init__(self):
        super().__init__(
            name="risk_lead",
            agent_type="department_lead",
            description="Leads the risk intelligence department (advisory only)",
            role="department_lead",
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

    def can_handle(self, event_type: str, context: dict[str, Any] | None = None) -> bool:
        """Accept risk event families; keep the legacy ``risk_analysis`` task."""
        if event_type == "risk_analysis":
            return True
        return any(event_type.startswith(prefix) for prefix in self.RISK_EVENT_PREFIXES)

    @staticmethod
    def _as_number(value: Any) -> float | None:
        """Coerce a value to float; non-numeric input fails closed to None."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _coerce_risk_data(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Best-effort extraction of risk data from a supervisor context.

        Accepts ``{"risk_data": {...}}`` or a flat context with
        ``account``/``positions`` fields.  Malformed values are dropped and
        ``None`` is returned when no usable risk data remains (fail-closed).
        """
        if not isinstance(context, dict):
            return None

        source: dict[str, Any] = {}
        raw = context.get("risk_data")
        if isinstance(raw, dict):
            source.update(raw)
        else:
            account = context.get("account")
            if isinstance(account, dict):
                source["balance"] = account.get("balance")
                source["equity"] = account.get("equity")
                margin = account.get("used_margin", account.get("margin_used"))
                if margin is not None:
                    source["margin_used"] = margin
                if account.get("free_margin") is not None:
                    source["free_margin"] = account.get("free_margin")

            for key in (
                "balance",
                "equity",
                "margin_used",
                "free_margin",
                "daily_loss",
                "positions",
                "total_open_lots",
                "symbols",
                "correlation_matrix",
                "net_exposure_usd",
                "current_drawdown_pct",
                "max_drawdown_pct",
                "peak_equity",
                "current_equity",
            ):
                if key not in source and context.get(key) is not None:
                    source[key] = context[key]

        numeric_fields = (
            "balance",
            "equity",
            "margin_used",
            "free_margin",
            "daily_loss",
            "total_open_lots",
            "net_exposure_usd",
            "current_drawdown_pct",
            "max_drawdown_pct",
            "peak_equity",
            "current_equity",
        )
        cleaned: dict[str, Any] = {}
        for key in numeric_fields:
            number = self._as_number(source.get(key))
            if number is not None:
                cleaned[key] = number

        positions = source.get("positions")
        if isinstance(positions, list) and all(isinstance(p, dict) for p in positions):
            cleaned["positions"] = positions

        symbols = source.get("symbols")
        if isinstance(symbols, list):
            cleaned["symbols"] = [s for s in symbols if isinstance(s, str)]

        correlation = source.get("correlation_matrix")
        if isinstance(correlation, dict):
            cleaned["correlation_matrix"] = {
                str(key): float(value)
                for key, value in correlation.items()
                if self._as_number(value) is not None
            }

        # Derive current drawdown from peak/current equity when absent.
        if (
            "current_drawdown_pct" not in cleaned
            and "peak_equity" in cleaned
            and "current_equity" in cleaned
            and cleaned["peak_equity"] > 0
        ):
            peak = cleaned["peak_equity"]
            trough = cleaned["current_equity"]
            cleaned["current_drawdown_pct"] = max(0.0, (peak - trough) / peak * 100.0)

        has_numbers = any(key in cleaned for key in numeric_fields)
        has_portfolio = bool(cleaned.get("symbols")) or bool(cleaned.get("correlation_matrix"))
        has_positions = bool(cleaned.get("positions"))
        if not (has_numbers or has_portfolio or has_positions):
            return None
        return cleaned

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run the advisory risk committee and return a Supervisor dict.

        The deterministic RiskGate keeps sole authority over hard limits;
        this method only produces advisory evidence (never a veto).  Missing
        or malformed input fails closed to NEUTRAL instead of raising.
        """
        risk_data = self._coerce_risk_data(context if isinstance(context, dict) else {})

        if not risk_data:
            return {
                "agent": self.name,
                "role": "department_lead",
                "department": "risk",
                "signal": "NEUTRAL",
                "confidence": 0.0,
                "reasons": ["No risk data available for analysis (fail-closed NEUTRAL)"],
                "specialist_results": {},
                "advisory": True,
                "overall_risk": "UNKNOWN",
                "risk_score": None,
                "recommendations": [],
            }

        if not self.department:
            self.create_department()

        specialist_results: dict[str, dict[str, Any]] = {}
        reports: list[RiskAssessmentReport] = []
        warnings: list[str] = []
        for specialist in self.department.specialists:
            key = _REPORT_KEYS.get(type(specialist).__name__, type(specialist).__name__)
            try:
                report = specialist.analyze(risk_data)
            except Exception as exc:  # defensive boundary around specialists
                specialist_results[key] = {
                    "agent": key,
                    "status": "ERROR",
                    "risk_level": "UNKNOWN",
                    "score": 0.0,
                    "evidence": f"Specialist failed: {exc}",
                    "warnings": [],
                }
                continue
            reports.append(report)
            warnings.extend(report.warnings)
            specialist_results[key] = {
                "agent": key,
                "status": "OK",
                "risk_level": report.risk_level,
                "score": report.score,
                "evidence": report.evidence,
                "warnings": report.warnings,
            }

        scores = [r.score for r in reports]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        overall_risk = _score_to_level(avg_score)

        if avg_score < 0.25:
            signal = "RISK_ON"
            confidence = round(min(1.0, 1.0 - avg_score), 4)
            recommendations = ["Proceed with normal sizing"]
        elif avg_score < 0.5:
            signal = "NEUTRAL"
            confidence = 0.5
            recommendations = ["Reduce position size by 25%"]
        elif avg_score < 0.75:
            signal = "RISK_OFF"
            confidence = round(min(1.0, avg_score), 4)
            recommendations = [
                "Reduce position size by 50%",
                "No new entries until risk lowers",
            ]
        else:
            signal = "RISK_OFF"
            confidence = round(min(1.0, avg_score), 4)
            recommendations = [
                "Halt new entries immediately",
                "Consider closing worst positions",
            ]

        reasons = [
            f"Risk committee aggregated {len(reports)} specialist report(s)",
            f"Aggregate risk score {avg_score:.3f} → {overall_risk}",
        ]
        reasons.extend(f"warning: {warning}" for warning in warnings[:5])

        return {
            "agent": self.name,
            "role": "department_lead",
            "department": "risk",
            "signal": signal,
            "confidence": confidence,
            "reasons": reasons,
            "specialist_results": specialist_results,
            "advisory": True,
            "overall_risk": overall_risk,
            "risk_score": round(avg_score, 4),
            "recommendations": recommendations,
        }

    def execute(self, task):
        return {"status": "ok"}

    def to_dict(self) -> dict[str, Any]:
        """Include department identity in standard agent metadata."""
        result = super().to_dict()
        result.update({"department": "risk", "role": "department_lead"})
        return result
