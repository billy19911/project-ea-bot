# -*- coding: utf-8 -*-
"""Tests for the Telegram inbound poller (chat → bot commands).

The poller long-polls ``getUpdates`` on its *own* bot token and routes
authorized messages to the read-only gateway command surface. It must:

* use its own token (never the report bot's — Telegram allows one consumer),
* answer authorized commands and ignore unauthorized chats,
* advance the getUpdates offset (no double-processing),
* survive read failures (back-off) and per-message reply failures,
* stay OFF unless ``TELEGRAM_POLLER_ENABLED`` is truthy,
* never import execution / MT5 modules (same guard as gateway/transport).

Network calls are exercised with ``httpx.MockTransport`` — no real network.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json

import httpx
import pytest

from src.telegram import poller as poller_module
from src.telegram.poller import TelegramPoller, build_poller_from_env

TOKEN = "123456:SECRET_POLLER_TOKEN"
AUTHORIZED = 111
UNAUTHORIZED = 999


def _client(handler) -> httpx.Client:
    """Build an httpx client whose transport is an in-memory mock."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _updates_response(updates: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": updates})


def _message_update(update_id: int, chat_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id},
            "text": text,
        },
    }


# ---------------------------------------------------------------------------
# Happy path — command routed to gateway, reply sent back
# ---------------------------------------------------------------------------
def test_poll_once_replies_to_authorized_command() -> None:
    sent: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "getUpdates" in str(request.url):
            return _updates_response([_message_update(1, AUTHORIZED, "/help")])
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    poller = TelegramPoller(
        token=TOKEN,
        allowlist=[AUTHORIZED],
        providers={},
        client=_client(handler),
    )

    replied = poller.poll_once()

    assert replied == 1
    assert sent, "expected a reply to be sent"
    url, body = sent[0]
    assert f"/bot{TOKEN}/sendMessage" in url
    assert body["chat_id"] == str(AUTHORIZED)
    assert "/status" in body["text"]  # /help lists the commands


def test_poll_once_routes_status_to_provider() -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "getUpdates" in str(request.url):
            return _updates_response([_message_update(2, AUTHORIZED, "/status")])
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    poller = TelegramPoller(
        token=TOKEN,
        allowlist=[AUTHORIZED],
        providers={"status_provider": lambda: {"state": "RUNNING", "mode": "paper"}},
        client=_client(handler),
    )

    poller.poll_once()

    assert sent and "RUNNING" in sent[0]["text"]


# ---------------------------------------------------------------------------
# Authorization + offset handling
# ---------------------------------------------------------------------------
def test_unauthorized_chat_gets_no_reply() -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "getUpdates" in str(request.url):
            return _updates_response([_message_update(3, UNAUTHORIZED, "/status")])
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    poller = TelegramPoller(token=TOKEN, allowlist=[AUTHORIZED], client=_client(handler))

    assert poller.poll_once() == 0
    assert sent == []


def test_offset_advances_past_processed_updates() -> None:
    offsets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "getUpdates" in str(request.url):
            offsets.append(request.url.params.get("offset") or "")
            if len(offsets) == 1:
                return _updates_response([_message_update(41, AUTHORIZED, "/help")])
            return _updates_response([])
        return httpx.Response(200, json={"ok": True})

    poller = TelegramPoller(token=TOKEN, allowlist=[AUTHORIZED], client=_client(handler))

    poller.poll_once()
    poller.poll_once()

    assert offsets[0] == ""  # first poll has no offset
    assert offsets[1] == "42"  # 41 processed → next offset is 42


def test_non_text_updates_are_skipped() -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "getUpdates" in str(request.url):
            return _updates_response(
                [
                    {"update_id": 5, "message": {"chat": {"id": AUTHORIZED}}},
                    {"update_id": 6},
                    {"update_id": 7, "message": {"chat": {"id": AUTHORIZED}, "text": "  "}},
                ]
            )
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    poller = TelegramPoller(token=TOKEN, allowlist=[AUTHORIZED], client=_client(handler))

    assert poller.poll_once() == 0
    assert sent == []


# ---------------------------------------------------------------------------
# Fail-safe behaviour
# ---------------------------------------------------------------------------
def test_read_failure_raises_sanitised_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    poller = TelegramPoller(token=TOKEN, allowlist=[AUTHORIZED], client=_client(handler))

    with pytest.raises(Exception) as excinfo:
        poller.poll_once()

    assert TOKEN not in str(excinfo.value)


def test_reply_failure_does_not_block_other_messages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "getUpdates" in url:
            return _updates_response(
                [
                    _message_update(8, AUTHORIZED, "/help"),
                    _message_update(9, AUTHORIZED, "/help"),
                ]
            )
        if "sendMessage" in url:
            body = json.loads(request.content)
            if body["chat_id"] == str(AUTHORIZED) and "fail" not in getattr(handler, "seen", set()):
                handler.seen = {"fail"}  # first reply fails, second succeeds
                return httpx.Response(500, json={"ok": False})
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"ok": True})

    poller = TelegramPoller(token=TOKEN, allowlist=[AUTHORIZED], client=_client(handler))

    # One reply failed, the other succeeded → still returns 1, never raises.
    assert poller.poll_once() == 1


def test_run_survives_read_failures_and_stops_cleanly() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("down")

    poller = TelegramPoller(
        token=TOKEN,
        allowlist=[AUTHORIZED],
        client=_client(handler),
        error_delay=0.01,
    )

    async def scenario() -> None:
        task = asyncio.create_task(poller.run())
        await asyncio.sleep(0.1)
        poller.stop()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(scenario())

    assert calls["n"] >= 2, "the loop must keep polling after failures"
    assert poller.running is False


