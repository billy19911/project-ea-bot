# -*- coding: utf-8 -*-
"""Tests for the Risk Engine."""

from __future__ import annotations

from risk.base import RiskLevel, RiskMetrics, RiskThreshold
from risk.engine import RiskEngine


class TestRiskEngine:
    """Tests for RiskEngine class."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = RiskEngine(
            max_drawdown=0.15,
            daily_loss_limit=0.05,
            max_exposure=0.30,
            margin_threshold=0.20,
            max_positions=5,
            max_position_size=0.10,
        )

    def test_initialization_defaults(self) -> None:
        """Test default initialization."""
        engine = RiskEngine()
        assert engine.get_threshold(RiskThreshold.MAX_DRAWDOWN) == 0.15
        assert engine.get_threshold(RiskThreshold.DAILY_LOSS_LIMIT) == 0.05
        assert engine.get_threshold(RiskThreshold.MAX_EXPOSURE) == 0.30
        assert engine.get_threshold(RiskThreshold.MARGIN_THRESHOLD) == 0.20
        assert engine.get_threshold(RiskThreshold.MAX_POSITIONS) == 5
        assert engine.get_threshold(RiskThreshold.MAX_POSITION_SIZE) == 0.10

    def test_initialization_custom(self) -> None:
        """Test custom initialization."""
        engine = RiskEngine(
            max_drawdown=0.20,
            daily_loss_limit=0.10,
            max_exposure=0.50,
            margin_threshold=0.25,
            max_positions=10,
            max_position_size=0.20,
        )
        assert engine.get_threshold(RiskThreshold.MAX_DRAWDOWN) == 0.20
        assert engine.get_threshold(RiskThreshold.DAILY_LOSS_LIMIT) == 0.10
        assert engine.get_threshold(RiskThreshold.MAX_EXPOSURE) == 0.50
        assert engine.get_threshold(RiskThreshold.MARGIN_THRESHOLD) == 0.25
        assert engine.get_threshold(RiskThreshold.MAX_POSITIONS) == 10
        assert engine.get_threshold(RiskThreshold.MAX_POSITION_SIZE) == 0.20

    def test_calculate_account_risk_normal(self) -> None:
        """Test account risk calculation with normal values."""
        account_state = {
            "equity": 9500.0,
            "balance": 10000.0,
            "peak_equity": 10000.0,
            "daily_pnl": -200.0,
        }
        result = self.engine.calculate_account_risk(account_state)
        assert result["drawdown_pct"] == 0.05  # (10000 - 9500) / 10000
        assert result["daily_loss_pct"] == 0.02  # 200 / 10000
        assert result["equity"] == 9500.0
        assert result["balance"] == 10000.0

    def test_calculate_account_risk_zero_peak(self) -> None:
        """Test account risk with zero peak equity."""
        account_state = {
            "equity": 10000.0,
            "balance": 10000.0,
            "peak_equity": 0.0,
            "daily_pnl": 0.0,
        }
        result = self.engine.calculate_account_risk(account_state)
        assert result["drawdown_pct"] == 0.0

    def test_calculate_account_risk_positive_pnl(self) -> None:
        """Test account risk with positive daily P&L."""
        account_state = {
            "equity": 10500.0,
            "balance": 10000.0,
            "peak_equity": 10500.0,
            "daily_pnl": 500.0,
        }
        result = self.engine.calculate_account_risk(account_state)
        assert result["drawdown_pct"] == 0.0
        assert result["daily_loss_pct"] == 0.0  # No loss

    def test_calculate_position_risk_long(self) -> None:
        """Test position risk calculation for long position."""
        position = {
            "size": 1.0,
            "entry_price": 100.0,
            "current_price": 105.0,
            "side": "long",
            "stop_loss": 95.0,
        }
        result = self.engine.calculate_position_risk(position)
        assert result["pnl"] == 5.0  # (105 - 100) * 1
        assert result["risk_per_unit"] == 5.0  # 100 - 95
        assert result["risk_reward_ratio"] == 1.0  # 5 / 5
        assert result["position_value"] == 105.0
        assert result["unrealized_pnl_pct"] == 0.05

    def test_calculate_position_risk_short(self) -> None:
        """Test position risk calculation for short position."""
        position = {
            "size": 1.0,
            "entry_price": 100.0,
            "current_price": 95.0,
            "side": "short",
            "stop_loss": 105.0,
        }
        result = self.engine.calculate_position_risk(position)
        assert result["pnl"] == 5.0  # (100 - 95) * 1
        assert result["risk_per_unit"] == 5.0  # 105 - 100
        assert result["risk_reward_ratio"] == 1.0  # 5 / 5

    def test_calculate_position_risk_no_stop_loss(self) -> None:
        """Test position risk without stop loss."""
        position = {
            "size": 1.0,
            "entry_price": 100.0,
            "current_price": 105.0,
            "side": "long",
        }
        result = self.engine.calculate_position_risk(position)
        assert result["risk_per_unit"] == 0.0
        assert result["risk_reward_ratio"] == 0.0

    def test_calculate_portfolio_risk_empty(self) -> None:
        """Test portfolio risk with empty positions."""
        result = self.engine.calculate_portfolio_risk([], 10000.0)
        assert result["total_exposure_pct"] == 0.0
        assert result["correlation_risk"] == 0.0
        assert result["sector_concentration"] == 0.0
        assert result["leverage_used"] == 0.0
        assert result["total_notional"] == 0.0

    def test_calculate_portfolio_risk_multiple_positions(self) -> None:
        """Test portfolio risk with multiple positions."""
        positions = [
            {
                "size": 1.0,
                "current_price": 100.0,
                "entry_price": 100.0,
                "symbol": "EURUSD",
                "sector": "forex",
            },
            {
                "size": 2.0,
                "current_price": 50.0,
                "entry_price": 50.0,
                "symbol": "GBPUSD",
                "sector": "forex",
            },
            {
                "size": 1.0,
                "current_price": 200.0,
                "entry_price": 200.0,
                "symbol": "AAPL",
                "sector": "tech",
            },
        ]
        result = self.engine.calculate_portfolio_risk(positions, 10000.0)
        assert result["total_notional"] == 400.0  # 100 + 100 + 200
        assert result["total_exposure_pct"] == 0.04  # 400 / 10000
        assert result["leverage_used"] == 0.04
        assert result["correlation_risk"] == 1.0 - (3 / 3)  # All unique symbols
        assert result["sector_concentration"] == 2 / 3  # 2 forex, 1 tech

    def test_check_exposure_pass(self) -> None:
        """Test exposure check passes within limit."""
        positions = [
            {"size": 1.0, "current_price": 100.0, "entry_price": 100.0, "account_equity": 10000.0},
            {"size": 1.0, "current_price": 200.0, "entry_price": 200.0, "account_equity": 10000.0},
        ]
        assert self.engine.check_exposure(positions, max_exposure=0.30) is True

    def test_check_exposure_fail(self) -> None:
        """Test exposure check fails over limit."""
        positions = [
            {
                "size": 100.0,
                "current_price": 100.0,
                "entry_price": 100.0,
                "account_equity": 10000.0,
            },
        ]
        assert self.engine.check_exposure(positions, max_exposure=0.30) is False

    def test_check_margin_pass(self) -> None:
        """Test margin check passes."""
        account_state = {
            "equity": 10000.0,
            "used_margin": 1000.0,
            "margin_call_level": 5000.0,
        }
        assert self.engine.check_margin(account_state, margin_threshold=0.20) is True

    def test_check_margin_fail_high_usage(self) -> None:
        """Test margin check fails due to high usage."""
        account_state = {
            "equity": 10000.0,
            "used_margin": 3000.0,
            "margin_call_level": 5000.0,
        }
        assert self.engine.check_margin(account_state, margin_threshold=0.20) is False

    def test_check_margin_fail_margin_call(self) -> None:
        """Test margin check fails due to margin call level."""
        account_state = {
            "equity": 4000.0,
            "used_margin": 1000.0,
            "margin_call_level": 5000.0,
        }
        assert self.engine.check_margin(account_state, margin_threshold=0.20) is False

    def test_check_max_positions_pass(self) -> None:
        """Test max positions check passes."""
        positions = [{"size": 1.0} for _ in range(5)]
        assert self.engine.check_max_positions(positions, max_count=5) is True

    def test_check_max_positions_fail(self) -> None:
        """Test max positions check fails."""
        positions = [{"size": 1.0} for _ in range(6)]
        assert self.engine.check_max_positions(positions, max_count=5) is False

    def test_check_drawdown_pass(self) -> None:
        """Test drawdown check passes."""
        account_state = {
            "equity": 9500.0,
            "peak_equity": 10000.0,
        }
        assert self.engine.check_drawdown(account_state, max_drawdown=0.15) is True

    def test_check_drawdown_fail(self) -> None:
        """Test drawdown check fails."""
        account_state = {
            "equity": 8000.0,
            "peak_equity": 10000.0,
        }
        assert self.engine.check_drawdown(account_state, max_drawdown=0.15) is False

    def test_check_daily_loss_pass(self) -> None:
        """Test daily loss check passes."""
        account_state = {
            "balance": 10000.0,
            "daily_pnl": -200.0,
        }
        assert self.engine.check_daily_loss(account_state, daily_loss_limit=0.05) is True

    def test_check_daily_loss_fail(self) -> None:
        """Test daily loss check fails."""
        account_state = {
            "balance": 10000.0,
            "daily_pnl": -600.0,
        }
        assert self.engine.check_daily_loss(account_state, daily_loss_limit=0.05) is False

    def test_check_daily_loss_positive_pnl(self) -> None:
        """Test daily loss check with positive P&L."""
        account_state = {
            "balance": 10000.0,
            "daily_pnl": 500.0,
        }
        assert self.engine.check_daily_loss(account_state, daily_loss_limit=0.05) is True

    def test_check_position_size_pass(self) -> None:
        """Test position size check passes."""
        position = {"size": 1.0, "current_price": 500.0, "entry_price": 500.0}
        assert self.engine.check_position_size(position, 10000.0, max_position_size=0.10) is True

    def test_check_position_size_fail(self) -> None:
        """Test position size check fails."""
        position = {"size": 10.0, "current_price": 500.0, "entry_price": 500.0}
        assert self.engine.check_position_size(position, 10000.0, max_position_size=0.10) is False

    def test_assess_risk_level_low(self) -> None:
        """Test risk level assessment returns LOW."""
        metrics = RiskMetrics(
            drawdown_pct=0.01,
            daily_loss_pct=0.005,
            total_exposure_pct=0.10,
            used_margin_pct=0.05,
            position_count=2,
            correlation_risk=0.1,
            sector_concentration=0.2,
        )
        assert self.engine.assess_risk_level(metrics) == RiskLevel.LOW

    def test_assess_risk_level_medium(self) -> None:
        """Test risk level assessment returns MEDIUM."""
        metrics = RiskMetrics(
            drawdown_pct=0.08,  # > 50% of 0.15 → +2
            daily_loss_pct=0.015,  # > 20% of 0.05 → +1
            total_exposure_pct=0.16,  # > 50% of 0.30 → +1
            used_margin_pct=0.05,
            position_count=2,
            correlation_risk=0.1,
            sector_concentration=0.2,
        )
        assert self.engine.assess_risk_level(metrics) == RiskLevel.MEDIUM

    def test_assess_risk_level_high(self) -> None:
        """Test risk level assessment returns HIGH."""
        metrics = RiskMetrics(
            drawdown_pct=0.12,  # > 80% of 0.15
            daily_loss_pct=0.04,  # > 80% of 0.05
            total_exposure_pct=0.25,  # > 70% of 0.30
            used_margin_pct=0.05,
            position_count=2,
            correlation_risk=0.1,
            sector_concentration=0.2,
        )
        assert self.engine.assess_risk_level(metrics) == RiskLevel.HIGH

    def test_assess_risk_level_critical(self) -> None:
        """Test risk level assessment returns CRITICAL."""
        metrics = RiskMetrics(
            drawdown_pct=0.14,  # > 80% of 0.15
            daily_loss_pct=0.045,  # > 80% of 0.05
            total_exposure_pct=0.29,  # > 90% of 0.30
            used_margin_pct=0.19,  # > 90% of 0.20
            position_count=5,  # >= max
            correlation_risk=0.9,
            sector_concentration=0.9,
        )
        assert self.engine.assess_risk_level(metrics) == RiskLevel.CRITICAL

    def test_set_threshold(self) -> None:
        """Test setting a custom threshold."""
        self.engine.set_threshold(RiskThreshold.MAX_DRAWDOWN, 0.25)
        assert self.engine.get_threshold(RiskThreshold.MAX_DRAWDOWN) == 0.25


class TestRiskMetrics:
    """Tests for RiskMetrics dataclass."""

    def test_default_values(self) -> None:
        """Test default RiskMetrics values."""
        metrics = RiskMetrics()
        assert metrics.drawdown_pct == 0.0
        assert metrics.daily_loss_pct == 0.0
        assert metrics.equity == 0.0
        assert metrics.balance == 0.0
        assert metrics.position_count == 0

    def test_custom_values(self) -> None:
        """Test RiskMetrics with custom values."""
        metrics = RiskMetrics(
            drawdown_pct=0.10,
            daily_loss_pct=0.02,
            equity=9500.0,
            balance=10000.0,
            total_exposure_pct=0.25,
            used_margin_pct=0.15,
            position_count=3,
            peak_equity=10000.0,
            max_drawdown_pct=0.12,
            correlation_risk=0.3,
            sector_concentration=0.4,
            leverage_used=2.0,
            available_margin=8500.0,
            spread_cost=0.5,
        )
        assert metrics.drawdown_pct == 0.10
        assert metrics.daily_loss_pct == 0.02
        assert metrics.equity == 9500.0
        assert metrics.balance == 10000.0
        assert metrics.total_exposure_pct == 0.25
        assert metrics.used_margin_pct == 0.15
        assert metrics.position_count == 3
        assert metrics.peak_equity == 10000.0
        assert metrics.max_drawdown_pct == 0.12
        assert metrics.correlation_risk == 0.3
        assert metrics.sector_concentration == 0.4
        assert metrics.leverage_used == 2.0
        assert metrics.available_margin == 8500.0
        assert metrics.spread_cost == 0.5

    def test_to_dict(self) -> None:
        """Test RiskMetrics to_dict conversion."""
        metrics = RiskMetrics(
            drawdown_pct=0.10,
            equity=9500.0,
            balance=10000.0,
        )
        d = metrics.to_dict()
        assert d["drawdown_pct"] == 0.10
        assert d["equity"] == 9500.0
        assert d["balance"] == 10000.0
        assert "daily_loss_pct" in d
        assert "position_count" in d


class TestRiskThreshold:
    """Tests for RiskThreshold enum."""

    def test_enum_values(self) -> None:
        """Test RiskThreshold enum values."""
        assert RiskThreshold.MAX_DRAWDOWN == "max_drawdown"
        assert RiskThreshold.DAILY_LOSS_LIMIT == "daily_loss_limit"
        assert RiskThreshold.MAX_EXPOSURE == "max_exposure"
        assert RiskThreshold.MARGIN_THRESHOLD == "margin_threshold"
        assert RiskThreshold.MAX_POSITIONS == "max_positions"
        assert RiskThreshold.MAX_POSITION_SIZE == "max_position_size"


class TestRiskLevel:
    """Tests for RiskLevel enum."""

    def test_enum_values(self) -> None:
        """Test RiskLevel enum values."""
        assert RiskLevel.LOW == "low"
        assert RiskLevel.MEDIUM == "medium"
        assert RiskLevel.HIGH == "high"
        assert RiskLevel.CRITICAL == "critical"
