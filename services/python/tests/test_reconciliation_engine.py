# -*- coding: utf-8 -*-
"""Tests for the full reconciliation engine — PRD_V2 §14 Reconciliation.

Compares internal state against MT5 (broker) state across positions and orders,
detecting matched items, missing items on either side, lot/volume mismatches,
SL/TP mismatches, symbol mismatches, magic-number mismatches, and orphan orders.
Output must be deterministic (sorted) and expose a ``has_critical()`` helper.
"""

from __future__ import annotations

import pytest

from execution.reconciliation import Reconciler, ReconciliationReport


def _pos(ticket, symbol="EURUSD", volume=0.1, sl=1.0, tp=2.0, magic=100, side="BUY"):
    return {
        "ticket": ticket,
        "symbol": symbol,
        "volume": volume,
        "sl": sl,
        "tp": tp,
        "magic": magic,
        "side": side,
    }


def _order(ticket, symbol="EURUSD", volume=0.1, sl=1.0, tp=2.0, magic=100, status="OPEN"):
    return {
        "ticket": ticket,
        "symbol": symbol,
        "volume": volume,
        "sl": sl,
        "tp": tp,
        "magic": magic,
        "status": status,
    }


class TestCleanMatch:
    def test_clean_match_has_no_differences(self) -> None:
        internal = [_pos(1), _pos(2)]
        broker = [_pos(1), _pos(2)]
        report = Reconciler().compare(internal, broker, [], [])
        assert report.matched == [1, 2]
        assert report.has_critical() is False
        assert report.total_mismatches() == 0


class TestMissingItems:
    def test_missing_in_broker(self) -> None:
        report = Reconciler().compare([_pos(1)], [], [], [])
        assert report.missing_in_broker == [1]
        assert report.has_critical() is True

    def test_missing_internal(self) -> None:
        report = Reconciler().compare([], [_pos(9)], [], [])
        assert report.missing_internal == [9]
        assert report.has_critical() is True


class TestFieldMismatches:
    def test_volume_mismatch(self) -> None:
        report = Reconciler().compare([_pos(1, volume=0.1)], [_pos(1, volume=0.2)], [], [])
        assert any(m.ticket == 1 for m in report.volume_mismatches)
        assert report.has_critical() is True

    def test_sl_tp_mismatch(self) -> None:
        report = Reconciler().compare([_pos(1, sl=1.0, tp=2.0)], [_pos(1, sl=1.1, tp=2.2)], [], [])
        assert any(m.ticket == 1 for m in report.sltp_mismatches)

    def test_symbol_mismatch(self) -> None:
        report = Reconciler().compare(
            [_pos(1, symbol="EURUSD")], [_pos(1, symbol="GBPUSD")], [], []
        )
        assert any(m.ticket == 1 for m in report.symbol_mismatches)

    def test_magic_mismatch(self) -> None:
        report = Reconciler().compare([_pos(1, magic=100)], [_pos(1, magic=999)], [], [])
        assert any(m.ticket == 1 for m in report.magic_mismatches)


class TestOrdersAndOrphans:
    def test_order_missing_in_broker(self) -> None:
        report = Reconciler().compare([], [], [_order(5)], [])
        assert 5 in report.missing_in_broker
        assert report.has_critical() is True

    def test_orphan_broker_order(self) -> None:
        # An order the broker holds but the internal system does not.
        report = Reconciler().compare([], [], [], [_order(7)])
        assert report.orphan_orders == [7]
        assert report.has_critical() is True

    def test_matched_orders(self) -> None:
        report = Reconciler().compare([], [], [_order(3)], [_order(3)])
        assert 3 in report.matched_orders


class TestDeterminism:
    def test_output_is_sorted(self) -> None:
        internal = [_pos(3), _pos(1)]
        broker = [_pos(1)]
        report = Reconciler().compare(internal, broker, [], [])
        assert report.matched == sorted(report.matched)
        assert report.missing_in_broker == sorted(report.missing_in_broker)

    def test_repeated_calls_identical(self) -> None:
        args = ([_pos(3), _pos(1)], [_pos(2)], [], [_order(9)])
        a = Reconciler().compare(*args)
        b = Reconciler().compare(*args)
        assert a.to_dict() == b.to_dict()


class TestSerialisation:
    def test_to_dict_shape(self) -> None:
        report = Reconciler().compare([_pos(1)], [_pos(1)], [], [])
        assert isinstance(report, ReconciliationReport)
        payload = report.to_dict()
        for key in (
            "matched",
            "missing_in_broker",
            "missing_internal",
            "volume_mismatches",
            "sltp_mismatches",
            "symbol_mismatches",
            "magic_mismatches",
            "orphan_orders",
            "critical",
        ):
            assert key in payload


class TestAcceptsObjects:
    def test_accepts_object_positions(self) -> None:
        class P:
            def __init__(self, ticket, symbol, volume, sl, tp, magic):
                self.ticket = ticket
                self.symbol = symbol
                self.volume = volume
                self.sl = sl
                self.tp = tp
                self.magic = magic

        internal = [P(1, "EURUSD", 0.1, 1.0, 2.0, 100)]
        broker = [P(1, "EURUSD", 0.1, 1.0, 2.0, 100)]
        report = Reconciler().compare(internal, broker, [], [])
        assert report.matched == [1]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
