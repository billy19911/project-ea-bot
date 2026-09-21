# -*- coding: utf-8 -*-
"""Account / market context provider for the autonomous pipeline (audit P1-3).

The scheduler's ``context_provider`` previously supplied only news context, so
the deterministic Risk Gate ran against the pipeline's *zeroed* fallback account
state. This provider assembles the real inputs the gate needs — account state,
open positions and market info (spread) — from the read-only MT5 connector and
merges them with the news context.

Design guarantees:

* **Read-only & fail-safe** — every field is read from ``mt5.connector``
  (``get_account_info``/``get_positions``/``get_tick``); any failure degrades to
  the news-only context so the autonomous loop never breaks.
* **Honest** — when the connector is unavailable the account/positions/market
  keys are omitted (the pipeline keeps its conservative zero fallback) rather
  than fabricating numbers.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["AccountContextProvider", "build_connector_account_context"]

# Default short TTL for the merged context. The account/positions/spread and the
# news snapshot change slowly relative to event processing; caching it for a few
# seconds means a burst of events does NOT re-read MT5 + the news feed per event
# (which measured ~0.6s each). This keeps signal → execution latency low.
DEFAULT_CONTEXT_TTL = 2.0


def _to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort dict conversion for pydantic models / objects."""
    if isinstance(obj, dict):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump())
        except Exception:  # noqa: BLE001 - malformed model
            return {}
    return {}


def build_connector_account_context(symbol: str = "") -> dict[str, Any]:
    """Assemble account/positions/market context from the read-only connector.

    Returns a dict with any of the keys ``account_state``, ``current_positions``
    and ``market_info`` that could be read. Missing keys are simply omitted.
    Never raises.
    """
    context: dict[str, Any] = {}
    try:
        from ..mt5 import connector  # local import: keep MT5 out of agent imports

        # ── Account state ────────────────────────────────────────────────
        try:
            account = _to_dict(connector.get_account_info())
            if account:
                context["account_state"] = {
                    "equity": float(account.get("equity", 0.0) or 0.0),
                    "balance": float(account.get("balance", 0.0) or 0.0),
                    "peak_equity": float(
                        account.get("equity", 0.0) or 0.0
                    ),  # best-effort; no peak source
                    "daily_pnl": 0.0,
                    "used_margin": float(
                        account.get("margin", account.get("used_margin", 0.0)) or 0.0
                    ),
                    "free_margin": float(account.get("free_margin", 0.0) or 0.0),
                    "margin_level": float(account.get("margin_level", 0.0) or 0.0),
                }
        except Exception as exc:  # noqa: BLE001 - account read is best-effort
            logger.debug("Account context read failed: %s", exc)

        # ── Open positions ───────────────────────────────────────────────
        try:
            raw_positions = connector.get_positions() or []
            positions: list[dict[str, Any]] = []
            for pos in raw_positions:
                p = _to_dict(pos)
                if p:
                    positions.append(p)
            context["current_positions"] = positions
        except Exception as exc:  # noqa: BLE001 - positions read is best-effort
            logger.debug("Positions context read failed: %s", exc)

        # ── Market info (spread) ─────────────────────────────────────────
        if symbol:
            try:
                tick = connector.get_tick(symbol)
                tick_d = _to_dict(tick)
                if tick_d:
                    bid = float(tick_d.get("bid", 0.0) or 0.0)
                    ask = float(tick_d.get("ask", 0.0) or 0.0)
                    market_info: dict[str, Any] = {"bid": bid, "ask": ask}
                    if bid > 0:
                        # spread in "pips" ≈ (ask - bid) / point; point unknown
                        # here, so report the raw price delta and keep the gate's
                        # default when it cannot be derived confidently.
                        market_info["spread_price"] = abs(ask - bid)
                    context["market_info"] = market_info
            except Exception as exc:  # noqa: BLE001 - tick read is best-effort
                logger.debug("Market context read failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 - connector import/wiring failure
        logger.debug("Connector unavailable for account context: %s", exc)
    return context


class AccountContextProvider:
    """Scheduler context provider merging account data with news context.

    Args:
        news_provider: Callable returning a news-context dict for a symbol.
        account_provider: Callable returning the account/positions/market dict.
            Defaults to :func:`build_connector_account_context`.
    """

    def __init__(
        self,
        news_provider: Optional[Callable[[str], dict[str, Any]]] = None,
        account_provider: Optional[Callable[[str], dict[str, Any]]] = None,
        cache_ttl: float = DEFAULT_CONTEXT_TTL,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._news_provider = news_provider
        self._account_provider = account_provider or build_connector_account_context
        self._cache_ttl = max(0.0, float(cache_ttl))
        self._clock = clock if clock is not None else time.monotonic
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def __call__(self, event: Any) -> dict[str, Any]:
        """Build the merged context for one event (fail-safe, never raises).

        Results are cached per symbol for ``cache_ttl`` seconds so a burst of
        events within one feed poll does not re-read MT5 + news each time. The
        returned dict is a shallow copy so callers may mutate it safely.
        """
        symbol = str(getattr(event, "symbol", "") or "")
        now = self._clock()
        cached = self._cache.get(symbol)
        if cached is not None and (now - cached[0]) < self._cache_ttl:
            return dict(cached[1])

        context = self._build(symbol)
        self._cache[symbol] = (now, context)
        return dict(context)

    def _build(self, symbol: str) -> dict[str, Any]:
        """Assemble the context without caching (never raises)."""
        context: dict[str, Any] = {}

        # Account/positions/market first (deterministic risk inputs).
        try:
            context.update(self._account_provider(symbol) or {})
        except Exception as exc:  # noqa: BLE001 - never break the cycle
            logger.warning("Account context provider failed: %s", exc)

        # News context (advisory analysis inputs).
        if self._news_provider is not None:
            try:
                news = self._news_provider(symbol or "XAUUSD")
                if isinstance(news, dict):
                    context.update(news)
            except Exception as exc:  # noqa: BLE001 - never break the cycle
                logger.warning("News context provider failed: %s", exc)

        return context
