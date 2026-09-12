# -*- coding: utf-8 -*-
"""MT5 connection manager — lifecycle, health check, auto-reconnect."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ._connector_base import MT5Config, MT5Connector, MT5Error, MT5Health  # noqa: TID251

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class ConnectionStats:
    total_connections: int = 0
    successful_connections: int = 0
    failed_attempts: int = 0
    consecutive_failures: int = 0
    last_connect_at: datetime | None = None
    last_disconnect_at: datetime | None = None
    last_error: MT5Error | None = None
    uptime_seconds: float = 0.0
    total_reconnects: int = 0


class MT5ConnectionManager:
    """Manages MT5 connection lifecycle with auto-reconnect and health monitoring."""

    def __init__(
        self,
        config: MT5Config | None = None,
        auto_reconnect: bool = True,
        max_consecutive_failures: int = 5,
        health_check_interval_s: float = 30.0,
    ) -> None:
        self._config = config or MT5Config()
        self._auto_reconnect = auto_reconnect
        self._max_failures = max_consecutive_failures
        self._health_check_interval = health_check_interval_s

        self._connector = MT5Connector(self._config)
        self._state = ConnectionState.DISCONNECTED
        self._stats = ConnectionStats()
        self._last_health_check: MT5Health | None = None
        self._health_check_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._started = False

    # -- properties -------------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def stats(self) -> ConnectionStats:
        return self._stats

    @property
    def connector(self) -> MT5Connector:
        return self._connector

    @property
    def last_health(self) -> MT5Health | None:
        return self._last_health_check

    @property
    def is_connected(self) -> bool:
        return self._state in (ConnectionState.CONNECTED, ConnectionState.AUTHENTICATED)

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> bool:
        """Start the connection manager and attempt initial connection."""
        if self._started:
            logger.warning("ConnectionManager already started")
            return self.is_connected

        self._started = True
        self._stop_event.clear()
        logger.info("MT5ConnectionManager starting...")

        connected = await self.connect()
        if connected and self._health_check_interval > 0:
            self._health_check_task = asyncio.create_task(self._health_check_loop())

        return connected

    async def stop(self) -> None:
        """Stop the connection manager and disconnect."""
        logger.info("MT5ConnectionManager stopping...")
        self._stop_event.set()

        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        self._connector.shutdown()
        self._state = ConnectionState.DISCONNECTED
        self._stats.last_disconnect_at = datetime.now(timezone.utc)
        self._started = False
        logger.info("MT5ConnectionManager stopped")

    # -- connection -------------------------------------------------------

    async def connect(self) -> bool:
        """Connect to MT5 with retry logic."""
        self._state = ConnectionState.CONNECTING
        logger.info(
            "Connecting to MT5 (login=%s, server=%s)...", self._config.login, self._config.server
        )

        for attempt in range(1, self._config.max_retries + 1):
            self._stats.total_connections += 1
            try:
                ok = self._connector.initialise()
                if ok:
                    self._state = ConnectionState.CONNECTED
                    self._stats.successful_connections += 1
                    self._stats.consecutive_failures = 0
                    self._stats.last_connect_at = datetime.now(timezone.utc)
                    logger.info("MT5 connected (attempt %d)", attempt)

                    # Verify with health check
                    health = self._connector.health_check()
                    if health.connected:
                        self._state = ConnectionState.AUTHENTICATED
                        self._last_health_check = health
                        logger.info(
                            "MT5 authenticated — login=%d, server=%s", health.login, health.server
                        )
                    return True

                raise RuntimeError("initialise returned False")
            except Exception as exc:
                self._record_failure(exc)
                logger.warning(
                    "MT5 connection attempt %d/%d failed: %s",
                    attempt,
                    self._config.max_retries,
                    exc,
                )
                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._config.retry_delay_s)

        self._state = ConnectionState.FAILED
        logger.error("MT5 connection failed after %d attempts", self._config.max_retries)

        if self._auto_reconnect and self._stats.consecutive_failures < self._max_failures:
            await self._schedule_reconnect()

        return False

    async def disconnect(self) -> None:
        """Disconnect from MT5."""
        logger.info("Disconnecting from MT5...")
        self._connector.shutdown()
        self._state = ConnectionState.DISCONNECTED
        self._stats.last_disconnect_at = datetime.now(timezone.utc)
        logger.info("MT5 disconnected")

    async def reconnect(self) -> bool:
        """Force a reconnect: disconnect then connect."""
        logger.info("Reconnecting MT5...")
        self._connector.shutdown()
        self._state = ConnectionState.RECONNECTING
        self._stats.total_reconnects += 1
        return await self.connect()

    # -- health check -----------------------------------------------------

    async def health_check(self) -> MT5Health:
        """Run a health check against the MT5 connection."""
        health = self._connector.health_check()
        self._last_health_check = health
        if health.connected:
            self._state = ConnectionState.AUTHENTICATED
        else:
            self._state = ConnectionState.FAILED
            self._record_failure(health.error or "health check failed")
        return health

    async def _health_check_loop(self) -> None:
        """Background periodic health check."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self.health_check(), timeout=self._health_check_interval / 2)
            except asyncio.TimeoutError:
                logger.warning("Health check timed out")
                self._record_failure("health check timeout")
            except Exception as exc:
                logger.warning("Health check error: %s", exc)
                self._record_failure(exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._health_check_interval)
            except asyncio.TimeoutError:
                pass

    # -- auto-reconnect ---------------------------------------------------

    async def _schedule_reconnect(self) -> None:
        """Schedule a background reconnect attempt."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        logger.info("Scheduling auto-reconnect...")
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Background reconnect loop with exponential backoff."""
        backoff = self._config.retry_delay_s
        while (
            not self._stop_event.is_set() and self._stats.consecutive_failures < self._max_failures
        ):
            logger.info("Auto-reconnect attempt in %.1fs...", backoff)
            try:
                await asyncio.wait_for(
                    asyncio.sleep(backoff),
                    timeout=backoff + 5,
                )
            except asyncio.TimeoutError:
                pass

            if self._stop_event.is_set():
                break

            try:
                ok = await self.reconnect()
                if ok:
                    logger.info("Auto-reconnect succeeded")
                    return
            except Exception as exc:
                logger.warning("Auto-reconnect failed: %s", exc)
                self._record_failure(exc)

            backoff = min(backoff * 2, 60.0)

        if self._stats.consecutive_failures >= self._max_failures:
            self._state = ConnectionState.FAILED
            logger.error(
                "Auto-reconnect abandoned after %d consecutive failures", self._max_failures
            )

    # -- error tracking ---------------------------------------------------

    def _record_failure(self, error: Exception | str | MT5Error | None) -> None:
        self._stats.failed_attempts += 1
        self._stats.consecutive_failures += 1
        if isinstance(error, MT5Error):
            self._stats.last_error = error
        else:
            msg = str(error) if error is not None else "unknown error"
            self._stats.last_error = MT5Error(code=-1, message=msg, last_operation="connect")
        logger.warning("MT5 failure recorded: %s", self._stats.last_error.message)

    # -- convenience ------------------------------------------------------

    def login(
        self,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
    ) -> bool:
        """Synchronous login using connector."""
        return self._connector.login(login=login, password=password, server=server)

    def get_account_info(self) -> dict[str, Any] | None:
        return self._connector.account_info()

    def get_positions(self) -> list[dict[str, Any]]:
        return self._connector.positions()

    def health_sync(self) -> MT5Health:
        """Synchronous health check (non-async)."""
        health = self._connector.health_check()
        self._last_health_check = health
        return health


# Singleton manager for convenience
_default_manager: MT5ConnectionManager | None = None


def get_connection_manager(config: MT5Config | None = None) -> MT5ConnectionManager:
    """Get or create the default connection manager."""
    global _default_manager
    if _default_manager is None or _default_manager._state == ConnectionState.DISCONNECTED:
        _default_manager = MT5ConnectionManager(config=config or MT5Config())
    return _default_manager
