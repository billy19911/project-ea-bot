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
* **Market evidence** — every emitted event carries the exact inputs behind
  it (close/high/low series, computed market state, the detected events,
  volatility inputs); the latest snapshot per symbol is cached so cycles that
  arrive without one (e.g. a manual run) are still analysed with real data.
* **Market session awareness** — before polling a symbol the loop asks
  :func:`market.sessions.get_market_session` whether the market is open. A
  closed market (weekend/holiday/off-session) is skipped entirely instead of
  analysing stale bars; crypto stays open 24/7. The check is fail-open: any
  error means "poll anyway".
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
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from trading.market_snapshot import set_latest_snapshot

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
        on_emit: Optional zero-arg callback invoked right after at least one
            event is routed. Used to WAKE the scheduler immediately so the
            signal → execution path is not delayed by the idle poll. Fail-safe:
            a raising callback is swallowed.
        session_max_age_s: Data older than this (seconds) means the market is
            closed; passed to :func:`market.sessions.get_market_session`.
        session_provider: Optional ``Callable[[str], dict]`` returning a
            session status for a symbol. Test seam; when ``None`` the
            production :func:`market.sessions.get_market_session` is used with
            ``connector=self._connector`` and ``max_age_s=self.session_max_age_s``.
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
        on_emit: Optional[Callable[[], None]] = None,
        session_max_age_s: float = 1800.0,
        session_provider: Optional[Callable[[str], dict]] = None,
        multi_timeframe_enabled: bool = False,
        multi_timeframe_list: str = "M15,H1,H4",
        multi_timeframe_min_strength: float = 0.0,
        fallback_symbols: Optional[list[str]] = None,
        identity: Optional[Any] = None,
    ) -> None:
        self.queue = queue
        self.symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        # FOKUS: primary vs fallback symbols. Primaries (e.g. XAUUSD) are always
        # polled when their market is open. Fallbacks (e.g. #BTCUSD) are polled
        # ONLY when every primary market is closed (weekend/holiday) — so crypto
        # is a weekend side-instrument, never a competitor to gold during the
        # trading week.
        self.fallback_symbols = [str(s).strip() for s in (fallback_symbols or []) if str(s).strip()]
        self._all_symbols = [*self.symbols, *self.fallback_symbols]
        self.timeframe = str(timeframe or "M5")
        self.interval_s = float(interval_s)
        self.count = int(count)
        self.event_cooldown_s = float(event_cooldown_s)
        self._history = history
        self._clock = clock if clock is not None else time.monotonic
        self._on_emit = on_emit
        self._connector = connector if connector is not None else self._default_connector()
        self.session_max_age_s = float(session_max_age_s)
        self._session_provider = session_provider
        self.multi_timeframe_enabled = bool(multi_timeframe_enabled)
        self.multi_timeframe_list = str(multi_timeframe_list or "M15,H1,H4")
        self.multi_timeframe_min_strength = float(multi_timeframe_min_strength)
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
        # TASK 05: runtime identity for duplicate-feed detection. A second
        # MarketFeedLoop in the same process would have a different
        # feed_instance_id; two processes differ by process_id.
        self.identity = identity
        if self.identity is not None:
            try:
                self.identity.register_feed(self)
            except Exception:  # noqa: BLE001 - identity must never break the feed
                pass

    @staticmethod
    def _default_connector() -> Any:
        """Return the production MT5 connector module (read-only data access)."""
        from ..mt5 import connector as mt5_connector

        return mt5_connector

    def _session_status(self, symbol: str) -> dict:
        """Return the market-session status for *symbol* (fail-open upstream).

        Uses the injected ``session_provider`` when present (test seam);
        otherwise the production :func:`market.sessions.get_market_session`
        with this loop's connector and ``session_max_age_s``.
        """
        if self._session_provider is not None:
            return self._session_provider(symbol)
        from ..market.sessions import get_market_session

        return get_market_session(
            symbol,
            connector=self._connector,
            max_age_s=self.session_max_age_s,
        )

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

        Ordering (primary vs fallback):
            Primary symbols are polled first. Fallback symbols (crypto) are
            polled ONLY when **no** primary market is currently open — i.e. a
            weekend/holiday. This keeps gold the main instrument during the
            trading week and uses crypto as a weekend side-instrument.
        """
        emitted = 0
        any_primary_open = False
        for symbol in self.symbols:
            session = self._safe_session(symbol)
            if session is not None and not session.get("open", True):
                logger.info(
                    "Market feed: %s market closed (%s) — skipping",
                    symbol,
                    session.get("reason"),
                )
                continue
            any_primary_open = True
            emitted += self._poll_symbol(symbol, session)

        # Fallbacks only when every primary market is closed.
        if self.fallback_symbols and not any_primary_open:
            logger.info(
                "Market feed: all primary markets closed — polling fallback symbols %s",
                ", ".join(self.fallback_symbols),
            )
            for symbol in self.fallback_symbols:
                emitted += self._poll_symbol(symbol, self._safe_session(symbol))
        return emitted

    def _safe_session(self, symbol: str) -> Optional[dict]:
        """Return the session status for *symbol*, or None (fail-open)."""
        try:
            return self._session_status(symbol)
        except Exception as exc:  # noqa: BLE001 — fail-open, never block on session check
            logger.debug("Market feed session check skipped: %s", exc)
            return None

    def _poll_symbol(self, symbol: str, session: Optional[dict] = None) -> int:
        """Poll one symbol; returns the number of events emitted (0 on skip).

        ``session`` may be pre-resolved by the caller (``poll_once``); when
        ``None`` it is resolved here. A closed market returns 0.
        """
        if session is None:
            session = self._safe_session(symbol)
        if session is not None and not session.get("open", True):
            logger.info(
                "Market feed: %s market closed (%s) — skipping",
                symbol,
                session.get("reason"),
            )
            return 0

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
        snapshot = self._build_snapshot(symbol, ohlcv, events)
        if session is not None:
            try:
                snapshot["session"] = session
            except Exception:  # noqa: BLE001 - session attach is best-effort
                logger.debug("Market feed could not attach session to snapshot for %s", symbol)
        try:
            set_latest_snapshot(symbol, snapshot)
        except Exception:  # noqa: BLE001 - the snapshot cache must never kill the loop
            logger.warning("Market feed snapshot cache update failed for %s", symbol)
        return self._route_events(symbol, events, snapshot)

    def _route_events(
        self,
        symbol: str,
        events: list[Any],
        snapshot: Optional[dict[str, Any]] = None,
    ) -> int:
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
            if snapshot:
                try:
                    event.market_snapshot = snapshot
                except Exception:  # noqa: BLE001 - evidence attach is best-effort
                    logger.warning("Market feed could not attach snapshot to %s", event_type)
            # TASK 02 trace metadata: stamp when the event was created, when the
            # feed polled, and the bar time so the scheduler trace shows the
            # exact wake cause (event creation → queue → wake). Best-effort.
            try:
                event_created_at = getattr(event, "timestamp", "") or ""
                if not getattr(event, "event_created_at", None):
                    event.event_created_at = event_created_at
                if not getattr(event, "feed_poll_time", None):
                    event.feed_poll_time = datetime.now(timezone.utc).isoformat()
                if not getattr(event, "bar_time", None):
                    # The detector stamps the event's own ``time`` from the last
                    # bar when available; otherwise leave it blank.
                    event.bar_time = str(getattr(event, "time", "") or "")
                if not getattr(event, "event_id", None):
                    event.event_id = f"evt_{symbol}_{event_type}_{int(now * 1000)}"
            except Exception:  # noqa: BLE001 - trace metadata is best-effort
                logger.debug("Market feed trace metadata skipped for %s", event_type)
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
        if routed and self._on_emit is not None:
            # Wake the consumer immediately so a fresh signal is processed
            # without waiting for the next idle poll (latency-sensitive entry).
            try:
                self._on_emit()
            except Exception:  # noqa: BLE001 - waking must never kill the loop
                logger.warning("Market feed on_emit callback failed")
        return routed

    def _build_snapshot(
        self,
        symbol: str,
        ohlcv: list[dict[str, Any]],
        events: list[Any],
    ) -> dict[str, Any]:
        """Build the market-evidence snapshot attached to every emitted event.

        Carries the exact inputs the analysis committee consumes: the
        close/high/low series, the computed market state (ADX/trend/ATR/BB
        width), the detected events themselves, and the volatility inputs —
        so specialists run on real evidence instead of an empty context.
        """
        closes = [float(bar.get("close", 0.0) or 0.0) for bar in ohlcv]
        highs = [float(bar.get("high", 0.0) or 0.0) for bar in ohlcv]
        lows = [float(bar.get("low", 0.0) or 0.0) for bar in ohlcv]
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1]
        ]
        state = self._states.get(symbol)
        snapshot: dict[str, Any] = {
            "symbol": symbol,
            "prices": closes,
            "highs": highs,
            "lows": lows,
            "market_state": state,
            "detected_events": list(events),
            "volatility": {
                "atr": float(getattr(state, "atr", 0.0) or 0.0),
                "price": float(getattr(state, "close", 0.0) or 0.0),
                "bollinger_width": float(getattr(state, "BB_width", 0.0) or 0.0),
                "high": float(getattr(state, "high", 0.0) or 0.0),
                "low": float(getattr(state, "low", 0.0) or 0.0),
                "returns": returns,
            },
        }
        # Multi-timeframe analysis (HTF bias + LTF entry). Opt-in; fail-safe so
        # a data hiccup never breaks the loop.
        if self.multi_timeframe_enabled:
            try:
                from ..market.multi_timeframe import build_timeframe_prices

                tfs = tuple(tf.strip() for tf in self.multi_timeframe_list.split(",") if tf.strip())
                mtf = build_timeframe_prices(
                    symbol,
                    connector=self._connector,
                    timeframes=tfs,
                )
                if mtf.get("timeframe_prices"):
                    snapshot["timeframe_prices"] = mtf["timeframe_prices"]
                if mtf.get("htf_bias") is not None:
                    snapshot["htf_bias"] = mtf["htf_bias"]
            except Exception as exc:  # noqa: BLE001 - evidence is best-effort
                logger.debug("Multi-TF analysis skipped for %s: %s", symbol, exc)
        return snapshot

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
            logger.info(
                "MarketFeedLoop started (process_id=%s feed_instance_id=%s)",
                getattr(self.identity, "process_id", None),
                getattr(self.identity, "feed_instance_id", None),
            )
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
