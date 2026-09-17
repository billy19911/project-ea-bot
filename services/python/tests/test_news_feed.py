# -*- coding: utf-8 -*-
"""Tests for the real-time news feed provider (src/market/news_feed.py)."""

from __future__ import annotations

from typing import Any

from market.news_feed import (
    EconomicEventItem,
    NewsFeedProvider,
    get_news_feed_provider,
    score_headline_sentiment,
)


class FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, status_code: int = 200, json_data: Any = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._json = json_data
        self.content = content

    def json(self) -> Any:
        return self._json


class FakeClient:
    """Minimal httpx.Client stand-in that maps URLs to canned responses."""

    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.calls.append(url)
        if url not in self.responses:
            raise RuntimeError(f"unexpected URL: {url}")
        return self.responses[url]


def _rss_xml(items: list[tuple[str, str, str]]) -> bytes:
    """Build a minimal RSS document from (title, link, pubDate) tuples."""
    entries = "".join(
        f"<item><title>{title}</title><link>{link}</link>" f"<pubDate>{pub}</pubDate></item>"
        for title, link, pub in items
    )
    return f"<rss><channel>{entries}</channel></rss>".encode("utf-8")


# ---------------------------------------------------------------------------
# Sentiment scoring
# ---------------------------------------------------------------------------


class TestScoreHeadlineSentiment:
    def test_positive_headline(self) -> None:
        score, impact = score_headline_sentiment("Gold surges to record high on strong demand")
        assert score > 0

    def test_negative_headline(self) -> None:
        score, impact = score_headline_sentiment("Stocks plunge amid recession fears")
        assert score < 0

    def test_neutral_headline(self) -> None:
        score, impact = score_headline_sentiment("Markets open on Tuesday")
        assert score == 0.0

    def test_empty_headline(self) -> None:
        score, impact = score_headline_sentiment("")
        assert score == 0.0
        assert impact == "LOW"

    def test_critical_keyword_high_impact(self) -> None:
        score, impact = score_headline_sentiment("Fed rate hike fears spark selloff in bonds")
        assert impact in ("MEDIUM", "HIGH")

    def test_scores_are_bounded(self) -> None:
        for headline in (
            "surge rally gain bullish record",
            "slump plunge crash crisis fear war",
            "Gold rises as war escalates and inflation surges",
        ):
            score, _ = score_headline_sentiment(headline)
            assert -1.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Calendar fetching
# ---------------------------------------------------------------------------


class TestFetchCalendar:
    def test_parses_calendar_events(self) -> None:
        client = FakeClient(
            {
                "http://cal": FakeResponse(
                    json_data=[
                        {
                            "title": "Non-Farm Employment Change",
                            "country": "USD",
                            "date": "2026-09-18T12:30:00-04:00",
                            "impact": "High",
                            "forecast": "150K",
                            "previous": "142K",
                        },
                        {
                            "title": "German ZEW",
                            "country": "EUR",
                            "date": "2026-09-18T05:00:00-04:00",
                            "impact": "Medium",
                            "forecast": "",
                            "previous": "",
                        },
                    ]
                )
            }
        )
        provider = NewsFeedProvider(calendar_url="http://cal", client=client)
        events = provider.fetch_calendar()

        assert len(events) == 2
        assert events[0].title == "Non-Farm Employment Change"
        assert events[0].impact == "High"
        assert events[0].country == "USD"

    def test_unknown_impact_normalised_to_low(self) -> None:
        client = FakeClient(
            {
                "http://cal": FakeResponse(
                    json_data=[
                        {
                            "title": "X",
                            "country": "USD",
                            "date": "",
                            "impact": "Holiday",
                        }
                    ]
                )
            }
        )
        provider = NewsFeedProvider(calendar_url="http://cal", client=client)
        events = provider.fetch_calendar()
        assert events[0].impact == "Low"

    def test_caches_calendar(self) -> None:
        client = FakeClient({"http://cal": FakeResponse(json_data=[])})
        provider = NewsFeedProvider(calendar_url="http://cal", client=client)
        provider.fetch_calendar()
        provider.fetch_calendar()
        assert len(client.calls) == 1

    def test_force_refresh_bypasses_cache(self) -> None:
        client = FakeClient({"http://cal": FakeResponse(json_data=[])})
        provider = NewsFeedProvider(calendar_url="http://cal", client=client)
        provider.fetch_calendar()
        provider.fetch_calendar(force_refresh=True)
        assert len(client.calls) == 2

    def test_network_failure_returns_cache(self) -> None:
        class BrokenClient:
            def get(self, url: str) -> Any:
                raise RuntimeError("network down")

        provider = NewsFeedProvider(
            calendar_url="http://cal", client=BrokenClient()  # type: ignore[arg-type]
        )
        provider._cached_calendar = [
            EconomicEventItem(title="Cached", country="USD", date="", impact="High")
        ]
        provider._calendar_fetched_at = 0.0  # force staleness
        events = provider.fetch_calendar()
        assert len(events) == 1
        assert events[0].title == "Cached"

    def test_non_200_returns_cache(self) -> None:
        client = FakeClient({"http://cal": FakeResponse(status_code=503)})
        provider = NewsFeedProvider(calendar_url="http://cal", client=client)
        provider._cached_calendar = [
            EconomicEventItem(title="Cached", country="USD", date="", impact="High")
        ]
        provider._calendar_fetched_at = 0.0
        events = provider.fetch_calendar()
        assert len(events) == 1


