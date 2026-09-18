# -*- coding: utf-8 -*-
"""HTTP transport for the Telegram gateway (Phase 5).

This module is the *only* component that talks to ``api.telegram.org``. It
implements the transport contract expected by :class:`TelegramGateway` — any
object exposing ``send_message(chat_id, text)`` — and deliberately contains
nothing else:

* No execution / MT5 imports (a guard test enforces this invariant).
* The bot token never appears in exception messages or logs.
* Network failures raise; the gateway converts them into a safe ``False``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = ["HttpTelegramTransport", "TelegramTransportError"]

_API_BASE = "https://api.telegram.org"
_DEFAULT_TIMEOUT = 10.0


class TelegramTransportError(RuntimeError):
    """Raised when a Telegram API call fails.

    The message deliberately excludes the bot token (and the request URL,
    which embeds it) so tokens can never leak through error surfaces.
    """


class HttpTelegramTransport:
    """POST ``/bot<token>/sendMessage`` via httpx.

    Args:
        token: Bot token from @BotFather. Must be non-blank.
        client: Optional pre-built ``httpx.Client`` (injectable so tests can
            use ``httpx.MockTransport`` — no real network in tests).
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        token: str,
        client: Optional[httpx.Client] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Telegram bot token must be a non-empty string")
        self._token = token.strip()
        self._client = client
        self._timeout = float(timeout)

    def send_message(self, chat_id: Any, text: str) -> None:
        """Send ``text`` to ``chat_id``. Raises on failure (never leaks token)."""
        url = f"{_API_BASE}/bot{self._token}/sendMessage"
        payload = {"chat_id": str(chat_id), "text": text}
        try:
            if self._client is not None:
                response = self._client.post(url, json=payload, timeout=self._timeout)
            else:
                response = httpx.post(url, json=payload, timeout=self._timeout)
            response.raise_for_status()
        except TelegramTransportError:
            raise
        except Exception as exc:
            # Re-raise a sanitised error: the original exception (and the
            # request URL embedding the token) must never surface.
            raise TelegramTransportError(
                f"Telegram sendMessage failed ({type(exc).__name__})"
            ) from None
