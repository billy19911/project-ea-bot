# -*- coding: utf-8 -*-
"""Tests for the Risk Gate (risk_gate.py)."""

from __future__ import annotations

import pytest

from trading.risk_gate import RiskGate, RiskGateError, RiskGateResult, RiskGateValidationResult

# ---------------------------------------------------------------------------
# RiskGate initialisation tests
# ---------------------------------------------------------------------------


class TestRiskGateInit:
    def test_defaults(self):
        rg = RiskGate()
        assert rg.max_daily_loss == 500.0
        assert rg.max_position_size == 1000.0
        assert rg.max_exposure_percent == 20.0
        assert rg.max_daily_trades == 20
        assert rg.min_signal_confidence == 0.5
        assert rg.max_account_drawdown_percent == 15.0
        assert rg.margin_call_threshold == 0.5
        assert rg.auto_block_on_margin_call is True

    def test_custom_values(self):
        rg = RiskGate(
            max_daily_loss=1000.0,
            max_position_size=2000.0,
            max_exposure_percent=30.0,
            max_daily_trades=10,
            min_signal_confidence=0.7,
            max_account_drawdown_percent=10.0,
        )
        assert rg.max_daily_loss == 1000.0
        assert rg.max_position_size == 2000.0
        assert rg.max_exposure_percent == 30.0
        assert rg.max_daily_trades == 10
        assert rg.min_signal_confidence == 0.7
        assert rg.max_account_drawdown_percent == 10.0


# ---------------------------------------------------------------------------
# RiskGateResult enum tests
# ---------------------------------------------------------------------------


class TestRiskGateResult:
    def test_enum_values(self):
        assert RiskGateResult.PASS.value == "PASS"
        assert RiskGateResult.WARN.value == "WARN"
        assert RiskGateResult.BLOCK.value == "BLOCK"


# ---------------------------------------------------------------------------
# RiskGateError dataclass tests
# ---------------------------------------------------------------------------


class TestRiskGateError:
    def test_created(self):
        err = RiskGateError(
            code="TEST",
            message="test message",
            severity="ERROR",
            blocking=True,
            details={"key": "value"},
        )
        assert err.code == "TEST"
        assert err.message == "test message"
        assert err.severity == "ERROR"
        assert err.blocking is True
        assert err.details == {"key": "value"}

    def test_defaults(self):
        err = RiskGateError(
            code="WARN",
            message="warning",
            severity="WARNING",
        )
        assert err.blocking is True  # default
        assert err.details == {}


# ---------------------------------------------------------------------------
# RiskGate.validate() — happy path
# ---------------------------------------------------------------------------


class TestRiskGateValidate:
    @pytest.fixture
    def gate(self):
        return RiskGate()

    def test_all_clear_pass(self, gate):
        """Healthy account with all limits satisfied → PASS."""
        result = gate.validate(
            account_equity=10000.0,
            daily_pnl=0.0,
            open_positions=0,
            total_exposure=0.0,
            margin_used_percent=0.0,
            signal_confidence=0.8,
            detected_events=None,
            daily_trades_today=0,
            current_drawdown_percent=0.0,
        )
        assert result.is_safe
        assert result.outcome == RiskGateResult.PASS
        assert result.checks_passed == result.checks_total
        assert len(result.errors) == 0

    def test_validation_result_properties(self, gate):
        result = gate.validate(
            account_equity=10000.0,
            signal_confidence=0.8,
        )
        assert isinstance(result.checked_at, str)
        assert result.checks_passed > 0
        assert result.checks_total > 0
        assert result.is_safe is True
        assert result.has_warnings is False


# ---------------------------------------------------------------------------
# RiskGate.validate() — blocking scenarios
# ---------------------------------------------------------------------------


class TestRiskGateBlocking:
    @pytest.fixture
    def gate(self):
        return RiskGate()

    def test_negative_equity_blocks(self, gate):
        result = gate.validate(account_equity=-500.0)
        assert result.outcome == RiskGateResult.BLOCK
        assert not result.is_safe
        codes = {e.code for e in result.errors}
        assert "ACCT_EQUITY_INVALID" in codes

    def test_zero_equity_blocks(self, gate):
        result = gate.validate(account_equity=0.0)
        assert result.outcome == RiskGateResult.BLOCK

    def test_daily_loss_limit_blocks(self, gate):
        result = gate.validate(
            account_equity=10000.0,
            daily_pnl=-600.0,  # exceeds 500 default
        )
        assert result.outcome == RiskGateResult.BLOCK

    def test_position_size_limit_blocks(self, gate):
        result = gate.validate(
            account_equity=10000.0,
            total_exposure=1500.0,  # exceeds 1000 default
        )
        assert result.outcome == RiskGateResult.BLOCK

    def test_low_confidence_warns_not_blocks(self, gate):
        result = gate.validate(
            account_equity=10000.0,
            signal_confidence=0.3,  # below 0.5 default
        )
        assert result.outcome == RiskGateResult.WARN
        assert result.has_warnings
        codes = {e.code for e in result.errors}
        assert "LOW_CONFIDENCE" in codes

    def test_daily_trade_limit_blocks(self, gate):
        result = gate.validate(
            account_equity=10000.0,
            daily_trades_today=25,  # exceeds 20 default
        )
        assert result.outcome == RiskGateResult.BLOCK

    def test_drawdown_limit_blocks(self, gate):
        result = gate.validate(
            account_equity=10000.0,
            current_drawdown_percent=20.0,  # exceeds 15 default
        )
        assert result.outcome == RiskGateResult.BLOCK


