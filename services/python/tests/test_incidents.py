# -*- coding: utf-8 -*-
"""Tests for Incident Management (Phase 55)."""

from src.monitoring.incidents import IncidentManager, Severity


def test_open_incident_has_all_fields() -> None:
    mgr = IncidentManager()
    inc = mgr.open(
        severity=Severity.CRITICAL.value,
        component="reconciliation",
        trigger="mismatch detected",
        system_state="ENTRY_BLOCKED",
        action_taken="new entries blocked",
    )
    d = inc.to_dict()
    for key in (
        "incident_id",
        "severity",
        "detected_at",
        "component",
        "trigger",
        "system_state",
        "action_taken",
        "recovery_state",
        "resolved_at",
    ):
        assert key in d
    assert inc.is_open()
    assert d["resolved_at"] is None


def test_incident_id_sequence() -> None:
    mgr = IncidentManager()
    a = mgr.open("INFO", "x", "t")
    b = mgr.open("INFO", "x", "t")
    assert a.incident_id == "INC-0001"
    assert b.incident_id == "INC-0002"


def test_invalid_severity_rejected() -> None:
    mgr = IncidentManager()
    try:
        mgr.open("BOGUS", "x", "t")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_escalation_only_increases() -> None:
    mgr = IncidentManager()
    inc = mgr.open("WARNING", "mt5", "disconnect")
    inc.escalate("CRITICAL", "positions unresolved")
    assert inc.severity == "CRITICAL"
    # Attempt to de-escalate is ignored.
    inc.escalate("INFO", "try downgrade")
    assert inc.severity == "CRITICAL"


def test_record_action_and_resolve() -> None:
    mgr = IncidentManager()
    inc = mgr.open("HIGH", "db", "unavailable")
    inc.record_action("switched to read-only")
    inc.resolve("RECOVERED")
    assert not inc.is_open()
    assert inc.recovery_state == "RECOVERED"
    assert inc.resolved_at is not None


def test_has_critical_open() -> None:
    mgr = IncidentManager()
    assert mgr.has_critical_open() is False
    inc = mgr.open("CRITICAL", "recon", "mismatch")
    assert mgr.has_critical_open() is True
    inc.resolve()
    assert mgr.has_critical_open() is False


def test_emergency_counts_as_critical() -> None:
    mgr = IncidentManager()
    mgr.open("EMERGENCY", "system", "flatten")
    assert mgr.has_critical_open() is True


def test_open_incidents_filter() -> None:
    mgr = IncidentManager()
    mgr.open("INFO", "a", "t")
    inc2 = mgr.open("WARNING", "b", "t")
    inc2.resolve()
    assert len(mgr.open_incidents()) == 1


def test_by_severity() -> None:
    mgr = IncidentManager()
    mgr.open("WARNING", "a", "t")
    mgr.open("WARNING", "b", "t")
    mgr.open("INFO", "c", "t")
    assert len(mgr.by_severity("WARNING")) == 2
