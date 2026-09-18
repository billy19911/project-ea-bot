# -*- coding: utf-8 -*-
"""Tests for the HTTP Telegram transport (Phase 5).

The transport is the *only* component that talks to api.telegram.org. It must:

* POST to ``/bot<token>/sendMessage`` with ``{"chat_id", "text"}``,
* raise on HTTP/network errors (the gateway converts those to a safe ``False``),
* **never leak the bot token** in raised exception messages or logs, and
* never import execution / MT5 modules (same guard as the gateway).

Network calls are exercised with ``httpx.MockTransport`` — no real network.
"""

from __future__ import annotations

import ast
import inspect
import json

import httpx
import pytest

from src.telegram import transport as transport_module
from src.telegram.transport import HttpTelegramTransport

TOKEN = "123456:SECRET_TEST_TOKEN"


def _client(handler) -> httpx.Client:
    """Build an httpx client whose transport is an in-memory mock."""
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------
def test_send_message_posts_to_bot_send_message_url() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    transport = HttpTelegramTransport(token=TOKEN, client=_client(handler))
    transport.send_message(12345, "hello world")

    assert captured["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert captured["body"]["chat_id"] == "12345"
    assert captured["body"]["text"] == "hello world"


def test_send_message_accepts_string_chat_id() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    transport = HttpTelegramTransport(token=TOKEN, client=_client(handler))
    transport.send_message("-100123456", "x")

    assert captured["body"]["chat_id"] == "-100123456"


# ---------------------------------------------------------------------------
# Construction guard
# ---------------------------------------------------------------------------
def test_empty_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        HttpTelegramTransport(token="")


def test_blank_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        HttpTelegramTransport(token="   ")


# ---------------------------------------------------------------------------
# Failure behaviour — raise, but never leak the token
# ---------------------------------------------------------------------------
def test_http_error_raises_without_token_leak() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    transport = HttpTelegramTransport(token=TOKEN, client=_client(handler))
    with pytest.raises(Exception) as excinfo:
        transport.send_message(1, "x")

    assert TOKEN not in str(excinfo.value)


def test_network_error_raises_without_token_leak() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = HttpTelegramTransport(token=TOKEN, client=_client(handler))
    with pytest.raises(Exception) as excinfo:
        transport.send_message(1, "x")

    assert TOKEN not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Safety invariant — no execution / MT5 imports
# ---------------------------------------------------------------------------
def test_transport_module_does_not_import_execution_or_mt5() -> None:
    source = inspect.getsource(transport_module)
    assert "src.execution" not in source
    assert "src.mt5" not in source
    assert "MetaTrader5" not in source

    names: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    assert not any(n.startswith("src.mt5") for n in names)
    assert not any(n.startswith("src.execution") for n in names)
    assert not any(n.startswith("MetaTrader5") for n in names)


def test_transport_has_no_trading_methods() -> None:
    forbidden = ("place_order", "send_order", "execute", "open_position", "close_position")
    for name in forbidden:
        assert not hasattr(HttpTelegramTransport, name), f"unexpected method: {name}"
