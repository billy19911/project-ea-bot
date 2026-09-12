# -*- coding: utf-8 -*-
"""Tests for the Money Manager (Phase 11)."""

from __future__ import annotations

import pytest

from risk.money_management import MoneyManager, PositionSizeResult


class TestPositionSizeResult:
    """Tests for PositionSizeResult dataclass."""

    def test_default_values(self) -> None:
        """Test default PositionSizeResult values."""
        result = PositionSizeResult()
        assert result.lot_size == 0.0
        assert result.risk_amount == 0.0
        assert result.sl_pips == 0.0
        assert result.tp_pips == 0.0
        assert result.rr_ratio == 0.0
        assert result.sl_price == 0.0
        assert result.tp_price == 0.0

    def test_custom_values(self) -> None:
        """Test PositionSizeResult with custom values."""
        result = PositionSizeResult(
            lot_size=0.1,
            risk_amount=50.0,
            sl_pips=50.0,
            tp_pips=100.0,
            rr_ratio=2.0,
            sl_price=1.1000,
            tp_price=1.1100,
        )
        assert result.lot_size == 0.1
        assert result.risk_amount == 50.0
        assert result.sl_pips == 50.0
        assert result.tp_pips == 100.0
        assert result.rr_ratio == 2.0
        assert result.sl_price == 1.1000
        assert result.tp_price == 1.1100


