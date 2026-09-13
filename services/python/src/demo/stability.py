# -*- coding: utf-8 -*-
"""Stability monitoring for demo trading sessions.

Phase 20: Uptime tracking, error rate monitoring, and auto-reconnect.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class StabilityMonitor:
    """Monitors connection stability with uptime and error tracking.

    Tracks uptime, error rates, and provides auto-reconnect capability.
    """

    def __init__(
        self,
        connector: Any,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Initialize stability monitor.

        Args:
            connector: MT5 connector instance.
            clock: Optional time function for testing (returns seconds).
        """
        self.connector = connector
        self._clock = clock or (lambda: 0.0)
        self.started_at: float = 0.0
        self._checks: list[bool] = []
        self._errors: int = 0
        self._reconnects: int = 0

    def start(self) -> None:
        """Start stability monitoring."""
        self.started_at = self._clock() if self._clock else 0.0
        self._checks = []
        self._errors = 0
        logger.info("Stability monitoring started")

    def track_uptime(self) -> float:
        """Track uptime in seconds since monitoring started.

        Returns:
            Uptime in seconds.
        """
        if self.started_at == 0.0:
            return 0.0
        current = self._clock() if self._clock else 0.0
        return max(0.0, current - self.started_at)

    def check_error_rate(self) -> float:
        """Calculate error rate from recorded checks.

        Returns:
            Error rate as fraction (0.0 to 1.0).
        """
        if not self._checks:
            return 0.0
        failures = sum(1 for ok in self._checks if not ok)
        return failures / len(self._checks)

    def record_check(self, success: bool) -> None:
        """Record a health check result.

        Args:
            success: True if check passed.
        """
        self._checks.append(success)
        if not success:
            self._errors += 1

    def auto_reconnect(self) -> bool:
        """Attempt auto-reconnect if connection lost.

        Returns:
            True if reconnected or already connected.
        """
        health = self.connector.health_check()
        if getattr(health, "connected", False):
            return True

        logger.warning("Connection lost, attempting reconnect...")
        if hasattr(self.connector, "reconnect"):
            try:
                ok = self.connector.reconnect()
                if ok:
                    self._reconnects += 1
                    logger.info("Reconnect successful")
                    return True
            except Exception as exc:
                logger.error(f"Reconnect failed: {exc}")
                return False
        return False

    def get_stats(self) -> dict[str, Any]:
        """Get stability statistics.

        Returns:
            Dict with uptime, error rate, reconnect count.
        """
        return {
            "uptime_seconds": self.track_uptime(),
            "error_rate": self.check_error_rate(),
            "total_checks": len(self._checks),
            "errors": self._errors,
            "reconnects": self._reconnects,
        }
