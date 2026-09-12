# -*- coding: utf-8 -*-
"""MT5 connector — wraps the existing paper/live connector with a class interface.

Re-exports the existing functions and adds the MT5Connector class
with health check and error tracking.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from typing import Any

from .connector import (  # noqa: F401  (re-exported)
    SIMULATED_PRICES,
    SIMULATED_SYMBOLS,
    execute_order,
    get_account_info,
    get_ohlc,
    get_orders,
    get_positions,
    get_symbol_info,
    get_symbols,
    get_tick,
    is_live_mode,
    shutdown,
    use_live_mode,
)

__all__ = [
    "MT5Config",
    "MT5Health",
    "MT5Error",
    "MT5Connector",
    # re-export existing module API
    "SIMULATED_PRICES",
    "SIMULATED_SYMBOLS",
    "get_account_info",
    "get_symbols",
    "get_tick",
    "get_ohlc",
    "get_positions",
    "get_orders",
    "execute_order",
    "use_live_mode",
    "is_live_mode",
    "shutdown",
]


@dataclass
class MT5Config:
    terminal_path: str = ""
    login: int = 0
    password: str = ""
    server: str = ""
    timeout_ms: int = 5000
    max_retries: int = 3
    retry_delay_s: float = 1.0


@dataclass
class MT5Health:
    connected: bool = False
    authenticated: bool = False
    login: int = 0
    server: str = ""
    balance: float = 0.0
    equity: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None


@dataclass
class MT5Error:
    code: int
    message: str
    last_operation: str = ""


class MT5Connector:
    """Class-based wrapper around the existing MT5 connector functions."""

    def __init__(self, config: MT5Config) -> None:
        self._config = config
        self._last_error: MT5Error | None = None

    def initialise(self) -> bool:
        self._last_error = None
        if self._config.terminal_path and self._config.login and self._config.password:
            ok = use_live_mode(
                terminal_path=self._config.terminal_path,
                login=self._config.login,
                password=self._config.password,
                server=self._config.server,
            )
            if ok:
                return True
            self._capture_error("initialise", "live mode initialise failed")
            return False
        return True

    def shutdown(self) -> None:
        try:
            shutdown()
        except Exception:
            pass

    def login(
        self, login: int | None = None, password: str | None = None, server: str | None = None
    ) -> bool:
        login = login or self._config.login
        password = password or self._config.password
        server = server or self._config.server
        for attempt in range(1, self._config.max_retries + 1):
            ok = use_live_mode(
                terminal_path=self._config.terminal_path,
                login=int(login),
                password=password,
                server=server,
            )
            if ok:
                self._last_error = None
                return True
            self._capture_error(f"login (attempt {attempt})", "login failed")
            if attempt < self._config.max_retries:
                _time.sleep(self._config.retry_delay_s)
        return False

    def logout(self) -> None:
        try:
            shutdown()
        except Exception:
            pass

    def health_check(self) -> MT5Health:
        result = MT5Health()
        try:
            account = get_account_info()
        except Exception as exc:
            result.error = f"account_info failed: {exc}"
            self._capture_error("health_check", result.error)
            return result
        result.connected = True
        result.authenticated = True
        result.login = account.login
        result.server = account.server
        result.balance = float(account.balance)
        result.equity = float(account.equity)
        return result

    def positions(self) -> list[dict[str, Any]]:
        raw = get_positions()
        return [self._position_to_dict(p) for p in raw] if raw else []

    def account_info(self) -> dict[str, Any] | None:
        try:
            account = get_account_info()
            return {
                "login": account.login,
                "server": account.server,
                "balance": float(account.balance),
                "equity": float(account.equity),
                "margin": float(account.margin),
                "free_margin": float(account.free_margin),
                "leverage": account.leverage,
                "name": account.name,
            }
        except Exception:
            return None

    @property
    def last_error(self) -> MT5Error | None:
        return self._last_error

    def _capture_error(self, operation: str, message: str) -> None:
        self._last_error = MT5Error(code=-1, message=message, last_operation=operation)

    @staticmethod
    def _position_to_dict(pos: Any) -> dict[str, Any]:
        return {
            "ticket": getattr(pos, "ticket", 0),
            "symbol": getattr(pos, "symbol", ""),
            "volume": getattr(pos, "quantity", getattr(pos, "volume", 0)),
            "type": getattr(pos, "side", "buy"),
            "price_open": getattr(pos, "price_open", 0),
            "price_current": getattr(pos, "price_current", 0),
            "profit": getattr(pos, "profit", 0),
            "sl": getattr(pos, "sl", 0),
            "tp": getattr(pos, "tp", 0),
        }
