# -*- coding: utf-8 -*-
"""Tests for MT5 symbol auto-resolution (broker suffix detection)."""

from __future__ import annotations

from src.mt5.symbol_resolver import (
    cache_info,
    candidate_matches,
    clear_symbol_cache,
    resolve_symbol,
)


def test_exact_match_wins() -> None:
    symbols = ["XAUUSD", "XAUUSDc", "EURUSD"]
    assert candidate_matches("XAUUSD", symbols)[0] == "XAUUSD"


def test_suffix_variant_detected() -> None:
    symbols = ["XAUUSDc", "XAUUSD247c", "EURUSD"]
    matches = candidate_matches("XAUUSD", symbols)
    assert matches[0] == "XAUUSDc"


def test_suffix_247c_when_no_plain_c() -> None:
    symbols = ["XAUUSD247c", "EURUSD"]
    assert candidate_matches("XAUUSD", symbols)[0] == "XAUUSD247c"


def test_raw_suffix() -> None:
    symbols = ["XAUUSD.raw", "EURUSD"]
    assert candidate_matches("XAUUSD", symbols)[0] == "XAUUSD.raw"


def test_normalised_match() -> None:
    symbols = ["XAU-USD", "EURUSD"]
    assert "XAU-USD" in candidate_matches("XAUUSD", symbols)


def test_no_match_returns_empty() -> None:
    assert candidate_matches("XAUUSD", ["EURUSD", "GBPUSD"]) == []


def test_empty_base() -> None:
    assert candidate_matches("", ["XAUUSD"]) == []


def test_shortest_startswith_preferred() -> None:
    symbols = ["XAUUSDmicro", "XAUUSDc", "XAUUSD247c"]
    # "XAUUSDc" is the shortest startswith → best.
    assert candidate_matches("XAUUSD", symbols)[0] == "XAUUSDc"


def test_resolve_returns_base_when_no_live() -> None:
    clear_symbol_cache()
    # Not in live mode → resolution is a no-op passthrough.
    assert resolve_symbol("XAUUSD") == "XAUUSD"


def test_cache_cleared() -> None:
    clear_symbol_cache()
    assert cache_info() == {}
