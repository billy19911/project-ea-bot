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

import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Default endpoints (free, public, no registration needed).
# The calendar has PRIMARY + FALLBACK sources so a single host being
# rate-limited/blocked never empties the page.
DEFAULT_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
DEFAULT_CALENDAR_FALLBACK_URLS = (
    # XML mirror of the SAME dataset (a genuinely separate resource that often
    # survives when the JSON path 429s).
    "https://nfs.faireconomy.media/ff_calendar_thisweek.xml",
    # INDEPENDENT host (Federal Reserve) — used when the faireconomy host is
    # rate-limiting us. Its schema differs (``{"events": [...]}`` with
    # month/days/time) and is normalised by ``_parse_fed_calendar``.
    "https://www.federalreserve.gov/json/calendar.json",
)
DEFAULT_YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F,DX-Y.NYB"
DEFAULT_CNBC_FOREX_RSS = "https://www.cnbc.com/id/10000650/device/rss/rss.html"
DEFAULT_CNBC_ECONOMY_RSS = "https://www.cnbc.com/id/20910258/device/rss/rss.html"

# Cache TTL in seconds.
# The calendar TTL is intentionally long (the weekly calendar changes rarely) —
# this is the PRIMARY anti-rate-limit defence: we fetch at most once per window.
CALENDAR_CACHE_TTL = 3600.0  # 60 minutes (was 15m — fewer requests → no 429)
NEWS_CACHE_TTL = 600.0  # 10 minutes (was 5m)

# Minimum wall-clock gap between real network fetches, regardless of force_refresh.
# Prevents request storms (e.g. several UI tabs) from tripping the host's limiter.
CALENDAR_MIN_FETCH_INTERVAL = 300.0  # 5 minutes
NEWS_MIN_FETCH_INTERVAL = 120.0  # 2 minutes

# After a 429 we refuse to hit the host again for this long (honours Retry-After
# when the server provides a longer value).
CALENDAR_RATE_LIMIT_COOLDOWN = 900.0  # 15 minutes

