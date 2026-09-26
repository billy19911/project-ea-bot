# -*- coding: utf-8 -*-
"""Risk monitor (audit RISK-1): periodic drawdown/exposure/margin checks.

Emits RISK_* events to EventQueue when thresholds breached. OFF by default,
opt-in via RISK_MONITOR_ENABLED=true. Read-only MT5 operations only.

Design guarantees:
- **Observation-only** — never modifies positions/orders, only reads account state.
- **Fail-safe** — any error never crashes the app, logged and swallowed.
- **Explicit opt-in** — disabled by default, operator must enable.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["RiskMonitor"]


class RiskMonitor:
    """Periodic risk monitor that emits RISK_* events when thresholds breached.

    Args:
        check_interval_s: Seconds between checks (default 60).
        drawdown_threshold: Max drawdown % before RISK_DRAWDOWN event (default 0.05 = 5%).
        exposure_threshold: Max exposure % before RISK_EXPOSURE event (default 0.3 = 30%).
        margin_threshold: Min free margin % before RISK_MARGIN event (default 0.2 = 20%).
        on_emit: Callback invoked with (event_type, event_data) when risk detected.
    """

    def __init__(
        self,
        check_interval_s: float = 60.0,
        drawdown_threshold: float = 0.05,
        exposure_threshold: float = 0.30,
        margin_threshold: float = 0.20,
        on_emit: Optional[Callable[[str, dict[str, Any]], None]] = None,
    ) -> None:
        self._check_interval_s = max(1.0, float(check_interval_s))
        self._drawdown_threshold = float(drawdown_threshold)
        self._exposure_threshold = float(exposure_threshold)
        self._margin_threshold = float(margin_threshold)
        self._on_emit = on_emit
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stats: dict[str, int] = {
            "checks": 0,
            "drawdown_events": 0,
            "exposure_events": 0,
            "margin_events": 0,
            "errors": 0,
        }

    def start(self) -> None:
        """Start the monitor thread (idempotent)."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info(
                "Risk monitor started: interval=%.1fs, thresholds=(dd=%.1f%%, exp=%.1f%%, "
                "margin=%.1f%%)",
                self._check_interval_s,
                self._drawdown_threshold * 100,
                self._exposure_threshold * 100,
                self._margin_threshold * 100,
            )

    def stop(self) -> None:
        """Stop the monitor thread (idempotent, blocking)."""
        with self._lock:
            if not self._running:
                return
            self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Risk monitor stopped")

    def is_running(self) -> bool:
        """Return True if the monitor thread is running."""
        with self._lock:
            return self._running

    def stats(self) -> dict[str, int]:
        """Return snapshot of monitor statistics."""
        with self._lock:
            return dict(self._stats)

    def _run_loop(self) -> None:
        """Monitor loop (runs in daemon thread)."""
        while self._running:
            try:
                self._check_once()
            except Exception as exc:  # noqa: BLE001 - fail-safe, never crash
                with self._lock:
                    self._stats["errors"] += 1
                logger.exception("Risk monitor check failed: %s", exc)
            time.sleep(self._check_interval_s)

    def _check_once(self) -> None:
        """Perform one risk check cycle."""
        with self._lock:
            self._stats["checks"] += 1

        # Read account state (fail-safe: missing MT5 returns empty/zero)
        account_info = self._get_account_info()
        if not account_info:
            return

        equity = float(account_info.get("equity", 0.0))
        balance = float(account_info.get("balance", 0.0))
        margin = float(account_info.get("margin", 0.0))
        margin_free = float(account_info.get("margin_free", 0.0))

        # Check drawdown: (balance - equity) / balance
        if balance > 0:
            drawdown = (balance - equity) / balance
            if drawdown > self._drawdown_threshold:
                self._emit_event(
                    "RISK_DRAWDOWN",
                    {
                        "drawdown": drawdown,
                        "threshold": self._drawdown_threshold,
                        "equity": equity,
                        "balance": balance,
                    },
                )
                with self._lock:
                    self._stats["drawdown_events"] += 1

        # Check exposure: margin / equity
        if equity > 0:
            exposure = margin / equity
            if exposure > self._exposure_threshold:
                self._emit_event(
                    "RISK_EXPOSURE",
                    {
                        "exposure": exposure,
                        "threshold": self._exposure_threshold,
                        "margin": margin,
                        "equity": equity,
                    },
                )
                with self._lock:
                    self._stats["exposure_events"] += 1

        # Check margin: margin_free / equity
        if equity > 0:
            margin_free_pct = margin_free / equity
            if margin_free_pct < self._margin_threshold:
                self._emit_event(
                    "RISK_MARGIN",
                    {
                        "margin_free_pct": margin_free_pct,
                        "threshold": self._margin_threshold,
                        "margin_free": margin_free,
                        "equity": equity,
                    },
                )
                with self._lock:
                    self._stats["margin_events"] += 1

    def _get_account_info(self) -> dict[str, Any]:
        """Read account info from MT5 (fail-safe, read-only)."""
        try:
            import MetaTrader5 as mt5

            if not mt5.initialize():
                return {}
            info = mt5.account_info()
            if info is None:
                return {}
            return {
                "equity": info.equity,
                "balance": info.balance,
                "margin": info.margin,
                "margin_free": info.margin_free,
            }
        except Exception as exc:  # noqa: BLE001 - MT5 import/init may fail
            logger.debug("MT5 account_info failed: %s", exc)
            return {}

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit risk event via callback (fail-safe)."""
        if self._on_emit is None:
            return
        try:
            self._on_emit(event_type, data)
        except Exception as exc:  # noqa: BLE001 - never break monitor loop
            logger.warning("Risk event emission failed for %s: %s", event_type, exc)
