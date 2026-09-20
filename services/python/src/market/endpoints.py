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
