# -*- coding: utf-8 -*-
"""Trend sampler (UI/UX ide #8) — ring buffer of REAL samples.

The dashboard needs trends, but :class:`observability.metrics.MetricsRegistry`
is a *point-in-time* snapshot: it keeps no history. Rather than invent numbers
(a chart of fabricated zeros is the worst kind of slop), this sampler records
the values that genuinely move on this machine:

* **Account equity/balance/margin** from the attached MT5 terminal, read-only
  (``connector.get_account_info``). When live mode is OFF the connector returns
  a *simulated* paper account — that is test data, so the sampler records
  ``account: null`` instead of plotting a fake curve.
* **Scheduler counters** (``events_processed``, ``trades_blocked``, …) from the
  live ``AutonomousScheduler.stats()``.

Honesty rules
-------------
* A failed read is recorded as ``null`` for that section — never as ``0``.
  The UI draws gaps, not fake zeros.
* Each sample carries the ``login``/``server`` it came from, so after a
  terminal switch the chart shows only samples from the active account.
* The sampler never raises into its loop; a bad sample is logged and the next
  tick continues.

Interval is operator-tunable through the settings store
(``trend_sample_interval``), which pushes straight into ``TrendSampler.interval``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TrendSampler",
    "get_trend_sampler",
    "DEFAULT_INTERVAL_S",
    "MIN_INTERVAL_S",
    "MAX_INTERVAL_S",
    "DEFAULT_CAPACITY",
]

DEFAULT_INTERVAL_S = 15.0
MIN_INTERVAL_S = 2.0
MAX_INTERVAL_S = 300.0
# 240 samples @ 15s ≈ 1 hour of history.
DEFAULT_CAPACITY = 240


def _default_account_provider() -> Optional[dict[str, Any]]:
    """Read the REAL account snapshot (read-only) from the MT5 connector.

    Returns ``None`` when live mode is off: the connector would hand back a
    simulated paper account and plotting that as a trend would be fabrication.
    """
    from ..mt5 import connector

    if not connector.is_live_mode():
        return None
    info = connector.get_account_info()
    return {
        "login": info.login,
        "server": info.server,
        "equity": info.equity,
        "balance": info.balance,
        "margin": info.margin,
        "free_margin": info.free_margin,
        "margin_level": info.margin_level,
        "currency": info.currency,
    }


def _default_stats_provider() -> Optional[dict[str, Any]]:
    """Read live scheduler counters (lazy import to avoid an import cycle)."""
    from ..orchestration.runtime import get_runtime

    runtime = get_runtime()
    scheduler = getattr(runtime, "scheduler", None)
    if scheduler is None or not hasattr(scheduler, "stats"):
        return None
    return scheduler.stats()


class TrendSampler:
    """Append-only ring buffer of real samples, one per ``interval`` seconds.

    Args:
        account_provider: Callable returning an account dict or ``None``.
            Defaults to the live MT5 connector (read-only).
        stats_provider: Callable returning scheduler stats or ``None``.
        interval: Seconds between samples (clamped to the allowed range).
        capacity: Ring buffer size; oldest samples are evicted first.
    """

    def __init__(
        self,
        account_provider: Optional[Callable[[], Optional[dict[str, Any]]]] = None,
        stats_provider: Optional[Callable[[], Optional[dict[str, Any]]]] = None,
        interval: float = DEFAULT_INTERVAL_S,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        self._account_provider = account_provider or _default_account_provider
        self._stats_provider = stats_provider or _default_stats_provider
        self._interval = self._clamp_interval(interval)
        self._capacity = max(2, int(capacity))
        self._samples: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._running = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp_interval(value: float) -> float:
        return min(MAX_INTERVAL_S, max(MIN_INTERVAL_S, float(value)))

    @property
    def interval(self) -> float:
        return self._interval

    @interval.setter
    def interval(self, value: float) -> None:
        self._interval = self._clamp_interval(value)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    def sample_once(self) -> dict[str, Any]:
        """Record one sample from the real providers.

        Each section is read independently: an account failure does not lose
        the scheduler counters, and vice versa. Failed sections are stored as
        ``None`` so the UI can draw a gap instead of a fabricated zero.
        """
        account: Optional[dict[str, Any]] = None
        try:
            account = self._account_provider()
        except Exception as exc:  # noqa: BLE001 - one bad read must not kill the loop
            logger.warning("TrendSampler: account read failed: %s", exc)

        stats: Optional[dict[str, Any]] = None
        try:
            stats = self._stats_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TrendSampler: stats read failed: %s", exc)

        now = time.time()
        sample: dict[str, Any] = {
            "ts": now,
            "t": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "account": account,
            "stats": stats,
        }
        with self._lock:
            self._samples.append(sample)
            overflow = len(self._samples) - self._capacity
            if overflow > 0:
                del self._samples[:overflow]
        return sample

    def history(self, limit: int = 0) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent samples (oldest first)."""
        with self._lock:
            if limit and limit > 0:
                return list(self._samples[-limit:])
            return list(self._samples)

    # ------------------------------------------------------------------
    # Async lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Start the background sampling loop (non-blocking)."""
        if self._running:
            return
        self._running = True
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "TrendSampler started (interval=%ss, capacity=%s)", self._interval, self._capacity
        )

    async def stop(self) -> None:
        """Stop the loop and await the task."""
        if not self._running:
            return
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._task
        self._task = None
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:  # pragma: no cover - defensive
                pass

    async def _run_loop(self) -> None:
        """Sample immediately, then once per interval until stopped."""
        while self._running:
            try:
                self.sample_once()
            except Exception:  # pragma: no cover - sample_once already guards
                logger.exception("TrendSampler: unexpected sampling error")
            stop = self._stop_event
            if stop is None:  # pragma: no cover - defensive
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue


_default_sampler: Optional[TrendSampler] = None


def get_trend_sampler() -> TrendSampler:
    """Return the process-wide sampler singleton."""
    global _default_sampler
    if _default_sampler is None:
        _default_sampler = TrendSampler()
    return _default_sampler