# ---------------------------------------------------------------------------
# RiskGate.validate() — margin call scenarios
# ---------------------------------------------------------------------------


class TestRiskGateMarginCall:
    def test_margin_call_blocks_default(self):
        gate = RiskGate(auto_block_on_margin_call=True)
        result = gate.validate(
            account_equity=10000.0,
            margin_used_percent=0.6,  # 60% > 50% threshold
        )
        assert result.outcome == RiskGateResult.BLOCK
        codes = {e.code for e in result.errors}
        assert "MARGIN_CALL" in codes

    def test_margin_call_warns_when_unblocked(self):
        gate = RiskGate(auto_block_on_margin_call=False)
        result = gate.validate(
            account_equity=10000.0,
            margin_used_percent=0.6,
        )
        assert result.outcome == RiskGateResult.WARN
        codes = {e.code for e in result.errors}
        assert "MARGIN_CALL_WARN" in codes

    def test_low_margin_passes(self):
        gate = RiskGate()
        result = gate.validate(
            account_equity=10000.0,
            margin_used_percent=0.3,  # 30% < 50%
            signal_confidence=0.8,
        )
        assert result.outcome == RiskGateResult.PASS


# ---------------------------------------------------------------------------
# RiskGate.validate() — exposure warning
# ---------------------------------------------------------------------------


class TestRiskGateExposure:
    def test_exposure_exceeds_warns(self):
        gate = RiskGate(max_exposure_percent=20.0, max_position_size=5000.0)
        result = gate.validate(
            account_equity=10000.0,
            total_exposure=3000.0,
            signal_confidence=0.8,
        )
        assert result.outcome == RiskGateResult.WARN
        assert "EXPOSURE_LIMIT" in {e.code for e in result.errors}

    def test_exposure_within_limit_passes(self):
        gate = RiskGate(max_exposure_percent=20.0, max_position_size=5000.0)
        result = gate.validate(
            account_equity=10000.0,
            total_exposure=1500.0,
            signal_confidence=0.8,
        )
        assert result.outcome == RiskGateResult.PASS


# ---------------------------------------------------------------------------
# RiskGate.validate() — event-based blocking
# ---------------------------------------------------------------------------


class TestRiskGateEvents:
    def test_blocking_events_block(self):
        gate = RiskGate()
        blocking_event = {
            "code": "DRAWDOWN_WARNING",
            "blocking": True,
            "message": "test",
        }
        result = gate.validate(
            account_equity=10000.0,
            signal_confidence=0.8,
            detected_events=[blocking_event],
        )
        assert result.outcome == RiskGateResult.BLOCK
        assert "BLOCKING_EVENTS" in {e.code for e in result.errors}

    def test_non_blocking_events_pass(self):
        gate = RiskGate()
        result = gate.validate(
            account_equity=10000.0,
            signal_confidence=0.8,
            detected_events=[{"code": "INFO", "blocking": False}],
        )
        assert result.outcome == RiskGateResult.PASS

    def test_no_events_pass(self):
        gate = RiskGate()
        result = gate.validate(
            account_equity=10000.0,
            signal_confidence=0.8,
            detected_events=None,
        )
        assert result.outcome == RiskGateResult.PASS


# ---------------------------------------------------------------------------
# RiskGate.validate() — combined scenarios
# ---------------------------------------------------------------------------


class TestRiskGateCombined:
    def test_multiple_issues_blocks(self):
        gate = RiskGate()
        result = gate.validate(
            account_equity=10000.0,
            daily_pnl=-600.0,  # blocks
            total_exposure=1500.0,  # blocks
            signal_confidence=0.3,  # warns
            daily_trades_today=25,  # blocks
            current_drawdown_percent=20.0,  # blocks
        )
        assert result.outcome == RiskGateResult.BLOCK
        assert not result.is_safe
        # All 5 blocking + 1 warning
        assert len(result.errors) >= 5

    def test_warn_with_mixed_issues(self):
        gate = RiskGate()
        result = gate.validate(
            account_equity=10000.0,
            signal_confidence=0.3,  # warn
            total_exposure=2500.0,  # warn (25% > 20%)
            margin_used_percent=0.6,  # warn (if auto_block=False)
        )
        # With default auto_block_on_margin_call=True, margin blocks
        assert result.outcome in (RiskGateResult.WARN, RiskGateResult.BLOCK)


