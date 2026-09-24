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

    def send_message(self, chat_id: Any, text: str) -> Optional[int]:
        """Send ``text`` to ``chat_id``; return the new ``message_id`` (if any).

        Raises on failure (never leaks token). When Telegram's response body
        carries ``result.message_id`` that integer is returned so the caller can
        later *edit* the same message; otherwise ``None``.
        """
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
        return self._extract_message_id(response)

    def edit_message_text(self, chat_id: Any, message_id: int, text: str) -> bool:
        """Edit a previously sent message in place. Raises on real failure.

        Telegram returns HTTP 400 with "message is not modified" when the new
        body is byte-identical to the current one — that is idempotent success,
        not an error, so it is reported as ``True``.
        """
        url = f"{_API_BASE}/bot{self._token}/editMessageText"
        payload = {
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": text,
        }
        try:
            if self._client is not None:
                response = self._client.post(url, json=payload, timeout=self._timeout)
            else:
                response = httpx.post(url, json=payload, timeout=self._timeout)
            if (
                response.status_code == 400
                and "message is not modified" in response.text.lower()
            ):
                return True
            response.raise_for_status()
        except TelegramTransportError:
            raise
        except Exception as exc:
            raise TelegramTransportError(
                f"Telegram editMessageText failed ({type(exc).__name__})"
            ) from None
        return True

    @staticmethod
    def _extract_message_id(response: Any) -> Optional[int]:
        """Read ``result.message_id`` from a send response (fail-safe ``None``)."""
        try:
            body = response.json()
            message_id = body.get("result", {}).get("message_id")
            return int(message_id) if message_id is not None else None
        except Exception:  # noqa: BLE001 - a missing id must never break a send
            return None
