# -*- coding: utf-8 -*-
"""Risk Gate — pre-trade validation and account safety checks.

Formalises the risk gate as a class with a ``validate`` method that
aggregates all safety checks before any order is allowed to proceed.
This is the single gate every agent and the supervisor must pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class RiskGateResult(Enum):
    """Outcome of a risk gate validation."""

    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass
class RiskGateError:
    """A single risk gate violation or warning."""

    code: str
    message: str
    severity: str  # "ERROR" | "WARNING" | "INFO"
    blocking: bool = True
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskGateValidationResult:
    """Aggregate result of :meth:`RiskGate.validate`."""

    outcome: RiskGateResult
    errors: list[RiskGateError] = field(default_factory=list)
    checked_at: str = ""
    checks_passed: int = 0
    checks_total: int = 0

    @property
    def is_safe(self) -> bool:
        """True when outcome is PASS (no blocking errors)."""
        return self.outcome == RiskGateResult.PASS

    @property
    def has_warnings(self) -> bool:
        return any(e.severity == "WARNING" for e in self.errors)

    def __bool__(self) -> bool:
        return self.is_safe


# ---------------------------------------------------------------------------
# RiskGate
# ---------------------------------------------------------------------------


class RiskGate:
    """Central risk validation gate.

    Every order, signal, or agent recommendation must pass through
    ``validate()`` before execution.  The gate checks:

    - Account safety (equity, drawdown, daily loss)
    - Position limits (size, exposure)
    - Market risk (volatility, spread, news)
    - Strategy guardrails (min confidence, max daily trades)
    """

    def __init__(
        self,
        max_daily_loss: float = 500.0,
        max_position_size: float = 1000.0,
        max_exposure_percent: float = 20.0,
        max_daily_trades: int = 20,
        min_signal_confidence: float = 0.5,
        max_account_drawdown_percent: float = 15.0,
        margin_call_threshold: float = 0.5,  # 50% margin used → warn
        auto_block_on_margin_call: bool = True,
    ) -> None:
        self.max_daily_loss = max_daily_loss
        self.max_position_size = max_position_size
        self.max_exposure_percent = max_exposure_percent
        self.max_daily_trades = max_daily_trades
        self.min_signal_confidence = min_signal_confidence
        self.max_account_drawdown_percent = max_account_drawdown_percent
        self.margin_call_threshold = margin_call_threshold
        self.auto_block_on_margin_call = auto_block_on_margin_call

        self.created_at = datetime.now(timezone.utc).isoformat()

    def validate(
        self,
        account_equity: float,
        daily_pnl: float = 0.0,
        open_positions: int = 0,
        total_exposure: float = 0.0,
        margin_used_percent: float = 0.0,
        signal_confidence: float = 0.0,
        detected_events: Optional[list[dict]] = None,
        daily_trades_today: int = 0,
        current_drawdown_percent: float = 0.0,
    ) -> RiskGateValidationResult:
        """Run the full risk gate validation.

        Args:
            account_equity: Current account equity.
            daily_pnl: Today's net PnL (negative = loss).
            open_positions: Number of currently open positions.
            total_exposure: Total position value across all open trades.
            margin_used_percent: Margin used as a fraction (0.5 = 50%).
            signal_confidence: Confidence of the proposed signal (0–1).
            detected_events: List of detected events (for event-based risk).
            daily_trades_today: Trades already taken today.
            current_drawdown_percent: Current drawdown from peak (0–100).

        Returns:
            :class:`RiskGateValidationResult` — check ``is_safe`` before
            proceeding with any order.
        """
        errors: list[RiskGateError] = []
        checks_passed = 0
        checks_total = 0

        # ── 1. Account equity sanity ───────────────────────────────────────
        checks_total += 1
        if account_equity > 0:
            checks_passed += 1
        else:
            errors.append(
                RiskGateError(
                    code="ACCT_EQUITY_INVALID",
                    message="Account equity must be positive",
                    severity="ERROR",
                    blocking=True,
                    details={"account_equity": account_equity},
                )
            )

        # ── 2. Daily loss limit ────────────────────────────────────────────
        checks_total += 1
        if daily_pnl >= -self.max_daily_loss:
            checks_passed += 1
        else:
            errors.append(
                RiskGateError(
                    code="DAILY_LOSS_LIMIT",
                    message=(
                        f"Daily loss limit reached: {daily_pnl:.2f}"
                        f" < -{self.max_daily_loss:.2f}"
                    ),
                    severity="ERROR",
                    blocking=True,
                    details={"daily_pnl": daily_pnl, "limit": -self.max_daily_loss},
                )
            )

        # ── 3. Position size limit ─────────────────────────────────────────
        checks_total += 1
        if total_exposure <= self.max_position_size:
            checks_passed += 1
        else:
            errors.append(
                RiskGateError(
                    code="POSITION_SIZE_LIMIT",
                    message=(
                        f"Total exposure exceeds limit:"
                        f" {total_exposure:.2f} > {self.max_position_size:.2f}"
                    ),
                    severity="ERROR",
                    blocking=True,
                    details={"total_exposure": total_exposure, "limit": self.max_position_size},
                )
            )

        # ── 4. Exposure percent ────────────────────────────────────────────
        checks_total += 1
        if account_equity > 0:
            exposure_pct = total_exposure / account_equity * 100.0
            if exposure_pct <= self.max_exposure_percent:
                checks_passed += 1
            else:
                errors.append(
                    RiskGateError(
                        code="EXPOSURE_LIMIT",
                        message=(
                            f"Exposure {exposure_pct:.1f}% exceeds"
                            f" limit {self.max_exposure_percent:.1f}%"
                        ),
                        severity="WARNING",
                        blocking=False,
                        details={"exposure_pct": exposure_pct, "limit": self.max_exposure_percent},
                    )
                )
        else:
            checks_passed += 1  # already flagged in step 1

        # ── 5. Margin call check ───────────────────────────────────────────
        checks_total += 1
        if margin_used_percent >= self.margin_call_threshold:
            if self.auto_block_on_margin_call:
                errors.append(
                    RiskGateError(
                        code="MARGIN_CALL",
                        message=(
                            f"Margin usage {margin_used_percent*100:.1f}%"
                            f" ≥ threshold {self.margin_call_threshold*100:.1f}%"
                            " — blocked"
                        ),
                        severity="ERROR",
                        blocking=True,
                        details={
                            "margin_used": margin_used_percent,
                            "threshold": self.margin_call_threshold,
                        },
                    )
                )
            else:
                checks_passed += 1
                errors.append(
                    RiskGateError(
                        code="MARGIN_CALL_WARN",
                        message=(
                            f"Margin usage {margin_used_percent*100:.1f}%"
                            f" ≥ threshold {self.margin_call_threshold*100:.1f}%"
                            " — warning only"
                        ),
                        severity="WARNING",
                        blocking=False,
                        details={
                            "margin_used": margin_used_percent,
                            "threshold": self.margin_call_threshold,
                        },
                    )
                )
        else:
            checks_passed += 1

        # ── 6. Signal confidence ───────────────────────────────────────────
        checks_total += 1
        if signal_confidence >= self.min_signal_confidence:
            checks_passed += 1
        else:
            errors.append(
                RiskGateError(
                    code="LOW_CONFIDENCE",
                    message=(
                        f"Signal confidence {signal_confidence:.2f} below"
                        f" minimum {self.min_signal_confidence:.2f}"
                    ),
                    severity="WARNING",
                    blocking=False,
                    details={"confidence": signal_confidence, "min": self.min_signal_confidence},
                )
            )

        # ── 7. Daily trade limit ───────────────────────────────────────────
        checks_total += 1
        if daily_trades_today < self.max_daily_trades:
            checks_passed += 1
        else:
            errors.append(
                RiskGateError(
                    code="DAILY_TRADE_LIMIT",
                    message=(
                        f"Daily trade limit reached: {daily_trades_today}"
                        f" ≥ {self.max_daily_trades}"
                    ),
                    severity="ERROR",
                    blocking=True,
                    details={"trades_today": daily_trades_today, "limit": self.max_daily_trades},
                )
            )

        # ── 8. Account drawdown ────────────────────────────────────────────
        checks_total += 1
        if current_drawdown_percent <= self.max_account_drawdown_percent:
            checks_passed += 1
        else:
            errors.append(
                RiskGateError(
                    code="DRAWDOWN_LIMIT",
                    message=(
                        f"Account drawdown {current_drawdown_percent:.1f}%"
                        f" exceeds limit"
                        f" {self.max_account_drawdown_percent:.1f}%"
                    ),
                    severity="ERROR",
                    blocking=True,
                    details={
                        "drawdown": current_drawdown_percent,
                        "limit": self.max_account_drawdown_percent,
                    },
                )
            )

        # ── 9. Event-based risk ────────────────────────────────────────────
        checks_total += 1
        if detected_events:
            # If any blocking event (e.g. DRAWDOWN_WARNING, EXPOSURE_LIMIT_REACHED)
            blocking_events = [
                e for e in detected_events if isinstance(e, dict) and e.get("blocking", False)
            ]
            if blocking_events:
                errors.append(
                    RiskGateError(
                        code="BLOCKING_EVENTS",
                        message=f"{len(blocking_events)} blocking event(s) detected",
                        severity="ERROR",
                        blocking=True,
                        details={"blocking_events": blocking_events},
                    )
                )
            checks_passed += 0  # event check always counted; result depends on events
        else:
            checks_passed += 1

        # ── Determine outcome ──────────────────────────────────────────────
        blocking_errors = [e for e in errors if e.blocking]
        if blocking_errors:
            outcome = RiskGateResult.BLOCK
        elif errors:
            outcome = RiskGateResult.WARN
        else:
            outcome = RiskGateResult.PASS

        return RiskGateValidationResult(
            outcome=outcome,
            errors=errors,
            checked_at=datetime.now(timezone.utc).isoformat(),
            checks_passed=checks_passed,
            checks_total=checks_total,
        )

    def check_account_safety(
        self,
        account_equity: float,
        account_balance: float,
        margin_used: float,
        open_positions_value: float,
        daily_pnl: float,
        current_drawdown: float,
    ) -> dict[str, Any]:
        """Lightweight account safety check (used in health endpoints and dashboard).

        Returns a dict with safety flags rather than a full RiskGateResult —
        suitable for quick polling.
        """
        margin_pct = margin_used  # already a fraction 0–1
        exposure_pct = (
            (open_positions_value / account_equity * 100.0) if account_equity > 0 else 0.0
        )
        daily_loss_ok = daily_pnl >= -self.max_daily_loss
        drawdown_ok = current_drawdown <= self.max_account_drawdown_percent
        margin_ok = margin_pct < self.margin_call_threshold
        equity_ok = account_equity > 0

        return {
            "account_equity": account_equity,
            "account_balance": account_balance,
            "margin_used_pct": margin_pct * 100.0,
            "exposure_pct": exposure_pct,
            "daily_pnl": daily_pnl,
            "current_drawdown_pct": current_drawdown,
            "safe": all([daily_loss_ok, drawdown_ok, margin_ok, equity_ok]),
            "flags": {
                "daily_loss_ok": daily_loss_ok,
                "drawdown_ok": drawdown_ok,
                "margin_ok": margin_ok,
                "equity_ok": equity_ok,
            },
            "checks": {
                "max_daily_loss": self.max_daily_loss,
                "max_drawdown_pct": self.max_account_drawdown_percent,
                "margin_threshold_pct": self.margin_call_threshold * 100.0,
            },
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
