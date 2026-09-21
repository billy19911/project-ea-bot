# -*- coding: utf-8 -*-
"""Tests for the latency + news-resilience improvements.

* News: fallback source + anti-rate-limit (throttle, 429 cooldown, disk cache).
* AccountContextProvider: short-TTL cache so a burst of events does not re-read
  MT5 + news per event.
* Scheduler: event-driven wake-up (no fixed poll delay before processing).
"""

from __future__ import annotations

import asyncio
import time

from market.news_feed import CALENDAR_RATE_LIMIT_COOLDOWN, NewsFeedProvider
from orchestration.account_context import AccountContextProvider
from trading.event_engine import EventQueue
from trading.scheduler import AutonomousScheduler


# ---------------------------------------------------------------------------
# News resilience
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status_code=200, json_data=None, headers=None, content=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else []
        self.headers = headers or {}
        self.content = content if content is not None else b"[]"

    def json(self):
        return self._json


class _Client:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(url)
        resp = self.mapping.get(url)
        if resp is None:
            raise RuntimeError(f"no mapping for {url}")
        return resp


def test_calendar_falls_back_when_primary_fails():
    """Primary non-200 → the fallback source is tried and used."""
    primary = "http://primary"
    fallback = "http://fallback"
    client = _Client(
        {
            primary: _Resp(status_code=503),
            fallback: _Resp(json_data=[{"title": "NFP", "country": "USD", "impact": "High"}]),
        }
    )
    provider = NewsFeedProvider(
        calendar_url=primary, fallback_calendar_urls=[fallback], client=client
    )
    events = provider.fetch_calendar()
    assert len(events) == 1
    assert events[0].title == "NFP"
    assert client.calls == [primary, fallback]


def test_calendar_xml_fallback():
    """Primary JSON failing → the XML mirror fallback is parsed and used."""
    xml = (
        b"<weeklyevents><event><title>NFP</title><country>USD</country>"
        b"<date>2026-09-25</date><impact>High</impact><forecast>150K</forecast>"
        b"<previous>140K</previous></event></weeklyevents>"
    )
    client = _Client(
        {
            "http://json": _Resp(status_code=503, content=b""),
            "http://xml": _Resp(json_data=[], content=xml, headers={"content-type": "text/xml"}),
        }
    )
    provider = NewsFeedProvider(
        calendar_url="http://json", fallback_calendar_urls=["http://xml"], client=client
    )
    events = provider.fetch_calendar(force_refresh=True)
    assert len(events) == 1
    assert events[0].title == "NFP"
    assert events[0].impact == "High"
    assert client.calls == ["http://json", "http://xml"]


def test_calendar_fed_fallback_parsed():
    """The Federal Reserve fallback (a different schema/host) is normalised."""
    fed = [
        {
            "title": "Speech - Chair Test",
            "month": "2026-09",
            "days": "23",
            "time": "10:05 a.m.",
            "type": "Speeches",
        },
        {"title": "Housing Summit", "month": "2026-09", "days": "24", "type": "Speeches"},
    ]
    client = _Client(
        {
            "http://cal": _Resp(status_code=429, headers={"Retry-After": "60"}),
            "http://fed": _Resp(json_data={"events": fed}),
        }
    )
    provider = NewsFeedProvider(
        calendar_url="http://cal", fallback_calendar_urls=["http://fed"], client=client
    )
    events = provider.fetch_calendar(force_refresh=True)
    assert len(events) == 2
    assert events[0].title == "Speech - Chair Test"
    assert events[0].date == "2026-09-23"
    assert client.calls == ["http://cal", "http://fed"]


def test_calendar_429_sets_cooldown_and_stops_hammering():
    """A 429 sets a cooldown; a later automated fetch does not re-hit the host.

    Fallbacks are still tried (an independent host may serve), but the
    rate-limited PRIMARY must not be re-requested within the cooldown.
    """
    client = _Client({"http://cal": _Resp(status_code=429, headers={"Retry-After": "120"})})
    provider = NewsFeedProvider(calendar_url="http://cal", fallback_calendar_urls=[], client=client)

    provider.fetch_calendar(force_refresh=True)
    assert client.calls.count("http://cal") == 1
    assert provider._calendar_429_until > time.time()

    # A later (non-force_network) fetch must respect the 429 cooldown entirely.
    provider.fetch_calendar(force_refresh=True)
    assert client.calls.count("http://cal") == 1, "should not hammer a rate-limited host"


