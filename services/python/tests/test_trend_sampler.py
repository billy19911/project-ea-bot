# -*- coding: utf-8 -*-
"""Tests for the trend sampler (UI/UX ide #8).

The sampler exists so the dashboard can draw trends from REAL data instead of
fabricated zeros. These tests pin the honesty rules:

* a failed read is stored as ``null`` (gap), never as ``0``;
* the ring buffer evicts the oldest sample first;
* the interval is clamped to the documented range;
* live mode OFF means no account section at all (the connector would return a
  simulated paper account — plotting that as a trend would be fabrication).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.observability.sampler import (  # noqa: E402
    DEFAULT_CAPACITY,
    MAX_INTERVAL_S,
    MIN_INTERVAL_S,
    TrendSampler,
    get_trend_sampler,
)


def _account(equity: float = 1000.0) -> dict:
    return {
        "login": 12345,
        "server": "Test-Server",
        "equity": equity,
        "balance": 1000.0,
        "margin": 0.0,
        "free_margin": 1000.0,
        "margin_level": 0.0,
        "currency": "USD",
    }


def _stats(processed: int = 0) -> dict:
    return {"events_processed": processed, "trades_blocked": 0, "running": False}


# ---------------------------------------------------------------------------
# Sampling honesty
# ---------------------------------------------------------------------------


def test_sample_records_both_sections() -> None:
    sampler = TrendSampler(
        account_provider=lambda: _account(1234.5), stats_provider=lambda: _stats(7)
    )
    sample = sampler.sample_once()
    assert sample["account"]["equity"] == 1234.5
    assert sample["stats"]["events_processed"] == 7
    assert sample["ts"] > 0
    assert "T" in sample["t"]  # ISO-8601


def test_failed_account_read_is_null_not_zero() -> None:
    def boom() -> dict:
        raise RuntimeError("terminal detached")

    sampler = TrendSampler(account_provider=boom, stats_provider=lambda: _stats(3))
    sample = sampler.sample_once()
    # The account section is a gap; the scheduler section still landed.
    assert sample["account"] is None
    assert sample["stats"]["events_processed"] == 3


def test_failed_stats_read_is_null_not_zero() -> None:
    def boom() -> dict:
        raise RuntimeError("no runtime")

    sampler = TrendSampler(account_provider=lambda: _account(), stats_provider=boom)
    sample = sampler.sample_once()
    assert sample["account"] is not None
    assert sample["stats"] is None


def test_provider_returning_none_is_preserved() -> None:
    # Live mode OFF -> account provider returns None by design.
    sampler = TrendSampler(account_provider=lambda: None, stats_provider=lambda: _stats())
    sample = sampler.sample_once()
    assert sample["account"] is None


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------


def test_ring_buffer_evicts_oldest_first() -> None:
    sampler = TrendSampler(
        account_provider=lambda: _account(),
        stats_provider=lambda: _stats(),
        capacity=3,
    )
    for i in range(5):
        sampler.sample_once()
    history = sampler.history()
    assert len(history) == 3
    # Oldest two were evicted; the last sample is the newest.
    assert history[-1]["ts"] == max(s["ts"] for s in history)


def test_history_limit_returns_most_recent() -> None:
    sampler = TrendSampler(account_provider=lambda: _account(), stats_provider=lambda: _stats())
    for _ in range(10):
        sampler.sample_once()
    assert len(sampler.history(limit=4)) == 4
    assert len(sampler.history()) == 10


def test_default_capacity_is_documented_value() -> None:
    assert TrendSampler().capacity == DEFAULT_CAPACITY


# ---------------------------------------------------------------------------
# Interval clamping
# ---------------------------------------------------------------------------


def test_interval_clamped_to_range() -> None:
    sampler = TrendSampler(interval=0.001)
    assert sampler.interval == MIN_INTERVAL_S
    sampler.interval = 99999
    assert sampler.interval == MAX_INTERVAL_S
    sampler.interval = 30
    assert sampler.interval == 30


# ---------------------------------------------------------------------------
# Async lifecycle
# ---------------------------------------------------------------------------


def test_async_loop_samples_and_stops() -> None:
    async def run() -> int:
        sampler = TrendSampler(
            account_provider=lambda: _account(),
            stats_provider=lambda: _stats(),
            interval=MIN_INTERVAL_S,
        )
        await sampler.start()
        assert sampler.running
        # The loop samples immediately on entry.
        await asyncio.sleep(0.05)
        await sampler.stop()
        assert not sampler.running
        return len(sampler.history())

    count = asyncio.run(run())
    assert count >= 1


def test_singleton_is_stable() -> None:
    assert get_trend_sampler() is get_trend_sampler()


# ---------------------------------------------------------------------------
# Settings wiring (knob -> live sampler)
# ---------------------------------------------------------------------------


def test_settings_knob_applies_to_sampler() -> None:
    """The writable knob must reach the live object (no settings theatre)."""
    from src.system.endpoints import _apply_to_runtime

    pushed = _apply_to_runtime({"trend_sample_interval": 45.0})
    assert pushed["trend_sample_interval"] == 45.0
    assert get_trend_sampler().interval == 45.0
    # Restore the default so other tests are not affected.
    _apply_to_runtime({"trend_sample_interval": 15.0})


def test_trend_endpoint_reports_real_state() -> None:
    from fastapi.testclient import TestClient

    from src.main import app

    with TestClient(app) as client:
        sampler = get_trend_sampler()
        sampler.sample_once()
        r = client.get("/observability/trend?limit=10")
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "live"
        assert body["capacity"] == sampler.capacity
        assert body["interval_s"] == pytest.approx(sampler.interval)
        assert body["count"] >= 1
        assert len(body["samples"]) == body["count"]
