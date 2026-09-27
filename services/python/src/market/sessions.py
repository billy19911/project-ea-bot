# -*- coding: utf-8 -*-
"""Market session awareness — detect closed/holiday markets + crypto 24/7.

The feed loop polls MT5 symbols on a fixed schedule, but many instruments are
*not* tradable 24/7: FX/metals close on weekends and holidays, indices have
session hours. Without a session check the loop keeps analysing stale bars
(e.g. Friday's close) as if they were fresh — producing bogus analysis/signals.

This module answers a single question, read-only and fail-open:

    "Is *symbol*'s market open right now?"

Strategy (deliberately data-driven — NO hardcoded session hours, timezones,
DST rules or holiday tables, which are brittle and broker-specific):

* **Crypto** (BTC, ETH, …) trades 24/7 — always open. A stale crypto *feed* is
  a feed problem, not a closed market, so we never hide it as "closed".
* **Everything else** — compare the freshest available evidence (last M5 bar
  time and last tick time) against ``max_age_s``. If either source is fresh the
  market is considered open (a single stale source must not fake a closure).
* Any error / missing data / inconclusive evidence => **open** (fail-open): the
  loop must never be blocked because a session probe failed.

Never imports execution/order code.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["classify_symbol", "get_market_session"]

# Known crypto *base* tokens. A symbol whose normalised base contains any of
# these is treated as crypto. Kept lowercase for case-insensitive matching.
_CRYPTO_TOKENS: tuple[str, ...] = (
    "BTC",
    "ETH",
    "XRP",
    "SOL",
    "ADA",
    "DOGE",
    "LTC",
    "BCH",
    "DOT",
    "AVAX",
    "LINK",
    "MATIC",
    "TRX",
    "XLM",
    "ATOM",
    "NEO",
    "EOS",
    "XTZ",
    "ETC",
    "FIL",
    "SHIB",
    "PEPE",
    "BNB",
)


def _normalise(symbol: str) -> str:
    """Strip broker prefixes/suffixes and non-alphanumerics; uppercase.

    ``#BTCUSD`` → ``BTCUSD``; ``BTCUSD.pro`` → ``BTCUSDPRO``; ``XAU/USD`` →
    ``XAUUSD``.
    """
    raw = str(symbol or "").upper()
    return "".join(ch for ch in raw if ch.isalnum())


def classify_symbol(symbol: str) -> str:
    """Return ``"crypto"`` or ``"non_crypto"`` (asset-class guess).

    Normalises the symbol then checks whether the *base* begins with a known
    crypto token (``BTCUSD``, ``#ETHUSD``, ``ETHBTC``, …). Matching the base
    only — not any substring — avoids false positives such as ``#FirstSolar``
    (``FIRSTSOLAR`` contains ``SOL`` but is an equity).

    Returning ``"non_crypto"`` for anything unknown is the safe default (it
    still gets the age check).
    """
    normalised = _normalise(symbol)
    if not normalised:
        return "non_crypto"
    for token in _CRYPTO_TOKENS:
        if normalised.startswith(token):
            return "crypto"
    return "non_crypto"


def _as_utc(value: Any) -> Optional[datetime]:
    """Coerce a bar/tick time into an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        # Naive datetimes are treated as UTC.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_seconds(value: Any, now: datetime) -> Optional[float]:
    """Return the age of *value* in seconds relative to *now*, or None."""
    dt = _as_utc(value)
    if dt is None:
        return None
    return (now - dt).total_seconds()


def _bar_time(bar: Any) -> Any:
    """Extract the ``time`` attribute/key from a bar (object or dict)."""
    if isinstance(bar, dict):
        return bar.get("time")
    return getattr(bar, "time", None)


def _build_result(
    symbol: str,
    asset_class: str,
    is_open: bool,
    reason: str,
    bar_age_s: Optional[float],
    tick_age_s: Optional[float],
    now: datetime,
) -> dict:
    """Assemble the public result dict."""
    return {
        "symbol": symbol,
        "asset_class": asset_class,
        "open": is_open,
        "reason": reason,
        "bar_age_s": bar_age_s,
        "tick_age_s": tick_age_s,
        "checked_at": now.astimezone(timezone.utc).isoformat(),
    }


def get_market_session(
    symbol: str,
    connector: Any = None,
    max_age_s: float = 1800.0,
    now: Optional[datetime] = None,
) -> dict:
    """Return live market-session status for *symbol*.

    Args:
        symbol: Symbol to check (broker prefix/suffix tolerated).
        connector: Object exposing ``get_ohlc(symbol, tf, count)`` and
            ``get_tick(symbol)``. Defaults to the production
            :mod:`mt5.connector` module (read-only).
        max_age_s: Data older than this (seconds) means the market is closed.
        now: Injectable "current time" (tests); defaults to aware UTC now.

    Returns:
        ``{"symbol", "asset_class", "open", "reason", "bar_age_s",
        "tick_age_s", "checked_at"}``.

    Never raises — any failure returns ``open=True`` (fail-open).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    asset_class = classify_symbol(symbol)

    # Crypto trades 24/7 — always open, regardless of data age.
    if asset_class == "crypto":
        return _build_result(
            symbol,
            asset_class,
            True,
            "crypto trades 24/7",
            None,
            None,
            now,
        )

    try:
        if connector is None:
            from ..mt5 import connector as connector  # noqa: PLC0415

        bar_age_s: Optional[float] = None
        tick_age_s: Optional[float] = None

        # A connector that cannot provide a tick (e.g. a bare ``get_ohlc``-only
        # stub) cannot yield a reliable session verdict; probing it would also
        # consume an OHLC call. Treat as inconclusive (fail-open) and skip.
        if not callable(getattr(connector, "get_tick", None)):
            return _build_result(
                symbol,
                asset_class,
                True,
                "session check inconclusive (fail-open)",
                bar_age_s,
                tick_age_s,
                now,
            )

        bars = connector.get_ohlc(symbol, "M5", 2)
        if bars:
            bar_age_s = _age_seconds(_bar_time(bars[-1]), now)

        tick = connector.get_tick(symbol)
        if tick is not None:
            tick_age_s = _age_seconds(getattr(tick, "time", None), now)

        ages = [age for age in (bar_age_s, tick_age_s) if age is not None]
        if not ages:
            return _build_result(
                symbol,
                asset_class,
                True,
                "session check inconclusive (fail-open)",
                bar_age_s,
                tick_age_s,
                now,
            )

        age = min(ages)
        is_open = age <= float(max_age_s)
        if is_open:
            reason = f"market open (last data {age:.0f}s old)"
        else:
            reason = f"market closed (last data {age:.0f}s old > {max_age_s:.0f}s)"
        return _build_result(symbol, asset_class, is_open, reason, bar_age_s, tick_age_s, now)
    except Exception as exc:  # noqa: BLE001 - fail-open, never block the caller
        logger.debug("Market session check failed for %s: %s", symbol, exc)
        return _build_result(
            symbol,
            asset_class,
            True,
            "session check failed (fail-open)",
            None,
            None,
            now,
        )
