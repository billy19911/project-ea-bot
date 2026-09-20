# -*- coding: utf-8 -*-
"""Multi-Account / Multi-Broker Foundation — PRD_V2 §53.

The scalability layer *after* single-account is stable. Provides an Account
Manager that groups accounts under brokers and guarantees every execution
carries the four identity fields the PRD requires::

    broker_id, account_id, terminal_id, symbol_spec_id

Multi-broker is explicitly **not** a blocker for single-broker production
(PRD §53) — this module is additive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

__all__ = [
    "Broker",
    "Account",
    "ExecutionContext",
    "AccountManager",
]


@dataclass(frozen=True)
class Broker:
    """A broker definition (PRD §53)."""

    broker_id: str
    name: str
    server: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"broker_id": self.broker_id, "name": self.name, "server": self.server}


@dataclass
class Account:
    """An account belonging to a broker (PRD §53)."""

    account_id: str
    broker_id: str
    login: str
    terminal_id: str = ""
    symbol_spec_id: str = ""
    environment: str = "DEMO"

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "broker_id": self.broker_id,
            "login": self.login,
            "terminal_id": self.terminal_id,
            "symbol_spec_id": self.symbol_spec_id,
            "environment": self.environment,
        }


@dataclass(frozen=True)
class ExecutionContext:
    """The mandatory identity block on every execution (PRD §53)."""

    broker_id: str
    account_id: str
    terminal_id: str
    symbol_spec_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "broker_id": self.broker_id,
            "account_id": self.account_id,
            "terminal_id": self.terminal_id,
            "symbol_spec_id": self.symbol_spec_id,
        }

    def is_complete(self) -> bool:
        return all([self.broker_id, self.account_id, self.terminal_id, self.symbol_spec_id])


class AccountManager:
    """Registry of brokers and their accounts (PRD §53)."""

    def __init__(self) -> None:
        self._brokers: dict[str, Broker] = {}
        self._accounts: dict[str, Account] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def add_broker(self, broker: Broker) -> Broker:
        self._brokers[broker.broker_id] = broker
        return broker

    def add_account(self, account: Account) -> Account:
        if account.broker_id not in self._brokers:
            raise ValueError(f"Unknown broker: {account.broker_id}")
        if account.account_id in self._accounts:
            raise ValueError(f"Account already registered: {account.account_id}")
        self._accounts[account.account_id] = account
        return account

    def get_account(self, account_id: str) -> Optional[Account]:
        return self._accounts.get(account_id)

    def accounts_for_broker(self, broker_id: str) -> list[Account]:
        return [a for a in self._accounts.values() if a.broker_id == broker_id]

    # ------------------------------------------------------------------
    # Execution identity
    # ------------------------------------------------------------------
    def execution_context(self, account_id: str, symbol_spec_id: str = "") -> ExecutionContext:
        """Build the mandatory execution context for *account_id*.

        ``symbol_spec_id`` may be supplied per-call (per-symbol) or fall back to
        the account default. Missing identity fields raise — an execution
        without full identity must never proceed.
        """
        account = self._accounts.get(account_id)
        if account is None:
            raise ValueError(f"Unknown account: {account_id}")
        ctx = ExecutionContext(
            broker_id=account.broker_id,
            account_id=account.account_id,
            terminal_id=account.terminal_id,
            symbol_spec_id=symbol_spec_id or account.symbol_spec_id,
        )
        if not ctx.is_complete():
            raise ValueError(f"Incomplete execution identity for {account_id}: {ctx.to_dict()}")
        return ctx

    def to_dict(self) -> dict[str, Any]:
        return {
            "brokers": [b.to_dict() for b in self._brokers.values()],
            "accounts": [a.to_dict() for a in self._accounts.values()],
        }