def test_run_offloads_blocking_poll_to_thread() -> None:
    """Regression: ``poll_once`` does blocking HTTP I/O (long-poll up to 25s).

    Running it directly in the event loop would freeze every FastAPI endpoint
    for the whole poll duration. The loop must offload it (``asyncio.to_thread``)
    so concurrent tasks keep ticking while a poll is in flight.
    """
    import threading

    release = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        # Block the worker thread until released (simulates a long-poll).
        release.wait(timeout=2.0)
        return _updates_response([])

    poller = TelegramPoller(
        token=TOKEN,
        allowlist=[AUTHORIZED],
        client=_client(handler),
        idle_delay=0.01,
        error_delay=0.01,
    )

    ticks = {"n": 0}

    async def ticker() -> None:
        while True:
            await asyncio.sleep(0.02)
            ticks["n"] += 1

    async def scenario() -> None:
        task = asyncio.create_task(poller.run())
        tk = asyncio.create_task(ticker())
        await asyncio.sleep(0.3)
        release.set()
        poller.stop()
        await asyncio.wait_for(task, timeout=3.0)
        tk.cancel()
        try:
            await tk
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    # If poll_once ran on the event-loop thread, the ticker could not run
    # during the blocking call — fewer than 5 ticks in 0.3 s means the loop
    # was frozen. With to_thread the ticker runs ~15 times.
    assert ticks["n"] >= 5, f"event loop was blocked during poll — only {ticks['n']} ticks"


# ---------------------------------------------------------------------------
# Env wiring — OFF by default, requires its own token
# ---------------------------------------------------------------------------
def test_build_poller_from_env_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_POLLER_ENABLED", raising=False)
    monkeypatch.delenv("TELEGRAM_POLLER_BOT_TOKEN", raising=False)

    assert build_poller_from_env() is None


def test_build_poller_from_env_enabled_without_token_stays_off(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_POLLER_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_POLLER_BOT_TOKEN", raising=False)

    assert build_poller_from_env() is None


def test_build_poller_from_env_builds_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_POLLER_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_POLLER_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", f"{AUTHORIZED},{UNAUTHORIZED}")

    poller = build_poller_from_env()

    assert poller is not None
    assert poller.gateway.allowlist == {str(AUTHORIZED), str(UNAUTHORIZED)}
    assert poller.gateway.transport is not None


def test_blank_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        TelegramPoller(token="   ")


# ---------------------------------------------------------------------------
# Lifespan wiring — poller starts/stops only when enabled
# ---------------------------------------------------------------------------
def test_lifespan_starts_and_stops_poller_when_enabled(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import src.main as main_module
    from src.telegram import poller as poller_module

    class _RecordingPoller:
        instances: list["_RecordingPoller"] = []

        def __init__(self) -> None:
            self.started = False
            self.stopped = False
            _RecordingPoller.instances.append(self)

        async def run(self) -> None:
            self.started = True
            while not self.stopped:
                await asyncio.sleep(0.01)

        def stop(self) -> None:
            self.stopped = True

    _RecordingPoller.instances.clear()
    monkeypatch.setattr(poller_module, "build_poller_from_env", lambda: _RecordingPoller())
    monkeypatch.setattr(main_module.settings, "scheduler_enabled", False)
    monkeypatch.setattr(main_module.settings, "market_feed_enabled", False)
    monkeypatch.setattr(main_module.settings, "mt5_live_data", False)

    with TestClient(main_module.app):
        assert _RecordingPoller.instances, "poller must be constructed when enabled"
        instance = _RecordingPoller.instances[-1]
        import time as _time

        end = _time.time() + 1.0
        while not instance.started and _time.time() < end:
            _time.sleep(0.01)

    assert instance.started, "poller.run() must be scheduled at startup"
    assert instance.stopped, "poller.stop() must be called at shutdown"


def test_lifespan_does_not_start_poller_when_disabled(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import src.main as main_module
    from src.telegram import poller as poller_module

    calls: list[int] = []
    monkeypatch.setattr(
        poller_module,
        "build_poller_from_env",
        lambda: calls.append(1) or None,
    )
    monkeypatch.setattr(main_module.settings, "scheduler_enabled", False)
    monkeypatch.setattr(main_module.settings, "market_feed_enabled", False)
    monkeypatch.setattr(main_module.settings, "mt5_live_data", False)

    with TestClient(main_module.app):
        pass

    assert calls, "lifespan must consult the env builder"
    # Builder returned None (disabled) → no poller task was created; nothing to
    # assert beyond a clean startup/shutdown (no hangs, no exceptions).


# ---------------------------------------------------------------------------
# Safety invariant — no execution / MT5 imports
# ---------------------------------------------------------------------------
def test_poller_module_does_not_import_execution_or_mt5() -> None:
    source = inspect.getsource(poller_module)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    assert not any(n.startswith("src.execution") for n in names)
    assert not any(n.startswith("src.mt5") for n in names)
    assert not any(n.startswith("MetaTrader5") for n in names)


def test_poller_exposes_no_order_placing_methods() -> None:
    forbidden = ("place_order", "send_order", "execute_order", "open_position", "close_position")
    for name in forbidden:
        assert not hasattr(TelegramPoller, name), f"unexpected method: {name}"
