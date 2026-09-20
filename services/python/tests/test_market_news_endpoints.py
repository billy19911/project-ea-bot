# -*- coding: utf-8 -*-
"""Tests for the /market news endpoints (summary + list).

Network is never touched: the global NewsFeedProvider is replaced with a
deterministic stub before the app is exercised through TestClient.
"""

from __future__ import annotations

import pytest  # noqa: F401
from fastapi.testclient import TestClient

from market.news_feed import EconomicEventItem, NewsHeadlineItem
from src.main import app
from src.market import endpoints as market_endpoints

client = TestClient(app)


class _StubProvider:
    """Deterministic stand-in for NewsFeedProvider (no network)."""

    def fetch_news(self, force_refresh: bool = False) -> list[NewsHeadlineItem]:
        return [
            NewsHeadlineItem(
                headline="Gold surges to record high",
                source="Yahoo Finance",
                sentiment=1.0,
                impact="HIGH",
            ),
            NewsHeadlineItem(
                headline="Dollar slumps on weak data",
                source="CNBC",
                sentiment=-1.0,
                impact="MEDIUM",
            ),
            NewsHeadlineItem(
                headline="Markets steady ahead of Fed",
                source="CNBC",
                sentiment=0.0,
                impact="LOW",
            ),
        ]

    def fetch_calendar(self, force_refresh: bool = False) -> list[EconomicEventItem]:
        return [
            EconomicEventItem(
                title="Non-Farm Payrolls",
                country="USD",
                date="2026-09-25",
                impact="High",
            )
        ]

    def get_news_context(self, symbol: str = "XAUUSD", **_: object) -> dict:
        news = self.fetch_news()
        return {
            "sentiment": {
                "news_items": [
                    {
                        "headline": n.headline,
                        "sentiment": n.sentiment,
                        "impact": n.impact,
                        "category": n.category,
                        "source": n.source,
                    }
                    for n in news
                ],
                "economic_events": [
                    {
                        "headline": "USD Non-Farm Payrolls",
                        "impact": "HIGH",
                        "sentiment": 0.0,
                        "date": "2026-09-25",
                    }
                ],
                "symbol": symbol,
            }
        }


def _install_stub() -> None:
    """Replace the provider accessor used by the market endpoints.

    The endpoints call ``get_news_feed_provider()`` at request time; swapping
    the function object on the module keeps the tests network-free without
    touching the real singleton.
    """
    stub = _StubProvider()
    market_endpoints.get_news_feed_provider = lambda: stub  # type: ignore[assignment]


def test_market_summary_returns_key_points() -> None:
    _install_stub()
    res = client.get("/market/summary?symbol=XAUUSD")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["symbol"] == "XAUUSD"
    assert body["high_impact_events"] == 1
    assert "Gold surges to record high" in body["top_positive"][0]
    assert "Dollar slumps on weak data" in body["top_negative"][0]


def test_market_news_list_endpoint() -> None:
    _install_stub()
    res = client.get("/market/news")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["count"] == 3


def test_market_news_source_filter() -> None:
    _install_stub()
    res = client.get("/market/news?source=CNBC")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    assert all("CNBC" in n["source"] for n in body["news"])
