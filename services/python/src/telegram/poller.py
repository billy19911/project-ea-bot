# -*- coding: utf-8 -*-
"""Telegram inbound poller — read-only command replies (chat → bot).

Long-polls ``getUpdates`` and routes authorized messages to the read-only
:class:`TelegramGateway` command surface (``/status``, ``/positions``,
``/risk``, ``/why``, ``/review``, ``/help``), sending the reply back through
the same bot.

Design rules:

* **Own bot token** — Telegram allows only one ``getUpdates`` consumer per bot,
  so this poller must not share the report bot's token: it uses
  ``TELEGRAM_POLLER_BOT_TOKEN`` (a second bot from @BotFather) and is OFF by
  default (``TELEGRAM_POLLER_ENABLED=true`` switches it on).
* **Read-only** — the gateway is a command/query surface; this module never
  imports execution/MT5 code and can never place an order (guard test).
* **Fail-safe** — API/network failures back off and retry; a reply failure
  skips that message; unauthorized chats are ignored silently.
* **No token leaks** — errors are sanitised by the transport layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Optional

import httpx

from .gateway import TelegramGateway
from .transport import HttpTelegramTransport, TelegramTransportError

logger = logging.getLogger(__name__)

__all__ = ["TelegramPoller", "build_poller_from_env"]

_API_BASE = "https://api.telegram.org"
_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(raw: str) -> bool:
    """Return True for common truthy env spellings."""
    return raw.strip().lower() in _TRUTHY


class TelegramPoller:
    """Poll ``getUpdates`` and reply to authorized read-only commands.

    Args:
        token: Bot token of the *inbound* bot (never the report bot's token).
        allowlist: Chat ids permitted to issue commands (empty = nobody).
        providers: Optional provider callables for :class:`TelegramGateway`.
        client: Optional pre-built ``httpx.Client`` (tests inject
            ``httpx.MockTransport`` — no real network in tests).
        poll_timeout: ``getUpdates`` long-poll timeout in seconds.
        idle_delay: Pause between successful polls.
        error_delay: Back-off after a failed poll.
    """

    def __init__(
        self,
        token: str,
        allowlist: Optional[list[Any]] = None,
        providers: Optional[dict[str, Callable[[], Any]]] = None,
        client: Optional[httpx.Client] = None,
        poll_timeout: float = 25.0,
        idle_delay: float = 0.5,
        error_delay: float = 10.0,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Telegram poller bot token must be a non-empty string")
        self._token = token.strip()
        self._client = client
        self._poll_timeout = float(poll_timeout)
        self._idle_delay = float(idle_delay)
        self._error_delay = float(error_delay)
        self._offset: Optional[int] = None
        self._running = False
        transport = HttpTelegramTransport(token=self._token, client=client)
        self.gateway = TelegramGateway(
            transport=transport,
            allowlist=allowlist or [],
            **(providers or {}),
        )

    @property
    def running(self) -> bool:
        """Return True while the async poll loop is active."""
        return self._running

    def _get_updates(self) -> list[dict[str, Any]]:
        """Fetch pending updates; failures raise a sanitised error."""
        url = f"{_API_BASE}/bot{self._token}/getUpdates"
        params: dict[str, Any] = {"timeout": int(self._poll_timeout), "limit": 100}
        if self._offset is not None:
            params["offset"] = self._offset
        try:
            timeout = self._poll_timeout + 10.0
            if self._client is not None:
                response = self._client.get(url, params=params, timeout=timeout)
            else:
                response = httpx.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - sanitised re-raise below
            raise TelegramTransportError(f"getUpdates failed ({type(exc).__name__})") from None
        updates = payload.get("result") if isinstance(payload, dict) else None
        return updates if isinstance(updates, list) else []

    def poll_once(self) -> int:
        """Handle one batch of updates; returns the number of replies sent.

        Read failures raise :class:`TelegramTransportError` (the run loop backs
        off); per-message failures are skipped so one bad update cannot stop
        the batch.
        """
        updates = self._get_updates()
        replied = 0
        for update in updates:
            if not isinstance(update, dict):
                continue
            self._advance_offset(update.get("update_id"))
            message = update.get("message")
            if not isinstance(message, dict):
                continue
            text = message.get("text")
            chat = message.get("chat")
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            if not isinstance(text, str) or not text.strip() or chat_id is None:
                continue
            if not self.gateway.is_authorized(chat_id):
                logger.info("Ignoring message from unauthorized chat %s", chat_id)
                continue
            try:
                reply = self.gateway.handle_message(chat_id, text)
                self.gateway.transport.send_message(chat_id, reply)
                replied += 1
            except Exception as exc:  # noqa: BLE001 - one bad reply must not stop the batch
                logger.warning("Failed to reply to chat %s (%s)", chat_id, type(exc).__name__)
        return replied

    def _advance_offset(self, update_id: Any) -> None:
        """Move the getUpdates offset past ``update_id`` (fail-safe)."""
        try:
            value = int(update_id)
        except (TypeError, ValueError):
            return
        if self._offset is None or value >= self._offset:
            self._offset = value + 1

    async def run(self) -> None:
        """Poll until :meth:`stop`; failures back off, cancellation is clean."""
        self._running = True
        try:
            while self._running:
                try:
                    self.poll_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - the loop never dies
                    logger.warning(
                        "Telegram poll failed (%s); backing off %.0fs",
                        type(exc).__name__,
                        self._error_delay,
                    )
                    await asyncio.sleep(self._error_delay)
                    continue
                await asyncio.sleep(self._idle_delay)
        finally:
            self._running = False

    def stop(self) -> None:
        """Request the loop to stop after the current poll/sleep."""
        self._running = False


def build_poller_from_env() -> Optional[TelegramPoller]:
    """Build the inbound poller from env; ``None`` when off/misconfigured.

    Env: ``TELEGRAM_POLLER_ENABLED`` (truthy switch),
    ``TELEGRAM_POLLER_BOT_TOKEN`` (second bot), ``TELEGRAM_ALLOWED_CHAT_IDS``
    (shared allowlist). Never raises — a wiring problem keeps the feature off.
    """
    try:
        enabled = _is_truthy(os.getenv("TELEGRAM_POLLER_ENABLED") or "")
        if not enabled:
            return None
        token = (os.getenv("TELEGRAM_POLLER_BOT_TOKEN") or "").strip()
        if not token:
            logger.warning(
                "TELEGRAM_POLLER_ENABLED=true but TELEGRAM_POLLER_BOT_TOKEN is empty; "
                "inbound poller stays off"
            )
            return None
        raw_allowlist = (
            os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_IDS") or ""
        )
        allowlist = [cid.strip() for cid in raw_allowlist.split(",") if cid.strip()]
        providers: dict[str, Callable[[], Any]] = {}
        try:
            from .providers import build_default_providers

            providers = build_default_providers()
        except Exception:  # noqa: BLE001 - commands degrade to "unavailable"
            logger.warning("Default Telegram providers unavailable; commands degraded")
        return TelegramPoller(token=token, allowlist=allowlist, providers=providers)
    except Exception as exc:  # noqa: BLE001 - never break startup
        logger.warning("Could not build Telegram poller (%s); staying off", type(exc).__name__)
        return None
