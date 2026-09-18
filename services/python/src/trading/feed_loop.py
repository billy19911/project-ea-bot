# -*- coding: utf-8 -*-
"""MarketFeedLoop — autonomous MT5 → event → queue feed (Phase 6).

This loop is the *only* component that reads MT5 OHLC on a schedule and turns
it into market events for the autonomous pipeline:

    MT5 (read-only) → OHLC bars → EventDetector → EventQueue → scheduler

Design rules:

* **Read-only** — it calls ``get_ohlc`` only; it can never place an order and
  does not import any execution/order module (guard test enforces this).
* **Fail-safe** — a connector or detector failure skips that symbol/cycle with
  a warning; the loop itself never dies.
* **Dedup by data fingerprint** — identical bars (same length, last bar time
  and close) are skipped, so a quiet market does not flood the queue with the
  same event every interval.
* **Emit cooldown** — the same ``(symbol, event_type)`` pair is not emitted
  again within ``event_cooldown_s`` (default 300s), so a moving market cannot
  flood the pipeline (and the user's Telegram) with the same analysis every
  poll.
* **OFF by default** — the lifespan starts this loop only when
  ``MARKET_FEED_ENABLED=true`` (operator opt-in).

This loop owns event routing: detected events are enqueued into the shared
``EventQueue`` (and optional ``EventHistory``) by the loop itself, after the
cooldown filter — so the cooldown and the fingerprint dedup are the single
place that decides what enters the pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from .event_engine import EventHistory, EventQueue
from .events import EventDetector

logger = logging.getLogger(__name__)

__all__ = ["MarketFeedLoop"]


class MarketFeedLoop:
    """Poll MT5 OHLC (read-only) → detect events → enqueue. Fail-safe.

    Args:
        queue: Production :class:`EventQueue` (the one the scheduler drains).
        symbols: Symbols to poll (e.g. ``["XAUUSD"]``).
        timeframe: MT5 timeframe string (``M1``/``M5``/``H1``/…).
        interval_s: Seconds between polls.
        count: Bars fetched per poll.
        connector: Object exposing ``get_ohlc(symbol, timeframe, count)``.
            Defaults to the production :mod:`mt5.connector` module (read-only).
        history: Optional :class:`EventHistory` for emitted events.
        detector_factory: Optional factory returning a detector exposing
            ``detect(ohlcv, prev_state)`` / ``update_state(ohlcv, prev_state)``.
            Defaults to a production :class:`EventDetector`. Routing (queue +
            history) is owned by this loop, so the detector only detects.
        event_cooldown_s: Seconds before the same ``(symbol, event_type)`` may
            be emitted again (anti-spam; default 300s).
        clock: Optional monotonic clock callable (tests inject a fake).
    """

    def __init__(
        self,
        queue: EventQueue,
        symbols: list[str],
        timeframe: str = "M5",
        interval_s: float = 60.0,
        count: int = 200,
        connector: Any = None,
        history: Optional[EventHistory] = None,
        detector_factory: Optional[Callable[[], Any]] = None,
        event_cooldown_s: float = 300.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.queue = queue
        self.symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        self.timeframe = str(timeframe or "M5")
        self.interval_s = float(interval_s)
        self.count = int(count)
        self.event_cooldown_s = float(event_cooldown_s)
        self._history = history
        self._clock = clock if clock is not None else time.monotonic
        self._connector = connector if connector is not None else self._default_connector()
        if detector_factory is not None:
            self._detector = detector_factory()
        else:
            # Routing lives in this loop (cooldown + fingerprint), so the
            # detector is built without its own queue/history.
            self._detector = EventDetector()
        self._fingerprints: dict[str, tuple] = {}
        self._states: dict[str, Any] = {}
        self._last_emitted: dict[tuple[str, str], float] = {}
        self._running = False

    @staticmethod
    def _default_connector() -> Any:
        """Return the production MT5 connector module (read-only data access)."""
        from ..mt5 import connector as mt5_connector

        return mt5_connector

    @property
    def running(self) -> bool:
        """Return True while the async loop is active."""
        return self._running

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    def poll_once(self) -> int:
        """Run one poll cycle: read → detect → enqueue.

        Returns:
            The number of detected events emitted this cycle. Zero on any
            read/detection failure (fail-safe) — never raises.
        """
        emitted = 0
        for symbol in self.symbols:
            emitted += self._poll_symbol(symbol)
        return emitted

    def _poll_symbol(self, symbol: str) -> int:
        """Poll one symbol; returns the number of events emitted (0 on skip)."""
        try:
            bars = self._connector.get_ohlc(symbol, self.timeframe, self.count)
        except Exception as exc:  # noqa: BLE001 - MT5 must never kill the loop
            logger.warning("Market feed read failed for %s: %s", symbol, exc)
            return 0
        if not bars:
            return 0

        try:
            ohlcv = [self._bar_to_dict(bar) for bar in bars]
        except Exception as exc:  # noqa: BLE001 - malformed bars are skipped
            logger.warning("Market feed bar conversion failed for %s: %s", symbol, exc)
            return 0

        fingerprint = self._fingerprint(ohlcv)
        if self._fingerprints.get(symbol) == fingerprint:
            return 0  # identical data → nothing new to detect

        try:
            events = self._detector.detect(ohlcv, self._states.get(symbol))
            self._states[symbol] = self._detector.update_state(ohlcv, self._states.get(symbol))
        except Exception as exc:  # noqa: BLE001 - detection must never kill the loop
            logger.warning("Market feed detection failed for %s: %s", symbol, exc)
            return 0

        self._fingerprints[symbol] = fingerprint
        return self._route_events(symbol, events)

    def _route_events(self, symbol: str, events: list[Any]) -> int:
        """Enqueue cooldown-filtered events; returns the number routed.

        A moving market re-detects the same regime every poll; without a
        cooldown that would re-run the pipeline (and re-message the user) every
        interval. The cooldown suppresses repeats per ``(symbol, event_type)``.

        The cooldown stamp is only written when the event actually entered the
        queue: a full queue (``enqueue`` → False) must not silently swallow an
        event *and* suppress it for the whole cooldown window — it is skipped
        now and may be emitted on the next poll once the queue drains.
        """
        now = self._clock()
        routed = 0
        for event in events:
            event_type = str(getattr(event, "event_type", "") or "")
            key = (symbol, event_type)
            last = self._last_emitted.get(key)
            if last is not None and (now - last) < self.event_cooldown_s:
                continue
            if not self.queue.enqueue(event):
                logger.warning(
                    "Market feed queue full; dropping %s %s this cycle",
                    symbol,
                    event_type,
                )
                continue
            self._last_emitted[key] = now
            if self._history is not None:
                try:
                    self._history.add(event)
                except Exception:  # noqa: BLE001 - history must never kill the loop
                    logger.warning("Market feed history add failed for %s", symbol)
            routed += 1
        return routed

    @staticmethod
    def _bar_to_dict(bar: Any) -> dict[str, Any]:
        """Normalise one OHLC bar (object or dict) to the detector's dict shape."""
        if isinstance(bar, dict):
            data = dict(bar)
        else:
            data = {
                "symbol": getattr(bar, "symbol", ""),
                "open": float(getattr(bar, "open", 0.0) or 0.0),
                "high": float(getattr(bar, "high", 0.0) or 0.0),
                "low": float(getattr(bar, "low", 0.0) or 0.0),
                "close": float(getattr(bar, "close", 0.0) or 0.0),
                "volume": float(getattr(bar, "volume", 0.0) or 0.0),
                "time": str(getattr(bar, "time", "")),
            }
        data.setdefault("symbol", "")
        return data

    @staticmethod
    def _fingerprint(ohlcv: list[dict[str, Any]]) -> tuple:
        """Return a cheap identity of the series (length, last time, last close)."""
        last = ohlcv[-1]
        return (len(ohlcv), str(last.get("time", "")), last.get("close"))

    # ------------------------------------------------------------------
    # Async lifecycle
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """Poll every ``interval_s`` until :meth:`stop` is called.

        Fail-safe: poll errors are logged and the loop continues. Cancellation
        propagates cleanly (no swallowed ``CancelledError``).

        ``poll_once`` does blocking MT5 IPC (``copy_rates_from_pos``) which can
        stall for seconds on a live terminal; running it on the event-loop
        thread would freeze every FastAPI endpoint. We offload it to a worker
        thread (``asyncio.to_thread``) so the loop stays responsive.
        """
        self._running = True
        try:
            while self._running:
                try:
                    await asyncio.to_thread(self.poll_once)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - belt and braces
                    logger.warning("Market feed poll failed: %s", exc)
                await asyncio.sleep(self.interval_s)
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False

    def stop(self) -> None:
        """Request the loop to stop after the current sleep/poll."""
        self._running = False
