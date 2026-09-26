# -*- coding: utf-8 -*-
"""FIX-503 T1 — discovery must be non-blocking, cached on failure, single-flight.

Root cause: ``ModelRegistry.discover_from_gateway()`` was called synchronously
inside an async handler. When the LLM gateway is unreachable (env missing -> the
internet default 404s) the event loop blocked for seconds on *every* request
because failures were never cached.

These tests pin the new contract:

* a failed discovery is negatively cached for ``failure_ttl`` seconds,
* the failure window expires and recovery is attempted again,
* concurrent callers collapse into exactly one network attempt (single-flight),
* the ``/ai/models`` handler no longer blocks the event loop (``/health`` stays
  fast while discovery sleeps).
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.llm.registry import STATE_CONNECTED, STATE_DISCONNECTED, ModelRegistry
from src.main import app
from src.system import endpoints as system_endpoints

client = TestClient(app)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _StubModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


class _StubModelsAPI:
    def __init__(self, entries: Any) -> None:
        self._entries = entries
        self.call_count = 0

    def list(self) -> Any:
        self.call_count += 1
        if isinstance(self._entries, Exception):
            raise self._entries
        return self._entries


class StubGatewayClient:
    """Minimal OpenAI-compatible client exposing ``.models.list()``."""

    def __init__(self, entries: Any) -> None:
        self.models = _StubModelsAPI(entries)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Give each test a fresh registry so discovery state does not leak."""
    system_endpoints._model_registry = system_endpoints.ModelRegistry()
    yield
    system_endpoints._model_registry = system_endpoints.ModelRegistry()


def _run_coro(coro: Any) -> Any:
    """Run ``coro`` on a private loop, then restore a usable current loop.

    ``asyncio.run`` closes its loop and unsets the thread's current event loop,
    which breaks later sync tests that call ``asyncio.get_event_loop()``. We
    restore a fresh, open loop so the rest of the suite is unaffected.
    """
    loop = asyncio.new_event_loop()
    previous = None
    try:
        previous = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        previous = None
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        if previous is not None and not previous.is_closed():
            asyncio.set_event_loop(previous)
        else:
            asyncio.set_event_loop(asyncio.new_event_loop())


# ---------------------------------------------------------------------------
# a. Negative cache after failure
# ---------------------------------------------------------------------------
def test_negative_cache_after_failure() -> None:
    """A second call within the failure window must not hit the gateway again."""
    registry = ModelRegistry()
    failing = StubGatewayClient(RuntimeError("gateway down"))

    registry.discover_from_gateway(client=failing)
    assert failing.models.call_count == 1

    start = time.perf_counter()
    registry.discover_from_gateway(client=failing)
    elapsed = time.perf_counter() - start

    # No new network attempt, returns fast, health stays honest.
    assert failing.models.call_count == 1
    assert elapsed <= 0.05
    assert registry.health()["state"] == STATE_DISCONNECTED
    assert registry.source == "defaults"


def test_negative_cache_then_recovery_success() -> None:
    """After a failure window expires, a healthy gateway can recover the cache."""
    registry = ModelRegistry()
    registry.failure_ttl = 0.05
    registry.discover_from_gateway(client=StubGatewayClient(RuntimeError("down")))
    assert registry.health()["state"] == STATE_DISCONNECTED

    time.sleep(0.06)
    good = StubGatewayClient([_StubModel("openai/gpt-4o-mini")])
    registry.discover_from_gateway(client=good)

    assert good.models.call_count == 1
    assert registry.health()["state"] == STATE_CONNECTED
    assert registry.get("openai/gpt-4o-mini") is not None


# ---------------------------------------------------------------------------
# b. Failure window expiry
# ---------------------------------------------------------------------------
def test_failure_ttl_expiry() -> None:
    """Once the failure window passes the next call is allowed to retry."""
    registry = ModelRegistry()
    registry.failure_ttl = 0.05
    failing = StubGatewayClient(RuntimeError("down"))

    registry.discover_from_gateway(client=failing)
    assert failing.models.call_count == 1

    # Within the window: no retry.
    registry.discover_from_gateway(client=failing)
    assert failing.models.call_count == 1

    # Window expires: retry happens again.
    time.sleep(0.06)
    registry.discover_from_gateway(client=failing)
    assert failing.models.call_count == 2


# ---------------------------------------------------------------------------
# c. Single-flight concurrency
# ---------------------------------------------------------------------------
def test_single_flight_concurrent() -> None:
    """Four concurrent callers while discovery is slow -> exactly one attempt."""
    registry = ModelRegistry()
    started = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    class SlowClient:
        class models:  # noqa: N801 - mimic attribute name
            @staticmethod
            def list() -> Any:
                calls["n"] += 1
                started.set()
                release.wait(timeout=2.0)
                raise RuntimeError("down")

    results: list[int] = []

    def _call() -> None:
        registry.discover_from_gateway(client=SlowClient())
        results.append(1)

    threads = [threading.Thread(target=_call) for _ in range(4)]
    threads[0].start()
    started.wait(timeout=2.0)  # ensure the first holds the flight
    for thread in threads[1:]:
        thread.start()
    time.sleep(0.05)  # let the other three pile up on the lock
    release.set()
    for thread in threads:
        thread.join(timeout=5.0)

    assert calls["n"] == 1
    assert len(results) == 4


# ---------------------------------------------------------------------------
# d. Endpoint non-blocking (event loop stays free)
# ---------------------------------------------------------------------------
def test_ai_models_endpoint_nonblocking(monkeypatch: Any) -> None:
    """While discovery sleeps, /health must stay fast (event loop not blocked).

    Both requests are awaited on the SAME event loop via an in-process ASGI
    transport, so a synchronous (blocking) discovery in ``/ai/models`` would
    stall ``/health`` too. We wait for discovery to actually be in-flight (its
    blocking body runs inside a worker thread once fixed) before timing the
    unrelated health check — reproducing the production failure mode where the
    Node proxy 503s because unrelated endpoints queue on the blocked loop.
    """
    import httpx

    registry = system_endpoints.get_model_registry()

    def _slow_fetch(client: Any) -> Any:
        time.sleep(1.0)
        raise RuntimeError("down")

    monkeypatch.setattr(registry, "_fetch_gateway_models", _slow_fetch)

    async def _run() -> tuple[float, int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            # Time from before yielding to the discovery request. A blocking
            # discovery (sync in-handler) would hold the loop once it starts,
            # delaying the /health response by ~1s; an off-loaded discovery
            # (asyncio.to_thread) lets /health answer immediately.
            models_task = asyncio.create_task(ac.get("/ai/models"))
            start = time.perf_counter()
            await asyncio.sleep(0)  # let the discovery coroutine start
            health = await ac.get("/health")
            health_elapsed = time.perf_counter() - start
            await models_task
        return health_elapsed, health.status_code

    health_elapsed, health_status = _run_coro(_run())

    assert health_status == 200
    assert health_elapsed <= 0.5