def test_calendar_uses_default_cooldown_without_retry_after():
    client = _Client({"http://cal": _Resp(status_code=429)})
    provider = NewsFeedProvider(calendar_url="http://cal", fallback_calendar_urls=[], client=client)
    provider.fetch_calendar(force_refresh=True)
    remaining = provider._calendar_429_until - time.time()
    # Should be close to the default cooldown (allow a small scheduling margin).
    assert CALENDAR_RATE_LIMIT_COOLDOWN - 5 <= remaining <= CALENDAR_RATE_LIMIT_COOLDOWN


def test_disk_cache_roundtrip(tmp_path):
    """Last-good data is persisted and reloaded (survives restart/rate-limit)."""
    path = str(tmp_path / "news_cache.json")
    client = _Client({"http://cal": _Resp(json_data=[{"title": "CPI", "country": "USD"}])})
    writer = NewsFeedProvider(
        calendar_url="http://cal", client=client, cache_path=path, use_disk_cache=True
    )
    writer.fetch_calendar()
    assert len(writer._cached_calendar) == 1

    # A fresh provider (no network) loads the persisted events.
    reader = NewsFeedProvider(
        calendar_url="http://cal",
        client=_Client({}),
        cache_path=path,
        use_disk_cache=True,
    )
    assert len(reader._cached_calendar) == 1
    assert reader._cached_calendar[0].title == "CPI"


def test_disk_cache_disabled_by_default(tmp_path):
    """A default instance must NOT read a persisted cache (test isolation)."""
    path = str(tmp_path / "news_cache.json")
    client = _Client({"http://cal": _Resp(json_data=[{"title": "GDP", "country": "USD"}])})
    NewsFeedProvider(
        calendar_url="http://cal", client=client, cache_path=path, use_disk_cache=True
    ).fetch_calendar()

    # Default (use_disk_cache=False) starts cold even though the file exists.
    provider = NewsFeedProvider(calendar_url="http://cal", client=_Client({}), cache_path=path)
    assert provider._cached_calendar == []


# ---------------------------------------------------------------------------
# Context provider caching
# ---------------------------------------------------------------------------
def test_context_provider_caches_within_ttl():
    """The account/news provider is only invoked once within the TTL."""
    calls = {"n": 0}

    def account_provider(symbol):
        calls["n"] += 1
        return {"account_state": {"equity": 10000.0}}

    provider = AccountContextProvider(account_provider=account_provider, cache_ttl=60.0)
    for _ in range(5):
        ctx = provider(type("E", (), {"symbol": "XAUUSD"})())
    assert calls["n"] == 1, "burst should hit the provider once"
    assert ctx["account_state"]["equity"] == 10000.0


def test_context_provider_recomputes_after_ttl():
    calls = {"n": 0}

    def account_provider(symbol):
        calls["n"] += 1
        return {}

    now = {"t": 1000.0}
    provider = AccountContextProvider(
        account_provider=account_provider, cache_ttl=2.0, clock=lambda: now["t"]
    )
    event = type("E", (), {"symbol": "XAUUSD"})()
    provider(event)
    now["t"] += 3.0  # exceed TTL
    provider(event)
    assert calls["n"] == 2


def test_context_provider_returns_copies():
    """Callers may mutate the returned context without poisoning the cache."""
    provider = AccountContextProvider(account_provider=lambda s: {"a": 1}, cache_ttl=60.0)
    event = type("E", (), {"symbol": "XAUUSD"})()
    ctx = provider(event)
    ctx["a"] = 999
    assert provider(event)["a"] == 1


# ---------------------------------------------------------------------------
# Scheduler wake-up
# ---------------------------------------------------------------------------
class _RecordingPipeline:
    def __init__(self):
        self.ran = 0

    def run(self, event, context=None):
        self.ran += 1
        return type("R", (), {"status": "WAIT", "decision": "WAIT", "error": None})()


def test_scheduler_wake_processes_immediately():
    """wake() causes the loop to drain the queue without the poll delay."""
    queue = EventQueue()

    class _Evt:
        event_type = "TREND_BULLISH"
        symbol = "XAUUSD"

    async def scenario():
        pipeline = _RecordingPipeline()
        sched = AutonomousScheduler(queue=queue, pipeline=pipeline, poll_interval=30.0)
        await sched.start()
        # Let the loop settle into its idle sleep.
        await asyncio.sleep(0.05)
        queue.enqueue(_Evt())
        sched.wake()
        # Should process within a fraction of a second, well under poll_interval.
        for _ in range(50):
            if pipeline.ran >= 1:
                break
            await asyncio.sleep(0.02)
        await sched.stop()
        return pipeline.ran

    ran = asyncio.get_event_loop().run_until_complete(scenario())
    assert ran >= 1, "wake() must trigger immediate processing"


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
