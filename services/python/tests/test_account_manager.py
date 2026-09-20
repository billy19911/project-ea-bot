# -*- coding: utf-8 -*-
"""Tests for Multi-Account / Multi-Broker Foundation (Phase 53)."""

import pytest

from src.live_readiness.account_manager import Account, AccountManager, Broker, ExecutionContext


def _manager() -> AccountManager:
    mgr = AccountManager()
    mgr.add_broker(Broker("B1", "Broker One", "srv1"))
    mgr.add_broker(Broker("B2", "Broker Two", "srv2"))
    mgr.add_account(Account("A1", "B1", "1001", terminal_id="T1", symbol_spec_id="S1"))
    mgr.add_account(Account("A2", "B1", "1002", terminal_id="T2", symbol_spec_id="S1"))
    mgr.add_account(Account("A3", "B2", "2001", terminal_id="T3", symbol_spec_id="S2"))
    return mgr


def test_accounts_grouped_by_broker() -> None:
    mgr = _manager()
    assert [a.account_id for a in mgr.accounts_for_broker("B1")] == ["A1", "A2"]
    assert [a.account_id for a in mgr.accounts_for_broker("B2")] == ["A3"]


def test_execution_context_complete() -> None:
    mgr = _manager()
    ctx = mgr.execution_context("A1")
    assert isinstance(ctx, ExecutionContext)
    assert ctx.broker_id == "B1"
    assert ctx.account_id == "A1"
    assert ctx.terminal_id == "T1"
    assert ctx.symbol_spec_id == "S1"
    assert ctx.is_complete()


def test_execution_context_symbol_override() -> None:
    mgr = _manager()
    ctx = mgr.execution_context("A1", symbol_spec_id="OVERRIDE")
    assert ctx.symbol_spec_id == "OVERRIDE"


def test_unknown_account_rejected() -> None:
    mgr = _manager()
    with pytest.raises(ValueError):
        mgr.execution_context("NOPE")


def test_cannot_add_account_to_unknown_broker() -> None:
    mgr = AccountManager()
    with pytest.raises(ValueError):
        mgr.add_account(Account("A1", "MISSING", "1"))


def test_duplicate_account_rejected() -> None:
    mgr = _manager()
    with pytest.raises(ValueError):
        mgr.add_account(Account("A1", "B1", "9999"))


def test_incomplete_identity_rejected() -> None:
    mgr = AccountManager()
    mgr.add_broker(Broker("B1", "B1"))
    # No terminal_id and no symbol_spec_id → incomplete identity.
    mgr.add_account(Account("A1", "B1", "1001"))
    with pytest.raises(ValueError):
        mgr.execution_context("A1")


def test_execution_context_has_all_required_fields() -> None:
    mgr = _manager()
    ctx = mgr.execution_context("A3")
    d = ctx.to_dict()
    for key in ("broker_id", "account_id", "terminal_id", "symbol_spec_id"):
        assert key in d
