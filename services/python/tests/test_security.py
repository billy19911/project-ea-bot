# -*- coding: utf-8 -*-
"""Tests for security module — EPIC 17.

Covers tool permissions (17.06) and tamper-evident audit
protection (17.07).
"""

import pytest

from src.security import (
    AuditIntegrityError,
    ProtectedAuditLog,
    ToolPermissionError,
    ToolPermissionRegistry,
)


class TestToolPermissionRegistry:
    """17.06 Tool permissions."""

    def test_register_and_check_tool(self) -> None:
        reg = ToolPermissionRegistry()
        reg.register_tool("mt5.execute_order", required_permission="SEND_TO_MT5")
        assert reg.check(agent_permissions=["SEND_TO_MT5"], tool="mt5.execute_order") is True

    def test_denies_without_permission(self) -> None:
        reg = ToolPermissionRegistry()
        reg.register_tool("mt5.execute_order", required_permission="SEND_TO_MT5")
        assert reg.check(agent_permissions=["ANALYZE"], tool="mt5.execute_order") is False

    def test_require_raises_on_denied(self) -> None:
        reg = ToolPermissionRegistry()
        reg.register_tool("telegram.send", required_permission="SEND_TELEGRAM")
        with pytest.raises(ToolPermissionError) as exc:
            reg.require(agent_name="analyst", agent_permissions=[], tool="telegram.send")
        assert "telegram.send" in str(exc.value)

    def test_unknown_tool_is_denied(self) -> None:
        reg = ToolPermissionRegistry()
        with pytest.raises(ToolPermissionError):
            reg.require(agent_name="a", agent_permissions=["X"], tool="not.registered")

    def test_list_tools_for_agent(self) -> None:
        reg = ToolPermissionRegistry()
        reg.register_tool("t1", required_permission="P1")
        reg.register_tool("t2", required_permission="P2")
        reg.register_tool("t3", required_permission="P1")
        allowed = reg.list_tools(agent_permissions=["P1"])
        assert sorted(allowed) == ["t1", "t3"]

    def test_wildcard_permission_grants_all(self) -> None:
        reg = ToolPermissionRegistry()
        reg.register_tool("dangerous.tool", required_permission="ADMIN")
        assert reg.check(agent_permissions=["*"], tool="dangerous.tool") is True

    def test_duplicate_registration_rejected(self) -> None:
        reg = ToolPermissionRegistry()
        reg.register_tool("t", required_permission="P")
        with pytest.raises(ValueError):
            reg.register_tool("t", required_permission="Q")


class TestProtectedAuditLog:
    """17.07 Audit protection (tamper-evident hash chain)."""

    def test_append_and_verify_clean_chain(self) -> None:
        log = ProtectedAuditLog()
        log.append(actor="supervisor", action="decision.approve", target="DEC-1")
        log.append(actor="execution", action="order.send", target="ORD-1")
        ok, broken_at = log.verify()
        assert ok is True
        assert broken_at is None

    def test_entries_have_chained_hashes(self) -> None:
        log = ProtectedAuditLog()
        e1 = log.append(actor="a", action="x", target="t1")
        e2 = log.append(actor="b", action="y", target="t2")
        assert e1.prev_hash == log.genesis_hash
        assert e2.prev_hash == e1.hash

    def test_tamper_detected(self) -> None:
        log = ProtectedAuditLog()
        log.append(actor="a", action="x", target="t1")
        entry = log.append(actor="b", action="y", target="t2")
        log.append(actor="c", action="z", target="t3")
        # Tamper: modify an entry in place
        entry.action = "forged.action"
        ok, broken_at = log.verify()
        assert ok is False
        assert broken_at == 1

    def test_removal_detected(self) -> None:
        log = ProtectedAuditLog()
        log.append(actor="a", action="x", target="t1")
        log.append(actor="b", action="y", target="t2")
        log.append(actor="c", action="z", target="t3")
        del log._entries[1]  # simulate deletion
        ok, broken_at = log.verify()
        assert ok is False
        assert broken_at is not None

    def test_verify_or_raise(self) -> None:
        log = ProtectedAuditLog()
        log.append(actor="a", action="x", target="t1")
        entry = log.append(actor="b", action="y", target="t2")
        entry.target = "hacked"
        with pytest.raises(AuditIntegrityError):
            log.verify_or_raise()

    def test_append_only_no_mutation_api(self) -> None:
        log = ProtectedAuditLog()
        log.append(actor="a", action="x", target="t1")
        # No public API to delete/modify entries
        assert not hasattr(log, "delete")
        assert not hasattr(log, "update")
        assert not hasattr(log, "remove")

    def test_export_entries(self) -> None:
        log = ProtectedAuditLog()
        log.append(actor="a", action="x", target="t1")
        exported = log.entries()
        assert len(exported) == 1
        assert exported[0]["actor"] == "a"
        assert "hash" in exported[0]

    def test_chain_survives_export_import(self) -> None:
        log = ProtectedAuditLog()
        log.append(actor="a", action="x", target="t1")
        log.append(actor="b", action="y", target="t2")
        exported = log.entries()
        restored = ProtectedAuditLog.from_entries(exported)
        ok, _ = restored.verify()
        assert ok is True

    def test_empty_log_verifies(self) -> None:
        log = ProtectedAuditLog()
        ok, broken_at = log.verify()
        assert ok is True
        assert broken_at is None

    def test_genesis_hash_is_deterministic(self) -> None:
        a = ProtectedAuditLog()
        b = ProtectedAuditLog()
        assert a.genesis_hash == b.genesis_hash
