# -*- coding: utf-8 -*-
"""Tests for Observability Dashboard 2.0 (Phase 49)."""

from src.observability.dashboard_v2 import (
    NO_DATA,
    NOT_CONFIGURED,
    SECTIONS,
    UNAVAILABLE,
    DashboardAggregator,
)


def test_all_sections_present() -> None:
    assert len(SECTIONS) == 16
    agg = DashboardAggregator()
    payload = agg.build()
    assert payload["count"] == 16
    names = [s["section"] for s in payload["sections"]]
    assert names == list(SECTIONS)


def test_unconfigured_sections_report_not_configured() -> None:
    agg = DashboardAggregator()
    section = agg.section("market")
    # market provider not configured → explicit status, never a fake value.
    assert section["available"] is False
    assert section["status"] == NOT_CONFIGURED


def test_no_data_when_provider_returns_none() -> None:
    agg = DashboardAggregator(providers={"market": lambda: None})
    section = agg.section("market")
    assert section["available"] is False
    assert section["status"] == NO_DATA


def test_available_section_returns_value() -> None:
    agg = DashboardAggregator(providers={"risk": lambda: {"level": "NORMAL"}})
    section = agg.section("risk")
    assert section["available"] is True
    assert section["value"] == {"level": "NORMAL"}


def test_provider_error_is_unavailable_not_zero() -> None:
    def boom() -> dict:
        raise RuntimeError("boom")

    agg = DashboardAggregator(providers={"orders": boom})
    section = agg.section("orders")
    assert section["available"] is False
    assert section["status"] == UNAVAILABLE
    # Crucially: no fake "0" appears.
    assert "value" not in section


def test_unknown_section_returns_none() -> None:
    agg = DashboardAggregator()
    assert agg.section("nope") is None


def test_no_fake_zeros_principle() -> None:
    # A dashboard built with no providers must not contain any healthy-looking
    # zero/default values — every section must be explicitly unavailable.
    agg = DashboardAggregator()
    payload = agg.build()
    for section in payload["sections"]:
        assert section["available"] is False
        assert section["status"] in {NOT_CONFIGURED, NO_DATA, UNAVAILABLE}
