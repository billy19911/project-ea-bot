# -*- coding: utf-8 -*-
"""FastAPI endpoints for live market news and economic calendar.

Provides REST API access to real-time news headlines (with deterministic
sentiment scoring) and economic calendar events fetched from public feeds.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from .news_feed import get_news_feed_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/news")
async def get_market_news(
    limit: int = Query(default=20, ge=1, le=100, description="Max headlines"),
    source: str = Query(default="all", description="Filter by source"),
) -> dict:
    """Return latest market news headlines with sentiment & impact scores."""
    provider = get_news_feed_provider()
    news = provider.fetch_news()

    if source.lower() != "all":
        news = [n for n in news if source.lower() in n.source.lower()]

    items = [n.to_dict() for n in news[:limit]]
    avg_sentiment = sum(n["sentiment"] for n in items) / len(items) if items else 0.0

    return {
        "status": "ok",
        "count": len(items),
        "avg_sentiment": round(avg_sentiment, 3),
        "news": items,
    }


@router.get("/calendar")
async def get_economic_calendar(
    currency: str = Query(default="USD", description="Filter by country"),
    impact: str = Query(default="all", description="Filter: all, High, Medium, Low"),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    """Return economic calendar events for the current week."""
    provider = get_news_feed_provider()
    events = provider.fetch_calendar()

    if currency.lower() != "all":
        events = [e for e in events if e.country.upper() == currency.upper()]

    if impact.lower() != "all":
        events = [e for e in events if e.impact.lower() == impact.lower()]

    items = [e.to_dict() for e in events[:limit]]

    return {
        "status": "ok",
        "count": len(items),
        "currency": currency,
        "events": items,
    }


@router.get("/health")
async def market_data_health(
    symbol: str = Query(default="XAUUSD", description="Symbol to check health")
) -> dict:
    """Return market data health for *symbol* (Phase 32)."""
    from .health import compute_market_data_health

    return compute_market_data_health(symbol)


@router.get("/symbol-spec")
async def get_symbol_spec_endpoint(
    symbol: str = Query(default="XAUUSD", description="Symbol to query"),
) -> dict:
    """Return the full broker SymbolSpec for *symbol* (Phase 33)."""
    from .symbol_spec import get_symbol_spec as _get_spec

    return _get_spec(symbol)


@router.get("/sentiment")
async def get_market_sentiment(
    symbol: str = Query(default="XAUUSD", description="Trading symbol"),
) -> dict:
    """Return current market sentiment summary for a symbol."""
    provider = get_news_feed_provider()
    context = provider.get_news_context(symbol=symbol)

    sentiment_data = context.get("sentiment", {})
    news_items = sentiment_data.get("news_items", [])
    events = sentiment_data.get("economic_events", [])

    avg_news_sentiment = (
        sum(n.get("sentiment", 0) for n in news_items) / len(news_items) if news_items else 0.0
    )

    high_impact_count = sum(
        1 for e in events if e.get("impact", "").upper() in ("HIGH", "CRITICAL")
    )

    if avg_news_sentiment > 0.15:
        signal = "BULLISH"
    elif avg_news_sentiment < -0.15:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    return {
        "status": "ok",
        "symbol": symbol,
        "signal": signal,
        "avg_sentiment": round(avg_news_sentiment, 3),
        "news_count": len(news_items),
        "events_count": len(events),
        "high_impact_events": high_impact_count,
        "updated_at": sentiment_data.get("updated_at", ""),
    }


@router.post("/refresh")
async def refresh_news_feed() -> dict:
    """Force-refresh all cached news and calendar data."""
    provider = get_news_feed_provider()
    news = provider.fetch_news(force_refresh=True)
    events = provider.fetch_calendar(force_refresh=True)
    return {
        "status": "ok",
        "news_count": len(news),
        "events_count": len(events),
        "message": "News feed refreshed",
    }


@router.get("/summary")
async def market_summary(symbol: str = Query(default="XAUUSD")) -> dict:
    """Return concise news summary for a symbol.
    Includes avg sentiment, high‑impact event count, and top positive/negative headlines.
    """
    provider = get_news_feed_provider()
    context = provider.get_news_context(symbol=symbol)
    sentiment_data = context.get("sentiment", {})
    news_items = sentiment_data.get("news_items", [])
    events = sentiment_data.get("economic_events", [])
    # avg sentiment
    avg_sentiment = (
        sum(item.get("sentiment", 0) for item in news_items) / len(news_items)
        if news_items
        else 0.0
    )
    # high impact events
    high_imp = sum(1 for e in events if e.get("impact", "").upper() in ("HIGH", "CRITICAL"))
    # top headlines
    positive = sorted(news_items, key=lambda x: x.get("sentiment", 0), reverse=True)[:3]
    negative = sorted(news_items, key=lambda x: x.get("sentiment", 0))[:3]
    return {
        "status": "ok",
        "symbol": symbol,
        "avg_sentiment": round(avg_sentiment, 3),
        "high_impact_events": high_imp,
        "top_positive": [item.get("headline") for item in positive],
        "top_negative": [item.get("headline") for item in negative],
    }


@router.get("/upcoming")
async def market_upcoming(
    currency: str = Query(default="USD", description="Currency filter (USD = US)"),
    limit: int = Query(default=15, ge=1, le=100),
) -> dict:
    """Return UPCOMING economic events (future only), soonest first.

    The news page uses this for the "akan datang" (upcoming) panel — filtered to
    USD/US by default. Events with an unparseable date are kept at the end so a
    bad feed never hides real upcoming data.
    """
    from datetime import datetime, timezone

    provider = get_news_feed_provider()
    events = provider.fetch_calendar()

    cur = currency.upper()
    if cur not in ("ALL", ""):
        events = [e for e in events if e.country.upper() == cur]

    now = datetime.now(timezone.utc)

    def _parse(ts: str):
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    upcoming = []
    for e in events:
        dt = _parse(e.date)
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= now:
            upcoming.append((dt, e))

    upcoming.sort(key=lambda pair: pair[0])
    items = []
    for dt, e in upcoming[:limit]:
        d = e.to_dict()
        d["datetime_utc"] = dt.astimezone(timezone.utc).isoformat()
        items.append(d)

    return {
        "status": "ok",
        "count": len(items),
        "currency": currency,
        "events": items,
    }


@router.get("/patterns")
async def market_news_patterns(
    event_key: str = Query(default="", description="Filter to one event key"),
    min_samples: int = Query(default=0, ge=0, le=1000),
) -> dict:
    """Return learned news patterns from historical outcomes (PRD §43/§54).

    Advisory: these inform the news agent's reasoning, never an order directly.
    """
    from .news_patterns import get_news_pattern_memory

    memory = get_news_pattern_memory()
    if min_samples:
        memory.min_samples = min_samples
    patterns = memory.patterns(event_key=event_key or None)
    return {
        "status": "ok",
        "count": len(patterns),
        "min_samples": memory.min_samples,
        "patterns": [p.to_dict() for p in patterns],
    }