# ---------------------------------------------------------------------------
# News fetching
# ---------------------------------------------------------------------------


class TestFetchNews:
    def test_parses_rss_feed(self) -> None:
        client = FakeClient(
            {
                "http://rss": FakeResponse(
                    content=_rss_xml(
                        [
                            ("Gold rallies on safe-haven demand", "http://a", "Mon"),
                            ("Dollar slumps after weak data", "http://b", "Tue"),
                        ]
                    )
                )
            }
        )
        provider = NewsFeedProvider(rss_urls=["http://rss"], client=client)
        news = provider.fetch_news()

        assert len(news) == 2
        assert news[0].sentiment > 0
        # "slumps" is in the negative lexicon.
        assert news[1].sentiment < 0

    def test_caches_news(self) -> None:
        client = FakeClient({"http://rss": FakeResponse(content=_rss_xml([("A", "", "")]))})
        provider = NewsFeedProvider(rss_urls=["http://rss"], client=client)
        provider.fetch_news()
        provider.fetch_news()
        assert len(client.calls) == 1

    def test_broken_feed_does_not_raise(self) -> None:
        client = FakeClient({"http://rss": FakeResponse(content=b"not xml")})
        provider = NewsFeedProvider(rss_urls=["http://rss"], client=client)
        news = provider.fetch_news()
        assert news == []

    def test_network_error_does_not_raise(self) -> None:
        class BrokenClient:
            def get(self, url: str) -> Any:
                raise RuntimeError("boom")

        provider = NewsFeedProvider(
            rss_urls=["http://rss"], client=BrokenClient()  # type: ignore[arg-type]
        )
        assert provider.fetch_news() == []

    def test_multiple_feeds_aggregated(self) -> None:
        client = FakeClient(
            {
                "http://a": FakeResponse(content=_rss_xml([("A", "", "")])),
                "http://b": FakeResponse(content=_rss_xml([("B", "", "")])),
            }
        )
        provider = NewsFeedProvider(rss_urls=["http://a", "http://b"], client=client)
        news = provider.fetch_news()
        assert len(news) == 2

    def test_skips_items_without_title(self) -> None:
        client = FakeClient(
            {"http://rss": FakeResponse(content=_rss_xml([("", "", ""), ("Ok", "", "")]))}
        )
        provider = NewsFeedProvider(rss_urls=["http://rss"], client=client)
        news = provider.fetch_news()
        assert len(news) == 1
        assert news[0].headline == "Ok"


# ---------------------------------------------------------------------------
# Pipeline context construction
# ---------------------------------------------------------------------------


class TestGetNewsContext:
    def test_returns_sentiment_wrapper(self) -> None:
        client = FakeClient(
            {
                "http://cal": FakeResponse(
                    json_data=[
                        {
                            "title": "NFP",
                            "country": "USD",
                            "date": "",
                            "impact": "High",
                            "forecast": "150K",
                            "previous": "142K",
                        },
                        {
                            "title": "EU CPI",
                            "country": "EUR",
                            "date": "",
                            "impact": "High",
                        },
                    ]
                ),
                "http://rss": FakeResponse(content=_rss_xml([("Gold rallies", "", "")])),
            }
        )
        provider = NewsFeedProvider(
            calendar_url="http://cal", rss_urls=["http://rss"], client=client
        )
        context = provider.get_news_context(symbol="XAUUSD", currency="USD")

        assert "sentiment" in context
        sentiment = context["sentiment"]
        assert sentiment["symbol"] == "XAUUSD"
        assert sentiment["currency"] == "USD"
        assert len(sentiment["news_items"]) == 1
        # Only the USD High-impact event is kept.
        assert len(sentiment["economic_events"]) == 1
        assert "NFP" in sentiment["economic_events"][0]["headline"]

    def test_context_consumed_by_news_agent(self) -> None:
        """The context must be directly consumable by NewsSentimentAgent."""
        from agents.analysts.news_agent import NewsSentimentAgent

        client = FakeClient(
            {
                "http://cal": FakeResponse(json_data=[]),
                "http://rss": FakeResponse(
                    content=_rss_xml(
                        [
                            ("Gold rallies strongly on dovish Fed", "", ""),
                            ("Gold gains as dollar weakens", "", ""),
                        ]
                    )
                ),
            }
        )
        provider = NewsFeedProvider(
            calendar_url="http://cal", rss_urls=["http://rss"], client=client
        )
        context = provider.get_news_context(symbol="XAUUSD")

        agent = NewsSentimentAgent()
        result = agent.analyze(context)

        # analyze() returns a dict with a "metrics" key.
        assert result["agent"] == "news_sentiment"
        assert result["metrics"]["news_count"] == 2
        # Positive gold headlines should yield a non-negative signal.
        assert result["signal"] in ("BULLISH", "NEUTRAL")

    def test_fail_closed_on_total_outage(self) -> None:
        class BrokenClient:
            def get(self, url: str) -> Any:
                raise RuntimeError("offline")

        provider = NewsFeedProvider(
            calendar_url="http://cal",
            rss_urls=["http://rss"],
            client=BrokenClient(),  # type: ignore[arg-type]
        )
        context = provider.get_news_context()
        assert context["sentiment"]["news_items"] == []
        assert context["sentiment"]["economic_events"] == []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_news_feed_provider_is_cached(self) -> None:
        import market.news_feed as mod

        mod._news_provider = None
        first = get_news_feed_provider()
        second = get_news_feed_provider()
        assert first is second
        mod._news_provider = None