# On-disk cache so a restart / long rate-limit window still has data.
DEFAULT_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
    "news_cache.json",
)

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
        fallback_calendar_urls: Optional[list[str]] = None,
        cache_path: Optional[str] = None,
        calendar_min_interval: float = CALENDAR_MIN_FETCH_INTERVAL,
        news_min_interval: float = NEWS_MIN_FETCH_INTERVAL,
        rate_limit_cooldown: float = CALENDAR_RATE_LIMIT_COOLDOWN,
        use_disk_cache: bool = False,
    ) -> None:
        self.calendar_url = calendar_url
        self.fallback_calendar_urls = (
            list(fallback_calendar_urls)
            if fallback_calendar_urls is not None
            else list(DEFAULT_CALENDAR_FALLBACK_URLS)
        )
        self.rss_urls = (
            rss_urls
            if rss_urls is not None
            else [DEFAULT_YAHOO_RSS, DEFAULT_CNBC_FOREX_RSS, DEFAULT_CNBC_ECONOMY_RSS]
        )
        self.calendar_ttl = calendar_ttl
        self.news_ttl = news_ttl
        self.calendar_min_interval = calendar_min_interval
        self.news_min_interval = news_min_interval
        self.rate_limit_cooldown = rate_limit_cooldown
        self.cache_path = cache_path if cache_path is not None else DEFAULT_CACHE_PATH
        # Disk cache is OPT-IN: only the long-lived production singleton enables
        # it. Short-lived instances (tests, ad-hoc callers) start cold so a
        # persisted file never leaks data into a fresh provider.
        self.use_disk_cache = bool(use_disk_cache)

        self._client = client
        self._cached_calendar: list[EconomicEventItem] = []
        self._calendar_fetched_at: float = 0.0

        self._cached_news: list[NewsHeadlineItem] = []
        self._news_fetched_at: float = 0.0

        # Anti-rate-limit bookkeeping.
        self._calendar_next_allowed_at: float = 0.0  # earliest time we may fetch again
        self._calendar_429_until: float = 0.0  # cooldown after a 429

        # Warm the cache from disk so a restart / rate-limit window still has data.
        if self.use_disk_cache:
            self._load_disk_cache()

    def _get_client(self) -> httpx.Client:
        """Return the HTTP client, creating one if not injected."""
        if self._client is not None:
            return self._client
        return httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def fetch_calendar(
        self, force_refresh: bool = False, force_network: bool = False
    ) -> list[EconomicEventItem]:
        """Fetch economic calendar events, returning cached data if fresh.

        Anti-rate-limit behaviour:
        * long TTL → at most one network fetch per window;
        * a minimum gap between fetches even when ``force_refresh=True``;
        * a cooldown after a 429 (honouring ``Retry-After``);
        * a fallback source tried only when the primary fails;
        * last-good data persisted to disk so restarts never show empty.

        ``force_refresh`` bypasses the freshness/min-interval throttle (explicit
        caller intent). ``force_network`` additionally bypasses the 429 cooldown
        and must only be used for an **operator-initiated** refresh (e.g. the
        dashboard's Refresh button) — never for automated polling.
        """
        now = time.time()
        cache_fresh = (now - self._calendar_fetched_at) < self.calendar_ttl
        has_fetched = self._calendar_fetched_at > 0.0
        # Serve cache when fresh, or when we are inside a rate-limit cooldown.
        # An explicit force_refresh bypasses the freshness check (and the
        # min-interval throttle) but NOT the 429 cooldown — hammering a host
        # that just rate-limited us would only make it worse. An explicit
        # operator force_network clears the cooldown.
        in_cooldown = now < self._calendar_429_until
        if in_cooldown and not force_network:
            return list(self._cached_calendar)
        if not force_refresh and not force_network and has_fetched and cache_fresh:
            return list(self._cached_calendar)
        if not force_refresh and not force_network and now < self._calendar_next_allowed_at:
            return list(self._cached_calendar)

        urls = [self.calendar_url] + [
            u for u in self.fallback_calendar_urls if u and u != self.calendar_url
        ]
        client = self._get_client()
        for url in urls:
            try:
                resp = client.get(url)
            except Exception as exc:  # noqa: BLE001 - try the next source
                logger.warning("Calendar fetch failed (%s): %s", url, exc)
                continue

            if resp.status_code == 200:
                parsed = self._parse_calendar_response(resp)
                # A valid 200 is authoritative (even if empty): record the fetch
                # time so we do not re-hit the host within the throttle window,
                # and do NOT fall through to other sources. Fallbacks are only
                # for a source that genuinely failed (non-200 / exception).
                self._calendar_next_allowed_at = now + self.calendar_min_interval
                if parsed:
                    self._cached_calendar = parsed
                    self._calendar_fetched_at = now
                    self._save_disk_cache()
                    logger.info("Fetched %d calendar events", len(parsed))
                else:
                    # Empty payload: keep serving the last good data if any.
                    self._calendar_fetched_at = now
                return list(self._cached_calendar)

            if resp.status_code == 429:
                cooldown = self._retry_after_seconds(resp)
                self._calendar_429_until = now + cooldown
                logger.warning("Calendar feed rate-limited (429) at %s; trying next source", url)
                # Do NOT stop: an independent host may still serve us. The
                # cooldown still applies to the throttled host on the next call.
                continue

            logger.warning(
                "Calendar feed status %d (%s), trying next source", resp.status_code, url
            )

        return list(self._cached_calendar)

    @staticmethod
    def _parse_calendar(raw_events: Any) -> list[EconomicEventItem]:
        """Normalise a raw calendar payload (list of dicts) into items."""
        parsed: list[EconomicEventItem] = []
        if not isinstance(raw_events, list):
            return parsed
        for ev in raw_events:
            if not isinstance(ev, dict):
                continue
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
        return parsed

    def _parse_calendar_response(self, resp: httpx.Response) -> list[EconomicEventItem]:
        """Parse a calendar response that may be JSON (list) or XML (weeklyevents).

        The primary endpoint returns JSON; the fallback returns the ForexFactory
        XML. Both encode the same fields (title/country/date/impact/...).
        """
        content_type = (getattr(resp, "headers", {}) or {}).get("content-type", "") or ""
        content_type = str(content_type).lower()
        body = getattr(resp, "content", b"") or b""
        looks_xml = "xml" in content_type or (isinstance(body, bytes) and body.lstrip()[:1] == b"<")
        if looks_xml:
            return self._parse_calendar_xml(body)
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - malformed JSON → no events
            logger.warning("Calendar JSON parse failed: %s", exc)
            return []
        # Fed calendar shape: {"events": [{"title", "month", "days", "time", ...}]}
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return self._parse_fed_calendar(data["events"])
        # ForexFactory JSON shape: a bare list of event dicts.
        return self._parse_calendar(data)

    @staticmethod
    def _parse_fed_calendar(events: list[Any]) -> list[EconomicEventItem]:
        """Normalise the Federal Reserve calendar (``{"events": [...]}``).

        The Fed feed lists speeches/events with ``month`` (YYYY-MM),
        ``days`` (day-of-month), ``time`` and ``type`` rather than the
        ForexFactory fields. Only events carrying a title are kept; impact is
        derived from the ``type`` (Speeches/Conferences are informational).
        """
        parsed: list[EconomicEventItem] = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            title = str(ev.get("title") or ev.get("description") or "").strip()
            if not title:
                continue
            month = str(ev.get("month") or "").strip()  # "2026-09"
            days = str(ev.get("days") or "").strip()  # "23"
            date = ""
            if month and days:
                try:
                    date = f"{month}-{int(days):02d}"
                except (TypeError, ValueError):
                    date = f"{month}-{days}"
            ev_type = str(ev.get("type") or "").strip()
            impact = "High" if "speech" in ev_type.lower() and "chair" in title.lower() else "Low"
            parsed.append(
                EconomicEventItem(
                    title=title,
                    country="USD",
                    date=date,
                    impact=impact,
                    forecast="",
                    previous="",
                )
            )
        return parsed

    @staticmethod
    def _parse_calendar_xml(body: bytes) -> list[EconomicEventItem]:
        """Parse the ForexFactory ``weeklyevents`` XML into items (best-effort)."""
        parsed: list[EconomicEventItem] = []
        try:
            root = ET.fromstring(body)
        except Exception as exc:  # noqa: BLE001 - malformed XML → no events
            logger.warning("Calendar XML parse failed: %s", exc)
            return parsed

        for ev in root.iter("event"):
            title = (ev.findtext("title") or "").strip()
            if not title:
                continue
            impact_raw = (ev.findtext("impact") or "Low").strip().capitalize()
            if impact_raw not in ("Low", "Medium", "High"):
                impact_raw = "Low"
            parsed.append(
                EconomicEventItem(
                    title=title,
                    country=(ev.findtext("country") or "").strip(),
                    date=(ev.findtext("date") or "").strip(),
                    impact=impact_raw,
                    forecast=(ev.findtext("forecast") or "").strip(),
                    previous=(ev.findtext("previous") or "").strip(),
                )
            )
        return parsed

    @staticmethod
    def _retry_after_seconds(resp: httpx.Response) -> float:
        """Return the cooldown to honour after a 429 (Retry-After or default)."""
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except (TypeError, ValueError):
                pass
        return CALENDAR_RATE_LIMIT_COOLDOWN

    def _save_disk_cache(self) -> None:
        """Persist the last-good calendar + news to disk (best-effort)."""
        if not self.use_disk_cache:
            return
        try:
            payload = {
                "calendar": [e.to_dict() for e in self._cached_calendar],
                "news": [n.to_dict() for n in self._cached_news],
                "saved_at": time.time(),
            }
            directory = os.path.dirname(self.cache_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except Exception as exc:  # noqa: BLE001 - cache must never break the feed
            logger.debug("Could not persist news cache: %s", exc)

    def _load_disk_cache(self) -> None:
        """Warm the in-memory cache from the on-disk cache (best-effort)."""
        try:
            if not self.cache_path or not os.path.exists(self.cache_path):
                return
            with open(self.cache_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            for ev in payload.get("calendar", []):
                if isinstance(ev, dict) and ev.get("title"):
                    self._cached_calendar.append(
                        EconomicEventItem(
                            title=str(ev.get("title", "")),
                            country=str(ev.get("country", "")),
                            date=str(ev.get("date", "")),
                            impact=str(ev.get("impact", "Low")),
                            forecast=str(ev.get("forecast", "")),
                            previous=str(ev.get("previous", "")),
                        )
                    )
            for n in payload.get("news", []):
                if isinstance(n, dict) and n.get("headline"):
                    self._cached_news.append(
                        NewsHeadlineItem(
                            headline=str(n.get("headline", "")),
                            source=str(n.get("source", "")),
                            link=str(n.get("link", "")),
                            published=str(n.get("published", "")),
                            sentiment=float(n.get("sentiment", 0.0) or 0.0),
                            impact=str(n.get("impact", "LOW")),
                            category=str(n.get("category", "GENERAL")),
                        )
                    )
            # Seed the fetch timestamp so the (stale) disk cache is served
            # immediately and refreshed on the normal schedule, not on boot.
            if self._cached_calendar or self._cached_news:
                self._calendar_fetched_at = float(payload.get("saved_at", 0.0) or 0.0)
                self._news_fetched_at = float(payload.get("saved_at", 0.0) or 0.0)
                logger.info(
                    "Loaded %d calendar / %d news items from disk cache",
                    len(self._cached_calendar),
                    len(self._cached_news),
                )
        except Exception as exc:  # noqa: BLE001 - a bad cache file must be ignored
            logger.warning("Could not load news cache: %s", exc)

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
            self._save_disk_cache()
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
    """Return the global NewsFeedProvider singleton.

    The singleton opts into the on-disk cache so calendar/news survive a restart
    or an upstream rate-limit window.
    """
    global _news_provider
    if _news_provider is None:
        _news_provider = NewsFeedProvider(use_disk_cache=True)
    return _news_provider
