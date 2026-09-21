# -*- coding: utf-8 -*-
"""MT5 Write Guard — permission, volume, and monetary validation.

Before an order can be transmitted to MetaTrader 5, this guard enforces:
1. Agent has ``SEND_TO_MT5`` permission.
2. Order volume is within symbol-specific minima and maxima.
3. Daily loss limit has not been exceeded.
4. Total exposure does not breach portfolio limit.

The guard is intentionally strict: violations raise exceptions; silent
rejection would be dangerous (orders could slip through).  Only when all
checks pass does ``send_order`` proceed to the raw MT5 connector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agents.base import BaseAgent
from agents.permissions import AgentPermissionError, require_permission

# ---------------------------------------------------------------------------
# Validation result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Result of order validation."""

    valid: bool
    reason: str = ""
    checked: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual validation helpers
# ---------------------------------------------------------------------------


def validate_volume(
    symbol: str,
    volume: float,
    min_volume: float,
    max_volume: float,
) -> ValidationResult:
    """Validate order volume is within allowed range."""
    if volume < min_volume:
        return ValidationResult(False, f"Volume {volume} below minimum {min_volume}")
    if volume > max_volume:
        return ValidationResult(False, f"Volume {volume} above maximum {max_volume}")
    return ValidationResult(True, checked=["volume"])


def validate_daily_loss(
    account_state: dict[str, Any],
    daily_loss_limit: float,
) -> ValidationResult:
    """Validate daily loss does not exceed threshold (as % of balance)."""
    daily_pnl = account_state.get("daily_pnl", 0.0)
    balance = account_state.get("balance", 1.0)
    loss_ratio = daily_pnl / balance if balance else 0
    if loss_ratio < -daily_loss_limit:
        msg = f"Daily loss {loss_ratio:.2%} exceeds limit " f"{daily_loss_limit:.2%}"
        return ValidationResult(False, msg)
    return ValidationResult(True, checked=["daily_loss"])


def validate_exposure(
    positions: list[dict[str, Any]],
    max_exposure_pct: float,
    account_balance: float,
) -> ValidationResult:
    """Validate total exposure does not exceed threshold (audit P2-10).

    ``account_balance`` is the REAL account balance (from account state). The
    previous implementation assumed a fixed 10000 balance, which produced
    fictional exposure percentages. When the balance is unknown/zero, exposure
    cannot be computed → the check fails closed.
    """
    if account_balance <= 0:
        return ValidationResult(False, "Cannot validate exposure without account balance")
    total_exposure = sum(abs(p.get("volume", 0) * p.get("price", 1.0)) for p in positions)
    exposure_pct = total_exposure / account_balance * 100.0
    if exposure_pct > max_exposure_pct * 100:
        msg = f"Total exposure {exposure_pct:.1%} exceeds limit " f"{max_exposure_pct:.1%}"
        return ValidationResult(False, msg)
    return ValidationResult(True, checked=["exposure"])


# ---------------------------------------------------------------------------
# MT5WriteGuard class
# ---------------------------------------------------------------------------


@dataclass
class MT5WriteGuard:
    """Enforces permission and monetary validation before MT5 order submission.

    Configuration fields (all floats):
        min_volume: minimum lot size per symbol.
        max_volume: maximum lot size per symbol.
        daily_loss_limit: max daily loss as fraction (e.g. 0.1 = 10%).
        max_exposure_pct: max total exposure as fraction of account.
    """

    min_volume: float = 0.01
    max_volume: float = 100.0
    daily_loss_limit: float = 0.1
    max_exposure_pct: float = 0.2
    _on_before_send: Optional[Callable[[BaseAgent, dict[str, Any]], None]] = None

    def validate_order(
        self,
        agent: BaseAgent,
        order: dict[str, Any],
        positions: Optional[list[dict[str, Any]]] = None,
        account_state: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Validate an order before sending to MT5.

        Returns dict with keys:
            ``valid`` (bool): True if order may proceed.
            ``reason`` (str): Human-readable explanation if invalid.
            ``checked`` (list): Names of checks that passed.
        """
        validations: list[ValidationResult] = []

        # 1. Permission check
        try:
            require_permission(agent, "SEND_TO_MT5")
            validations.append(ValidationResult(True, checked=["permission"]))
        except AgentPermissionError as e:
            return {
                "valid": False,
                "reason": str(e),
                "checked": ["permission"],
            }

        # 2. Volume check — evaluated first so an obviously invalid order is
        # rejected without needing account context.
        volume = order.get("volume", order.get("quantity", 0))
        symbol = order.get("symbol", "EURUSD")
        volume_result = validate_volume(symbol, volume, self.min_volume, self.max_volume)
        validations.append(volume_result)
        if not volume_result.valid:
            return {"valid": False, "reason": volume_result.reason, "checked": ["permission"]}

        # 3. Daily loss check (audit P2-9: fail-closed — account_state required).
        if not account_state:
            return {
                "valid": False,
                "reason": "Cannot validate order without account state (daily loss).",
                "checked": ["permission", "volume"],
            }
        loss_result = validate_daily_loss(account_state, self.daily_loss_limit)
        validations.append(loss_result)
        if not loss_result.valid:
            return {
                "valid": False,
                "reason": loss_result.reason,
                "checked": ["permission", "volume"],
            }

        # 4. Exposure check (audit P2-9/P2-10: fail-closed, real balance).
        if positions is None:
            return {
                "valid": False,
                "reason": "Cannot validate order without current positions (exposure).",
                "checked": ["permission", "volume", "daily_loss"],
            }
        balance = float(account_state.get("balance", 0.0) or 0.0)
        validations.append(validate_exposure(positions, self.max_exposure_pct, balance))

        # Combine results
        failed = [v for v in validations if not v.valid]
        if failed:
            all_checked = []
            for v in validations:
                if v.valid and v.checked:
                    all_checked.extend(v.checked)
            return {
                "valid": False,
                "reason": failed[0].reason,
                "checked": all_checked,
            }

        all_checked = []
        for v in validations:
            if v.valid and v.checked:
                all_checked.extend(v.checked)
        return {
            "valid": True,
            "reason": "",
            "checked": all_checked,
        }

    def send_order(
        self,
        agent: BaseAgent,
        order: dict[str, Any],
        positions: Optional[list[dict[str, Any]]] = None,
        account_state: Optional[dict[str, Any]] = None,
        executor: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Validate then delegate to the MT5 connector (audit P2-9).

        The guard now performs the write boundary it documents: it validates
        (fail-closed), then calls the injected ``executor`` (defaults to the
        module-level :func:`mt5.connector.execute_order`). It no longer returns a
        fake success without sending.

        Raises:
            AgentPermissionError: if agent lacks permission.
            ValueError: if validation fails.
        """
        from agents.permissions import require_permission

        # Permission check raises AgentPermissionError on miss.
        require_permission(agent, "SEND_TO_MT5")
        result = self.validate_order(agent, order, positions=positions, account_state=account_state)
        if not result["valid"]:
            raise ValueError(result["reason"])

        run = executor if executor is not None else self._default_executor()
        out = run(order)
        if isinstance(out, dict):
            out.setdefault("checked", result["checked"])
        return out or {
            "success": False,
            "order_id": None,
            "message": "MT5 executor returned no result",
            "checked": result["checked"],
        }

    @staticmethod
    def _default_executor() -> Callable[[dict[str, Any]], dict[str, Any]]:
        """Return the production connector executor (read-only-safe)."""
        from mt5 import connector

        return connector.execute_order