# ---------------------------------------------------------------------------
# RiskGate.check_account_safety tests
# ---------------------------------------------------------------------------


class TestCheckAccountSafety:
    def test_safe_account(self):
        rg = RiskGate(max_daily_loss=500.0, max_account_drawdown_percent=15.0)
        safety = rg.check_account_safety(
            account_equity=10000.0,
            account_balance=10000.0,
            margin_used=0.2,
            open_positions_value=2000.0,
            daily_pnl=0.0,
            current_drawdown=5.0,
        )
        assert safety["safe"] is True
        assert safety["flags"]["daily_loss_ok"] is True
        assert safety["flags"]["drawdown_ok"] is True
        assert safety["flags"]["margin_ok"] is True
        assert safety["flags"]["equity_ok"] is True

    def test_unsafe_daily_loss(self):
        rg = RiskGate(max_daily_loss=500.0)
        safety = rg.check_account_safety(
            account_equity=10000.0,
            account_balance=10000.0,
            margin_used=0.2,
            open_positions_value=2000.0,
            daily_pnl=-600.0,  # exceeds limit
            current_drawdown=5.0,
        )
        assert safety["safe"] is False
        assert safety["flags"]["daily_loss_ok"] is False

    def test_unsafe_drawdown(self):
        rg = RiskGate(max_account_drawdown_percent=15.0)
        safety = rg.check_account_safety(
            account_equity=10000.0,
            account_balance=10000.0,
            margin_used=0.2,
            open_positions_value=2000.0,
            daily_pnl=0.0,
            current_drawdown=20.0,
        )
        assert safety["safe"] is False
        assert safety["flags"]["drawdown_ok"] is False

    def test_unsafe_margin(self):
        rg = RiskGate(margin_call_threshold=0.5)
        safety = rg.check_account_safety(
            account_equity=10000.0,
            account_balance=10000.0,
            margin_used=0.6,
            open_positions_value=2000.0,
            daily_pnl=0.0,
            current_drawdown=5.0,
        )
        assert safety["safe"] is False
        assert safety["flags"]["margin_ok"] is False

    def test_unsafe_negative_equity(self):
        rg = RiskGate()
        safety = rg.check_account_safety(
            account_equity=-100.0,
            account_balance=-100.0,
            margin_used=0.0,
            open_positions_value=0.0,
            daily_pnl=0.0,
            current_drawdown=0.0,
        )
        assert safety["safe"] is False
        assert safety["flags"]["equity_ok"] is False

    def test_includes_config_in_checks(self):
        rg = RiskGate(max_daily_loss=200.0, max_account_drawdown_percent=10.0)
        safety = rg.check_account_safety(
            account_equity=10000.0,
            account_balance=10000.0,
            margin_used=0.0,
            open_positions_value=0.0,
            daily_pnl=0.0,
            current_drawdown=0.0,
        )
        assert safety["checks"]["max_daily_loss"] == 200.0
        assert safety["checks"]["max_drawdown_pct"] == 10.0
        assert safety["checks"]["margin_threshold_pct"] == 50.0


# ---------------------------------------------------------------------------
# Result properties
# ---------------------------------------------------------------------------


class TestValidationResultProperties:
    def test_bool_conversion(self):
        result = RiskGateValidationResult(
            outcome=RiskGateResult.PASS,
            errors=[],
            checks_passed=9,
            checks_total=9,
        )
        assert bool(result) is True

        result2 = RiskGateValidationResult(
            outcome=RiskGateResult.BLOCK,
            errors=[RiskGateError(code="X", message="x", severity="ERROR", blocking=True)],
            checks_passed=5,
            checks_total=9,
        )
        assert bool(result2) is False

    def test_is_safe_property(self):
        r = RiskGateValidationResult(outcome=RiskGateResult.PASS)
        assert r.is_safe is True
        r2 = RiskGateValidationResult(outcome=RiskGateResult.BLOCK)
        assert r2.is_safe is False
        r3 = RiskGateValidationResult(outcome=RiskGateResult.WARN)
        assert r3.is_safe is False

    def test_has_warnings_property(self):
        r = RiskGateValidationResult(
            outcome=RiskGateResult.PASS,
            errors=[RiskGateError(code="W", message="w", severity="WARNING", blocking=False)],
        )
        assert r.has_warnings is True
        r2 = RiskGateValidationResult(outcome=RiskGateResult.PASS, errors=[])
        assert r2.has_warnings is False
