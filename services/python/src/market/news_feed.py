# -*- coding: utf-8 -*-
"""Real-time News and Economic Calendar Feed Provider.

Fetches real-time economic calendar and financial news headlines from public
feeds (ForexFactory calendar, Yahoo Finance RSS, CNBC RSS), performs
deterministic sentiment and impact scoring, and provides formatted context
for NewsSentimentAgent and API endpoints.

Fail-closed and resilient: network errors fall back to cache or empty data
without disrupting trading operations.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Default endpoints (free, public, no registration needed)
DEFAULT_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
DEFAULT_YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F,DX-Y.NYB"
DEFAULT_CNBC_FOREX_RSS = "https://www.cnbc.com/id/10000650/device/rss/rss.html"
DEFAULT_CNBC_ECONOMY_RSS = "https://www.cnbc.com/id/20910258/device/rss/rss.html"

# Cache TTL in seconds
CALENDAR_CACHE_TTL = 900.0  # 15 minutes
NEWS_CACHE_TTL = 300.0  # 5 minutes

# Timeout for HTTP requests
HTTP_TIMEOUT = 8.0

# User-Agent header to prevent 403 blocks
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36 EA-Bot/1.0"

# Financial Sentiment Lexicon (Deterministic Rule-Based)
POSITIVE_KEYWORDS = {
    "surge",
    "surges",
    "rally",
    "rallies",
    "gain",
    "gains",
    "jump",
    "jumps",
    "advance",
    "advances",
    "bullish",
    "high",
    "highs",
    "record",
    "growth",
    "strong",
    "strengthen",
    "strengthens",
    "outperform",
    "profit",
    "profits",
    "positive",
    "rebound",
    "rebounds",
    "recovery",
    "climb",
    "climbs",
    "soar",
    "soars",
    "boom",
    "booming",
    "stimulus",
    "dovish",
    "rate cut",
    "easing",
    "peace",
    "stabilize",
    "stabilizing",
    "optimism",
    "upgrade",
}

NEGATIVE_KEYWORDS = {
    "slump",
    "slumps",
    "drop",
    "drops",
    "fall",
    "falls",
    "plunge",
    "plunges",
    "bearish",
    "low",
    "lows",
    "decline",
    "declines",
    "weak",
    "weakens",
    "weakness",
    "loss",
    "losses",
    "negative",
    "crash",
    "crashes",
    "collapse",
    "risk",
    "warning",
    "warns",
    "crisis",
    "fear",
    "recession",
    "hawkish",
    "rate hike",
    "inflation",
    "tightening",
    "war",
    "conflict",
    "threat",
    "downgrade",
    "layoffs",
    "default",
    "trouble",
    "debt",
    "tariff",
    "tariffs",
    "tumble",
    "tumbles",
    "slide",
    "slides",
    "sink",
    "sinks",
    "selloff",
    "sell-off",
}

CRITICAL_EVENT_KEYWORDS = {
    "fed",
    "fomc",
    "interest rate",
    "nfp",
    "non-farm",
    "cpi",
    "inflation",
    "gdp",
    "powell",
    "unemployment rate",
    "war",
    "escalation",
}


@dataclass
class EconomicEventItem:
    """Standardized economic calendar event."""

    title: str
    country: str
    date: str
    impact: str  # "Low", "Medium", "High", "Critical"
    forecast: str = ""
    previous: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsHeadlineItem:
    """Standardized news headline item."""

    headline: str
    source: str
    link: str = ""
    published: str = ""
    sentiment: float = 0.0  # -1.0 to +1.0
    impact: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    category: str = "GENERAL"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_headline_sentiment(headline: str) -> tuple[float, str]:
    """Score headline sentiment and impact level deterministically.

    Returns:
        (sentiment_score between -1.0 and 1.0, impact_level str)
    """
    if not headline:
        return 0.0, "LOW"

    lower = headline.lower()

    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in lower)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in lower)

    total = pos_count + neg_count
    if total == 0:
        score = 0.0
    else:
        score = (pos_count - neg_count) / total

    # Impact assessment
    is_critical = any(kw in lower for kw in CRITICAL_EVENT_KEYWORDS)
    if is_critical and abs(score) >= 0.4:
        impact = "HIGH"
    elif is_critical:
        impact = "MEDIUM"
    elif abs(score) >= 0.5:
        impact = "MEDIUM"
    else:
        impact = "LOW"

    return round(score, 3), impact


class NewsFeedProvider:
    """Fetches, caches, and formats live news & economic calendar data."""

    def __init__(
        self,
        calendar_url: str = DEFAULT_CALENDAR_URL,
        rss_urls: Optional[list[str]] = None,
        calendar_ttl: float = CALENDAR_CACHE_TTL,
        news_ttl: float = NEWS_CACHE_TTL,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.calendar_url = calendar_url
        self.rss_urls = (
            rss_urls
            if rss_urls is not None
            else [DEFAULT_YAHOO_RSS, DEFAULT_CNBC_FOREX_RSS, DEFAULT_CNBC_ECONOMY_RSS]
        )
        self.calendar_ttl = calendar_ttl
        self.news_ttl = news_ttl

        self._client = client
        self._cached_calendar: list[EconomicEventItem] = []
        self._calendar_fetched_at: float = 0.0

        self._cached_news: list[NewsHeadlineItem] = []
        self._news_fetched_at: float = 0.0

    def _get_client(self) -> httpx.Client:
        """Return the HTTP client, creating one if not injected."""
        if self._client is not None:
            return self._client
        return httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def fetch_calendar(self, force_refresh: bool = False) -> list[EconomicEventItem]:
        """Fetch economic calendar events, returning cached data if fresh."""
        now = time.time()
        cache_fresh = (now - self._calendar_fetched_at) < self.calendar_ttl
        has_fetched = self._calendar_fetched_at > 0.0
        if not force_refresh and has_fetched and cache_fresh:
            return list(self._cached_calendar)

        try:
            client = self._get_client()
            resp = client.get(self.calendar_url)
            if resp.status_code == 200:
                raw_events = resp.json()
                parsed: list[EconomicEventItem] = []
                for ev in raw_events:
                    impact_raw = str(ev.get("impact", "Low")).capitalize()
                    if impact_raw not in ("Low", "Medium", "High"):
                        impact_raw = "Low"
                    parsed.append(
                        EconomicEventItem(
                            title=str(ev.get("title", "")),
                            country=str(ev.get("country", "")),
                            date=str(ev.get("date", "")),
                            impact=impact_raw,
                            forecast=str(ev.get("forecast", "")),
                            previous=str(ev.get("previous", "")),
                        )
                    )
                self._cached_calendar = parsed
                self._calendar_fetched_at = now
                logger.info("Fetched %d calendar events", len(parsed))
            else:
                logger.warning(
                    "Calendar feed status %d, using cache",
                    resp.status_code,
                )
        except Exception as exc:
            logger.warning("Calendar fetch failed: %s", exc)

        return list(self._cached_calendar)

    def fetch_news(self, force_refresh: bool = False) -> list[NewsHeadlineItem]:
        """Fetch news headlines from configured RSS feeds, using cache if fresh."""
        now = time.time()
        cache_fresh = (now - self._news_fetched_at) < self.news_ttl
        has_fetched = self._news_fetched_at > 0.0
        if not force_refresh and has_fetched and cache_fresh:
            return list(self._cached_news)

        all_news: list[NewsHeadlineItem] = []
        client = self._get_client()

        for url in self.rss_urls:
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.content)
                source_name = "Yahoo Finance" if "yahoo" in url else "CNBC"
                for item in root.findall(".//item"):
                    title_elem = item.find("title")
                    link_elem = item.find("link")
                    pub_elem = item.find("pubDate")

                    title = (
                        title_elem.text.strip()
                        if title_elem is not None and title_elem.text
                        else ""
                    )
                    if not title:
                        continue

                    link = (
                        link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                    )
                    pub = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else ""

                    sentiment, impact = score_headline_sentiment(title)

                    all_news.append(
                        NewsHeadlineItem(
                            headline=title,
                            source=source_name,
                            link=link,
                            published=pub,
                            sentiment=sentiment,
                            impact=impact,
                        )
                    )
            except Exception as exc:
                logger.warning("RSS parse failed %s: %s", url, exc)

        if all_news:
            self._cached_news = all_news
            self._news_fetched_at = now
            logger.info("Fetched %d news headlines", len(all_news))

        return list(self._cached_news)

    def get_news_context(
        self,
        symbol: str = "XAUUSD",
        currency: str = "USD",
        max_news: int = 15,
        max_events: int = 10,
    ) -> dict[str, Any]:
        """Construct a pipeline-ready context dict for NewsSentimentAgent.

        Filters events to the relevant currency (e.g. USD for Gold/XAUUSD),
        includes top headlines with deterministic sentiment scores, and wraps
        everything into ``{"sentiment": {...}}``.
        """
        news_items = self.fetch_news()
        calendar_events = self.fetch_calendar()

        # Filter relevant calendar events (e.g. USD and High/Medium impact)
        relevant_events = [
            ev
            for ev in calendar_events
            if ev.country.upper() == currency.upper() and ev.impact in ("High", "Medium")
        ][:max_events]

        formatted_news = [
            {
                "headline": item.headline,
                "sentiment": item.sentiment,
                "impact": item.impact,
                "category": item.category,
                "source": item.source,
            }
            for item in news_items[:max_news]
        ]

        formatted_events = [
            {
                "headline": f"{ev.country} {ev.title}",
                "impact": ev.impact.upper(),
                "sentiment": 0.0,
                "date": ev.date,
                "forecast": ev.forecast,
                "previous": ev.previous,
            }
            for ev in relevant_events
        ]

        return {
            "sentiment": {
                "news_items": formatted_news,
                "economic_events": formatted_events,
                "sentiment_override": 0.0,
                "symbol": symbol,
                "currency": currency,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        }


# Global singleton instance
_news_provider: Optional[NewsFeedProvider] = None


def get_news_feed_provider() -> NewsFeedProvider:
    """Return the global NewsFeedProvider singleton."""
    global _news_provider
    if _news_provider is None:
        _news_provider = NewsFeedProvider()
    return _news_provider
