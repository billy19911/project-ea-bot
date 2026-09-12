# -*- coding: utf-8 -*-
"""Deterministic Risk Gate — hard pre-execution validation.

Phase 13: Final non-bypassable gate before order execution.
Checks drawdown, daily loss, positions, exposure, margin, spread, R:R, SL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import RiskThreshold
from .engine import RiskEngine
from .money_management import MoneyManager

__all__ = [
    "GateDecision",
    "RiskGate",
]


@dataclass(frozen=True)
class GateDecision:
    """Result of the deterministic risk gate validation.

    Attributes:
        approved: True if ALL checks pass; False if ANY check fails.
        reason: Human-readable summary of the decision.
        checks_passed: Per-check boolean results.
        metrics_snapshot: Snapshot of key metrics at validation time.
    """

    approved: bool
    reason: str
    checks_passed: dict[str, bool]
    metrics_snapshot: dict[str, Any]


class RiskGate:
    """Hard deterministic risk gate for pre-execution order validation.

    Cannot be bypassed by Supervisor/LLM. All checks must pass for approval.

    Args:
        risk_engine: RiskEngine instance for account/portfolio checks.
        money_manager: MoneyManager instance for position sizing and R:R.
        max_spread_pips: Maximum allowed spread in pips (default 5.0).
        min_rr: Minimum risk-to-reward ratio (default 1.5).
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        money_manager: MoneyManager,
        max_spread_pips: float = 5.0,
        min_rr: float = 1.5,
    ) -> None:
        self._engine = risk_engine
        self._mm = money_manager
        self._max_spread_pips = max_spread_pips
        self._min_rr = min_rr

    def validate_proposal(
        self,
        proposal: dict[str, Any],
        account_state: dict[str, Any],
        current_positions: list[dict[str, Any]],
        market_info: dict[str, Any],
    ) -> GateDecision:
        """Run all deterministic risk checks on a trade proposal.

        Args:
            proposal: Dict with keys: symbol, direction, entry_price,
                stop_loss, take_profit, size (lots), risk_pct.
            account_state: Dict with equity, balance, peak_equity, daily_pnl,
                used_margin, margin_call_level, free_margin.
            current_positions: List of open position dicts.
            market_info: Dict with spread_pips, point_value, contract_size.

        Returns:
            GateDecision with approved=False if ANY check fails.
        """
        checks: dict[str, bool] = {}
        metrics: dict[str, Any] = {}

        # ── 1. Drawdown limit ───────────────────────────────────────────────
        max_dd = self._engine.get_threshold(RiskThreshold.MAX_DRAWDOWN)
        dd_check = self._engine.check_drawdown(account_state, max_drawdown=max_dd)
        checks["drawdown_limit"] = dd_check
        metrics["drawdown_pct"] = self._engine.calculate_account_risk(account_state)["drawdown_pct"]
        metrics["max_drawdown"] = max_dd

        # ── 2. Daily loss limit ─────────────────────────────────────────────
        daily_limit = self._engine.get_threshold(RiskThreshold.DAILY_LOSS_LIMIT)
        daily_check = self._engine.check_daily_loss(account_state, daily_loss_limit=daily_limit)
        checks["daily_loss_limit"] = daily_check
        metrics["daily_loss_pct"] = self._engine.calculate_account_risk(account_state)[
            "daily_loss_pct"
        ]
        metrics["daily_loss_limit"] = daily_limit

        # ── 3. Max positions reached ────────────────────────────────────────
        max_pos = self._engine.get_threshold(RiskThreshold.MAX_POSITIONS)
        # A proposal opens one more position; equality means limit is reached.
        pos_count_check = len(current_positions) < max_pos
        checks["max_positions"] = pos_count_check
        metrics["position_count"] = len(current_positions)
        metrics["max_positions"] = max_pos

        # ── 4. Max exposure breached ────────────────────────────────────────
        max_exp = self._engine.get_threshold(RiskThreshold.MAX_EXPOSURE)
        exp_check = self._engine.check_exposure(current_positions, max_exposure=max_exp)
        checks["max_exposure"] = exp_check
        portfolio_risk = self._engine.calculate_portfolio_risk(
            current_positions, account_state.get("equity", 0.0)
        )
        metrics["total_exposure_pct"] = portfolio_risk["total_exposure_pct"]
        metrics["max_exposure"] = max_exp

        # ── 5. Margin call / low margin level ───────────────────────────────
        margin_thresh = self._engine.get_threshold(RiskThreshold.MARGIN_THRESHOLD)
        margin_check = self._engine.check_margin(account_state, margin_threshold=margin_thresh)
        checks["margin_level"] = margin_check
        equity = float(account_state.get("equity", 0.0))
        used_margin = float(account_state.get("used_margin", 0.0))
        metrics["margin_used_pct"] = used_margin / equity if equity > 0 else 1.0
        metrics["margin_threshold"] = margin_thresh

        # ── 6. Spread too wide ──────────────────────────────────────────────
        spread_pips = float(market_info.get("spread_pips", 0.0))
        spread_check = spread_pips <= self._max_spread_pips
        checks["spread"] = spread_check
        metrics["spread_pips"] = spread_pips
        metrics["max_spread_pips"] = self._max_spread_pips

        # ── 7. Invalid R:R ratio (< min threshold) ──────────────────────────
        entry = float(proposal.get("entry_price", 0.0))
        sl = float(proposal.get("stop_loss", 0.0))
        tp = float(proposal.get("take_profit", 0.0))
        if entry > 0 and sl > 0 and tp > 0 and sl != entry:
            is_valid_rr, actual_rr = self._mm.validate_rr_ratio(
                entry_price=entry, sl_price=sl, tp_price=tp, min_rr=self._min_rr
            )
            rr_check = is_valid_rr
            metrics["risk_reward_ratio"] = actual_rr
        else:
            rr_check = False
            metrics["risk_reward_ratio"] = 0.0
        checks["risk_reward"] = rr_check
        metrics["min_rr"] = self._min_rr

        # ── 8. Missing / invalid SL ─────────────────────────────────────────
        sl_check = sl > 0 and sl != entry
        checks["stop_loss"] = sl_check
        metrics["stop_loss"] = sl
        metrics["entry_price"] = entry

        # ── Determine overall result ────────────────────────────────────────
        all_passed = all(checks.values())
        failed_checks = [k for k, v in checks.items() if not v]

        if all_passed:
            reason = "All risk checks passed"
        else:
            reason = f"REJECTED: failed checks — {', '.join(failed_checks)}"

        return GateDecision(
            approved=all_passed,
            reason=reason,
            checks_passed=checks,
            metrics_snapshot=metrics,
        )
