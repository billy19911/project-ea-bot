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
        try:
            from ..mt5 import connector  # local import: keep MT5 out of agent imports
        except ImportError:
            # Some entrypoints import this module top-level (``src/`` directly
            # on ``sys.path``, e.g. the test suite) where ``..mt5`` escapes the
            # package; fall back to the flat name so the connector stays
            # reachable. The outer handler still degrades to ``{}`` on failure.
            from mt5 import connector

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
            specs: dict[str, dict[str, Any]] = {}
            for pos in raw_positions:
                p = _to_dict(pos)
                if p:
                    symbol = str(p.get("symbol") or "")
                    try:
                        size = float(p.get("size", p.get("quantity", p.get("volume", 0.0))) or 0.0)
                        current_price = float(
                            p.get(
                                "current_price",
                                p.get(
                                    "price_current", p.get("entry_price", p.get("price_open", 0.0))
                                ),
                            )
                            or 0.0
                        )
                    except (TypeError, ValueError):
                        p["_notional_valid"] = False
                        positions.append(p)
                        continue

                    p["size"] = size
                    p["current_price"] = current_price
                    if "contract_size" not in p and symbol:
                        if symbol not in specs:
                            try:
                                specs[symbol] = _to_dict(connector.get_symbol_info(symbol))
                            except Exception as exc:  # noqa: BLE001 - missing spec blocks exposure
                                logger.debug("Position symbol spec read failed: %s", exc)
                                specs[symbol] = {}
                        try:
                            contract_size = float(specs[symbol].get("contract_size") or 0.0)
                        except (TypeError, ValueError):
                            contract_size = 0.0
                        if contract_size > 0:
                            p["contract_size"] = contract_size
                    try:
                        contract_size = float(p.get("contract_size") or 0.0)
                    except (TypeError, ValueError):
                        contract_size = 0.0
                    if size > 0 and current_price > 0 and contract_size > 0:
                        p["notional_value"] = size * current_price * contract_size
                        p["_notional_valid"] = True
                    else:
                        p["_notional_valid"] = False
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
                        spread_price = abs(ask - bid)
                        market_info["spread_price"] = spread_price
                        # Pip size = point * 10 (standard FX convention). The
                        # symbol spec supplies the point; without a spec fall
                        # back to a 5-digit FX point so the gate ALWAYS gets a
                        # numeric spread_pips (its max-spread check used to
                        # read a key nobody populated — dead code).
                        point = 0.0
                        contract_size = 0.0
                        tick_size = 0.0
                        tick_value = 0.0
                        volume_step = 0.0
                        volume_min = 0.0
                        volume_max = 0.0
                        try:
                            spec = _to_dict(connector.get_symbol_info(symbol))
                            point = float(spec.get("point", 0.0) or 0.0)
                            contract_size = float(spec.get("contract_size", 0.0) or 0.0)
                            tick_size = float(spec.get("tick_size", 0.0) or 0.0)
                            tick_value = float(spec.get("tick_value", 0.0) or 0.0)
                            volume_step = float(spec.get("volume_step", 0.0) or 0.0)
                            volume_min = float(spec.get("volume_min", 0.0) or 0.0)
                            volume_max = float(spec.get("volume_max", 0.0) or 0.0)
                        except Exception as exc:  # noqa: BLE001 - spec is best-effort
                            logger.debug("Symbol spec read failed: %s", exc)
                        if point <= 0:
                            point = 0.00001
                        if tick_size <= 0:
                            tick_size = point
                        pip_size = point * 10.0
                        market_info["point_value"] = point
                        market_info["tick_size"] = tick_size
                        market_info["tick_value"] = tick_value
                        market_info["spread_points"] = spread_price / point
                        market_info["spread_ticks"] = spread_price / tick_size
                        market_info["spread_atr"] = None
                        if volume_step > 0:
                            market_info["volume_step"] = volume_step
                        if volume_min > 0:
                            market_info["volume_min"] = volume_min
                        if volume_max > 0:
                            market_info["volume_max"] = volume_max
                        if contract_size > 0:
                            market_info["contract_size"] = contract_size
                            market_info["spread_cost_per_lot"] = (
                                spread_price / tick_size * tick_value
                                if tick_value > 0
                                else spread_price * contract_size
                            )
                        market_info["spread_pips"] = (
                            spread_price / pip_size if pip_size > 0 else 0.0
                        )
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