class TestCalculateLotSize:
    """Tests for MoneyManager.calculate_lot_size."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mm = MoneyManager()

    def test_basic_lot_calculation(self) -> None:
        """Test basic lot size calculation."""
        # balance=10000, risk_pct=1% = 100 risk, sl=100 pips,
        # point_value=0.0001 (standard), contract_size=100000
        # lot = 100 / (100 * 0.0001 * 100000) = 0.1
        result = self.mm.calculate_lot_size(
            balance=10000.0,
            risk_pct=0.01,
            sl_pips=100.0,
            point_value=0.0001,
            contract_size=100000,
        )
        assert result.lot_size == pytest.approx(0.1)
        assert result.risk_amount == pytest.approx(100.0)
        assert result.sl_pips == 100.0

    def test_zero_sl_pips_raises(self) -> None:
        """Test that zero SL pips raises ValueError."""
        with pytest.raises(ValueError, match="sl_pips must be positive"):
            self.mm.calculate_lot_size(10000.0, 0.01, 0.0, 0.0001)

    def test_negative_sl_pips_raises(self) -> None:
        """Test that negative SL pips raises ValueError."""
        with pytest.raises(ValueError, match="sl_pips must be positive"):
            self.mm.calculate_lot_size(10000.0, 0.01, -10.0, 0.0001)

    def test_zero_risk_pct_returns_zero(self) -> None:
        """Test zero risk percentage returns zero lot size."""
        result = self.mm.calculate_lot_size(10000.0, 0.0, 50.0, 0.0001)
        assert result.lot_size == 0.0
        assert result.risk_amount == 0.0

    def test_high_risk_pct_large_lot(self) -> None:
        """Test high risk percentage produces proportionally larger lot."""
        result = self.mm.calculate_lot_size(
            balance=10000.0,
            risk_pct=0.02,
            sl_pips=50.0,
            point_value=0.0001,
            contract_size=100000,
        )
        # 10000 * 0.02 = 200 risk; 50 * 0.0001 * 100000 = 500 per lot
        # lot = 200 / 500 = 0.4
        assert result.lot_size == pytest.approx(0.4)
        assert result.risk_amount == pytest.approx(200.0)

    def test_equity_used_when_provided(self) -> None:
        """Test that equity overrides balance when provided."""
        result = self.mm.calculate_lot_size(
            balance=10000.0,
            risk_pct=0.01,
            sl_pips=100.0,
            point_value=0.0001,
            contract_size=100000,
            equity=9000.0,
        )
        # Should use equity (9000) * 0.01 = 90 risk
        assert result.risk_amount == pytest.approx(90.0)
        assert result.lot_size == pytest.approx(0.09)


class TestCalculateSLTP:
    """Tests for MoneyManager.calculate_sl_tp."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mm = MoneyManager()

    def test_long_atr_based_sl_tp(self) -> None:
        """Test SL/TP calculation for long position using ATR."""
        # entry=1.1000, atr=0.0100, sl_mult=1.5, tp_mult=3.0
        # SL = 1.1000 - 1.5*0.0100 = 1.0850
        # TP = 1.1000 + 3.0*0.0100 = 1.1300
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=1.1000,
            direction="long",
            atr_value=0.0100,
        )
        assert sl == pytest.approx(1.0850)
        assert tp == pytest.approx(1.1300)

    def test_short_atr_based_sl_tp(self) -> None:
        """Test SL/TP calculation for short position using ATR."""
        # entry=1.1000, atr=0.0100, sl_mult=1.5, tp_mult=3.0
        # SL = 1.1000 + 1.5*0.0100 = 1.1150
        # TP = 1.1000 - 3.0*0.0100 = 1.0700
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=1.1000,
            direction="short",
            atr_value=0.0100,
        )
        assert sl == pytest.approx(1.1150)
        assert tp == pytest.approx(1.0700)

    def test_fixed_pips_sl_tp_long(self) -> None:
        """Test SL/TP calculation using fixed pips for long position."""
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=1.1000,
            direction="long",
            pips=50,
            point_value=0.0001,
        )
        # SL = 1.1000 - 50*0.0001 = 1.0950
        # TP = 1.1000 + 50*3.0*0.0001 = 1.1150 (3:1 default)
        assert sl == pytest.approx(1.0950)
        assert tp == pytest.approx(1.1150)

    def test_custom_multipliers(self) -> None:
        """Test SL/TP with custom multipliers."""
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=1.1000,
            direction="long",
            atr_value=0.0100,
            sl_multiplier=2.0,
            tp_multiplier=4.0,
        )
        assert sl == pytest.approx(1.0800)  # 1.1000 - 2*0.01
        assert tp == pytest.approx(1.1400)  # 1.1000 + 4*0.01

    def test_invalid_direction_raises(self) -> None:
        """Test invalid direction raises ValueError."""
        with pytest.raises(ValueError, match="direction must be 'long' or 'short'"):
            self.mm.calculate_sl_tp(1.1000, "sideways")

    def test_no_atr_no_pips_raises(self) -> None:
        """Test ValueError when neither ATR nor pips provided."""
        with pytest.raises(ValueError, match="either atr_value or pips"):
            self.mm.calculate_sl_tp(1.1000, "long")


