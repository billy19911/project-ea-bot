# -*- coding: utf-8 -*-
"""Tests for wiring the two AI learning loops into the production close path.

Covers the ``_on_review`` callback defined inside the FastAPI lifespan
(``services/python/src/main.py``):

* every reviewed trade feeds ``agent_memory.record_outcome`` once per agent,
* every reviewed trade feeds ``news_patterns.record_outcome`` once per event,
* empty inputs are skipped without a crash or a call,
* a missing ``trade_result`` is skipped gracefully,
* a raising learning store is swallowed (review must continue),
* the existing lesson-persist + signal-lifecycle calls still happen.

The learning stores are patched to mocks so no state leaks; the callback is
reached exactly as in production (through the lifespan's
``set_auto_trigger`` → ``ReviewAutoTrigger.on_review``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import src.main as main_module
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _trade_result(**overrides):
    base = {
        "pnl": 120.0,
        "direction": "BUY",
        "symbol": "EURUSD",
        "regime": "trending",
        "status": "CLOSED",
        "close_price": 1.1050,
    }
    base.update(overrides)
    return base


def _review_record(**attrs):
    """Stand-in ReviewRecord exposing the raw close context on attributes.

    Mimics how ``_on_review`` reaches into the record for the learning
    payloads (``trade_result`` / ``agent_outputs`` / ``news_events``).
    """
    review = SimpleNamespace(outcome="WIN", pnl=120.0, summary="s")
    root_cause = SimpleNamespace(primary_cause="edge", confidence=0.5)
    defaults = {
        "trade_id": "T-1",
        "review": review,
        "root_cause": root_cause,
        "trade_result": None,
        "agent_outputs": {},
        "news_events": [],
    }
    defaults.update(attrs)

    record = SimpleNamespace(**defaults)

    def _to_dict():
        return {"trade_id": record.trade_id}

    record.to_dict = _to_dict
    return record


@pytest.fixture
def _review_cb(monkeypatch):
    """Boot the lifespan and capture the wired ``_on_review`` callback.

    Patching ``get_agent_memory`` / ``get_news_pattern_memory`` before startup is
    irrelevant (the callback imports them lazily on each call), so we patch after
    boot and return ``(callback, mem_mock, nps_mock, lesson_store, lifecycle)``.
    """
    from agents.analysts.review_agent import get_lesson_store
    from review.auto_trigger import get_auto_trigger, set_auto_trigger

    calls: dict = {}

    class _Mem:
        def __init__(self):
            self.calls = []

        def record_outcome(self, **kwargs):
            self.calls.append(kwargs)

    class _Nps:
        def __init__(self):
            self.calls = []

        def record_outcome(self, **kwargs):
            self.calls.append(kwargs)

    mem = _Mem()
    nps = _Nps()
    lifecycle = SimpleNamespace(
        calls=[], on_review=lambda payload: lifecycle.calls.append(payload)
    )

    monkeypatch.setattr(main_module.settings, "scheduler_enabled", False)
    monkeypatch.setattr(main_module.settings, "market_feed_enabled", False)
    monkeypatch.setattr(main_module.settings, "mt5_live_data", False)

    original_trigger = get_auto_trigger()
    try:
        with TestClient(main_module.app):
            # Boot done; grab the callback wired by the lifespan.
            cb = get_auto_trigger()._on_review
            monkeypatch.setattr(
                "agents.agent_memory.get_agent_memory", lambda: mem, raising=False
            )
            monkeypatch.setattr(
                "market.news_patterns.get_news_pattern_memory",
                lambda: nps,
                raising=False,
            )
            calls["cb"] = cb
            calls["mem"] = mem
            calls["nps"] = nps
            calls["lesson_store"] = get_lesson_store()
            calls["lifecycle"] = lifecycle
            yield calls
    finally:
        set_auto_trigger(original_trigger)


# ---------------------------------------------------------------------------
# 1) agent_memory wiring
# ---------------------------------------------------------------------------
def test_agent_memory_records_once_per_agent(_review_cb):
    cb = _review_cb["cb"]
    mem = _review_cb["mem"]
    record = _review_record(
        trade_result=_trade_result(
            pnl=120.0, direction="BUY", symbol="EURUSD", regime="trending"
        ),
        agent_outputs={
            "momentum": {"confidence": 0.8},
            "structure": {"confidence": 0.6},
        },
    )

    cb(record)

    assert len(mem.calls) == 2
    names = sorted(c["agent"] for c in mem.calls)
    assert names == ["momentum", "structure"]
    for call in mem.calls:
        assert call["direction"] == "BUY"
        assert call["correct"] is True
        assert call["symbol"] == "EURUSD"
        assert call["regime"] == "trending"
    by_agent = {c["agent"]: c for c in mem.calls}
    assert by_agent["momentum"]["confidence"] == pytest.approx(0.8)
    assert by_agent["structure"]["confidence"] == pytest.approx(0.6)


def test_agent_memory_marks_loss_incorrect(_review_cb):
    cb = _review_cb["cb"]
    mem = _review_cb["mem"]
    record = _review_record(
        trade_result=_trade_result(pnl=-50.0),
        agent_outputs={"momentum": {"confidence": 0.5}},
    )

    cb(record)

    assert len(mem.calls) == 1
    assert mem.calls[0]["correct"] is False


# ---------------------------------------------------------------------------
# 2) news_patterns wiring
# ---------------------------------------------------------------------------
def test_news_patterns_records_once_per_event(_review_cb):
    cb = _review_cb["cb"]
    nps = _review_cb["nps"]
    record = _review_record(
        trade_result=_trade_result(pnl=200.0, symbol="XAUUSD"),
        news_events=[
            {
                "title": "US CPI beats",
                "country": "US",
                "impact": "high",
                "forecast": "3.0",
                "actual": "3.2",
            },
            {"title": "ECB rate decision", "country": "EU", "impact": "medium"},
        ],
    )

    cb(record)

    assert len(nps.calls) == 2
    assert nps.calls[0]["title"] == "US CPI beats"
    assert nps.calls[0]["country"] == "US"
    assert nps.calls[0]["impact"] == "high"
    assert nps.calls[0]["symbol"] == "XAUUSD"
    assert nps.calls[0]["realised_return"] == pytest.approx(200.0)
    assert nps.calls[0]["forecast"] == "3.0"
    assert nps.calls[0]["actual"] == "3.2"


def test_news_event_without_title_is_skipped(_review_cb):
    cb = _review_cb["cb"]
    nps = _review_cb["nps"]
    record = _review_record(
        trade_result=_trade_result(),
        news_events=[{"country": "US"}, {"title": "NFP miss", "country": "US"}],
    )

    cb(record)

    assert len(nps.calls) == 1
    assert nps.calls[0]["title"] == "NFP miss"


# ---------------------------------------------------------------------------
# 3) empty inputs → no crash, no calls
# ---------------------------------------------------------------------------
def test_empty_inputs_do_nothing(_review_cb):
    cb = _review_cb["cb"]
    mem = _review_cb["mem"]
    nps = _review_cb["nps"]
    record = _review_record(
        trade_result=_trade_result(),
        agent_outputs={},
        news_events=[],
    )

    cb(record)  # must not raise

    assert mem.calls == []
    assert nps.calls == []


# ---------------------------------------------------------------------------
# 4) missing trade_result → graceful skip
# ---------------------------------------------------------------------------
def test_missing_trade_result_skips_gracefully(_review_cb):
    cb = _review_cb["cb"]
    mem = _review_cb["mem"]
    nps = _review_cb["nps"]
    record = _review_record(
        trade_result=None, agent_outputs={"momentum": {}}, news_events=[]
    )

    cb(record)  # must not raise

    assert mem.calls == []
    assert nps.calls == []


# ---------------------------------------------------------------------------
# 5) raising record_outcome is swallowed
# ---------------------------------------------------------------------------
def test_raising_learning_stores_are_swallowed(_review_cb, monkeypatch):
    cb = _review_cb["cb"]

    class _BoomMem:
        def record_outcome(self, **kwargs):
            raise RuntimeError("mem down")

    class _BoomNps:
        def record_outcome(self, **kwargs):
            raise RuntimeError("nps down")

    monkeypatch.setattr(
        "agents.agent_memory.get_agent_memory", lambda: _BoomMem(), raising=False
    )
    monkeypatch.setattr(
        "market.news_patterns.get_news_pattern_memory",
        lambda: _BoomNps(),
        raising=False,
    )

    record = _review_record(
        trade_result=_trade_result(),
        agent_outputs={"momentum": {"confidence": 0.5}},
        news_events=[{"title": "CPI", "country": "US"}],
    )

    cb(record)  # must not raise


# ---------------------------------------------------------------------------
# 5b) dict-shaped record (the spec's "test record" shape) also works
# ---------------------------------------------------------------------------
def test_dict_record_shape_is_supported(_review_cb):
    cb = _review_cb["cb"]
    mem = _review_cb["mem"]
    nps = _review_cb["nps"]
    record = {
        "trade_result": _trade_result(pnl=10.0, direction="SELL", symbol="GBPUSD"),
        "agent_outputs": {"structure": {"confidence": 0.4}},
        "news_events": [{"title": "BoE hike", "country": "GB"}],
    }

    cb(record)

    assert len(mem.calls) == 1
    assert mem.calls[0]["agent"] == "structure"
    assert mem.calls[0]["direction"] == "SELL"
    assert mem.calls[0]["correct"] is True
    assert len(nps.calls) == 1
    assert nps.calls[0]["title"] == "BoE hike"


# ---------------------------------------------------------------------------
# 6) existing lesson persist + signal lifecycle still happen
# ---------------------------------------------------------------------------
def test_existing_lesson_and_signal_calls_still_happen(_review_cb, monkeypatch):
    cb = _review_cb["cb"]
    store = _review_cb["lesson_store"]
    lifecycle = _review_cb["lifecycle"]

    recorded_lessons: list = []
    monkeypatch.setattr(
        store, "add_lesson", lambda lesson: recorded_lessons.append(lesson)
    )

    review_calls: list = []
    lifecycle.on_review = lambda payload: review_calls.append(payload)
    monkeypatch.setattr(
        "telegram.signal_lifecycle.get_signal_lifecycle",
        lambda: lifecycle,
        raising=False,
    )

    record = _review_record(
        trade_result=_trade_result(),
        agent_outputs={"momentum": {"confidence": 0.5}},
        news_events=[{"title": "CPI", "country": "US"}],
    )

    cb(record)

    assert len(recorded_lessons) == 1
    assert len(review_calls) == 1