class TestValidateRRRatio:
    """Tests for MoneyManager.validate_rr_ratio."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mm = MoneyManager()

    def test_valid_rr_ratio(self) -> None:
        """Test valid R:R ratio passes validation."""
        # long: entry=100, sl=90, tp=120
        # risk = 100-90 = 10, reward = 120-100 = 20, R:R = 2.0
        is_valid, actual_rr = self.mm.validate_rr_ratio(100.0, 90.0, 120.0)
        assert is_valid is True
        assert actual_rr == pytest.approx(2.0)

    def test_invalid_rr_ratio(self) -> None:
        """Test R:R below threshold fails validation."""
        # entry=100, sl=90, tp=98 → risk=10, reward=2, R:R=0.2
        is_valid, actual_rr = self.mm.validate_rr_ratio(
            100.0,
            90.0,
            98.0,
            min_rr=1.5,
        )
        assert is_valid is False
        assert actual_rr == pytest.approx(0.2)

    def test_short_position_rr(self) -> None:
        """Test R:R calculation for short position."""
        # short: entry=100, sl=110, tp=80
        # risk = 110-100 = 10, reward = 100-80 = 20, R:R = 2.0
        is_valid, actual_rr = self.mm.validate_rr_ratio(100.0, 110.0, 80.0)
        assert is_valid is True
        assert actual_rr == pytest.approx(2.0)

    def test_rr_at_threshold(self) -> None:
        """Test R:R exactly at threshold passes."""
        # risk=10, reward=20, R:R=2.0 >= 2.0
        is_valid, actual_rr = self.mm.validate_rr_ratio(
            100.0,
            90.0,
            120.0,
            min_rr=2.0,
        )
        assert is_valid is True
        assert actual_rr == pytest.approx(2.0)

    def test_zero_sl_distance_raises(self) -> None:
        """Test ValueError when SL equals entry (zero risk)."""
        with pytest.raises(ValueError, match="stop loss cannot equal entry"):
            self.mm.validate_rr_ratio(100.0, 100.0, 120.0)


class TestCapLotSize:
    """Tests for MoneyManager.cap_lot_size."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mm = MoneyManager()

    def test_lot_within_per_trade_limit(self) -> None:
        """Test lot size within per-trade limit is unchanged."""
        capped = self.mm.cap_lot_size(0.5, max_lot_per_trade=1.0)
        assert capped == 0.5

    def test_lot_exceeds_per_trade_limit(self) -> None:
        """Test lot size exceeding per-trade limit is capped."""
        capped = self.mm.cap_lot_size(2.0, max_lot_per_trade=1.0)
        assert capped == 1.0

    def test_lot_exceeds_total_limit(self) -> None:
        """Test lot size exceeding total exposure limit is capped."""
        # calculated=2.0, current_total=3.0, max_total=5.0
        # remaining = 5.0 - 3.0 = 2.0 → cap to 2.0
        capped = self.mm.cap_lot_size(
            3.0,
            max_lot_per_trade=10.0,
            current_total_lots=3.0,
            max_total_lots=5.0,
        )
        assert capped == pytest.approx(2.0)

    def test_lot_capped_by_both_limits(self) -> None:
        """Test lot size capped by the more restrictive of two limits."""
        # calculated=10.0, per_trade=1.0, total allows 5.0 → cap to 1.0
        capped = self.mm.cap_lot_size(
            10.0,
            max_lot_per_trade=1.0,
            current_total_lots=1.0,
            max_total_lots=5.0,
        )
        assert capped == 1.0

    def test_total_exceeded_returns_zero(self) -> None:
        """Test lot size returns 0 when total already at max."""
        capped = self.mm.cap_lot_size(
            1.0,
            max_lot_per_trade=1.0,
            current_total_lots=5.0,
            max_total_lots=5.0,
        )
        assert capped == 0.0

    def test_no_lot_returns_zero(self) -> None:
        """Test zero calculated lot returns zero."""
        capped = self.mm.cap_lot_size(0.0)
        assert capped == 0.0


class TestIntegration:
    """Integration tests combining multiple MoneyManager methods."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mm = MoneyManager()

    def test_full_position_workflow(self) -> None:
        """Test full workflow: lot calc → SL/TP → R:R → cap."""
        # 1. Calculate lot size
        result = self.mm.calculate_lot_size(
            balance=10000.0,
            risk_pct=0.01,
            sl_pips=50.0,
            point_value=0.0001,
            contract_size=100000,
        )
        assert result.lot_size > 0

        # 2. Calculate SL/TP
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=1.1000,
            direction="long",
            atr_value=0.0100,
            sl_multiplier=1.5,
            tp_multiplier=3.0,
        )

        # 3. Validate R:R
        is_valid, rr = self.mm.validate_rr_ratio(
            entry_price=1.1000,
            sl_price=sl,
            tp_price=tp,
            min_rr=1.5,
        )
        assert is_valid is True
        assert rr == pytest.approx(2.0)  # 3.0/1.5

        # 4. Cap lot size
        capped = self.mm.cap_lot_size(result.lot_size, max_lot_per_trade=1.0)
        assert capped <= 1.0
