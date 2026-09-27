# -*- coding: utf-8 -*-
"""Spread-aware SL/TP and risk gate threshold tests (TDD)."""

import pytest

from src.risk.gate import RiskEngine, RiskGate
from src.risk.money_management import MoneyManager


class TestSpreadAwareSLTP:
    """Unit tests: MoneyManager.calculate_sl_tp dengan parameter spread."""

    def setup_method(self):
        self.mm = MoneyManager()

    def test_long_shifted_up_by_spread(self):
        """BUY: SL/TP dihitung dari ask-side (entry + spread)."""
        entry, atr, spread = 100.0, 10.0, 2.0
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=entry,
            direction="long",
            atr_value=atr,
            spread=spread,
        )
        expected_sl = entry + spread - atr * 1.5  # 100 + 2 - 15 = 87
        expected_tp = entry + spread + atr * 3.0  # 100 + 2 + 30 = 132
        assert sl == pytest.approx(expected_sl, rel=1e-9)
        assert tp == pytest.approx(expected_tp, rel=1e-9)

    def test_short_unaffected_by_spread(self):
        """SELL: SL/TP dihitung dari bid-side (tidak ada geser)."""
        entry, atr, spread = 100.0, 10.0, 2.0
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=entry,
            direction="short",
            atr_value=atr,
            spread=spread,
        )
        # Short: effective_entry = entry (tanpa geser)
        expected_sl = entry + atr * 1.5  # 100 + 15 = 115
        expected_tp = entry - atr * 3.0  # 100 - 30 = 70
        assert sl == pytest.approx(expected_sl, rel=1e-9)
        assert tp == pytest.approx(expected_tp, rel=1e-9)

    def test_backward_compatible_zero_spread(self):
        """spread=0 mengembalikan perilaku lama tanpa perubahan."""
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=100.0,
            direction="long",
            atr_value=10.0,
            spread=0.0,
        )
        assert sl == pytest.approx(85.0, rel=1e-9)  # 100 - 15
        assert tp == pytest.approx(130.0, rel=1e-9)  # 100 + 30

    def test_long_realistic_btc_scenario(self):
        """Simulasi BTC nyata: entry~68000, ATR~76.7, spread~40."""
        entry, atr, spread = 68000.0, 76.7, 40.0
        sl, tp = self.mm.calculate_sl_tp(
            entry_price=entry,
            direction="long",
            atr_value=atr,
            spread=spread,
        )
        # Effective entry = 68000 + 40 = 68040
        # SL = 68040 - 115.05 = 67924.95; TP = 68040 + 230.1 = 68270.1
        assert sl == pytest.approx(67924.95, rel=1e-5)
        assert tp == pytest.approx(68270.1, rel=1e-5)


class TestRiskGateSpreadThreshold:
    """Unit tests: Konfigurasi ambang batas spread di RiskGate."""

    def test_gate_accepts_normal_btc_spread(self):
        """Normal BTC spread (4000 pips) diterima saat threshold >= 4000."""
        mock_engine = RiskEngine(max_positions=5)
        mm = MoneyManager()
        max_spread_pips = 8000.0
        gate = RiskGate(mock_engine, mm, max_spread_pips=max_spread_pips, min_rr=1.5)

        proposal = {
            "symbol": "BTCUSD",
            "direction": "BUY",
            "entry_price": 68000.0,
            "stop_loss": 67900.0,
            "take_profit": 68300.0,
            "size": 0.1,
        }
        account_state = {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
        }
        current_positions = []
        market_info = {
            "spread_pips": 4000.0,
            "point_value": 0.001,
            "contract_size": 100000,
        }

        decision = gate.validate_proposal(proposal, account_state, current_positions, market_info)
        assert decision.checks_passed[
            "spread"
        ], f"Harus terima spread BTC normal: {decision.reason}"

    def test_gate_rejects_anomalous_spread(self):
        """Spread anomali (15000 pips) ditolak saat threshold=8000."""
        mock_engine = RiskEngine(max_positions=5)
        mm = MoneyManager()
        max_spread_pips = 8000.0
        gate = RiskGate(mock_engine, mm, max_spread_pips=max_spread_pips, min_rr=1.5)

        proposal = {
            "symbol": "BTCUSD",
            "direction": "SELL",
            "entry_price": 68000.0,
            "stop_loss": 68200.0,
            "take_profit": 67700.0,
            "size": 0.1,
        }
        account_state = {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
        }
        current_positions = []
        market_info = {
            "spread_pips": 15000.0,
            "point_value": 0.001,
            "contract_size": 100000,
        }

        decision = gate.validate_proposal(proposal, account_state, current_positions, market_info)
        assert not decision.checks_passed[
            "spread"
        ], f"Harus tolak spread anomali: {decision.reason}"


class TestPipelineSpreadWiring:
    """D2: Pipeline meneruskan spread_price pasar ke MoneyManager.calculate_sl_tp."""

    def test_pipeline_passes_spread_price_to_calculate_sl_tp(self):
        """Pipeline harus pass market_info['spread_price'] ke calculate_sl_tp."""
        from orchestration.pipeline import TradingPipeline

        class _SpyMoneyManager(MoneyManager):
            def __init__(self):
                super().__init__()
                self.calls = []

            def calculate_sl_tp(self, **kwargs):
                self.calls.append(dict(kwargs))
                return super().calculate_sl_tp(**kwargs)

        spy = _SpyMoneyManager()
        pipeline = TradingPipeline(supervisor=None, risk_gate=None, money_manager=spy)
        context = {
            "market_state": {"close": 68000.0, "atr": 76.7},
            "market_info": {"spread_price": 40.0, "spread_pips": 4000.0},
            "account_state": {
                "equity": 10000.0,
                "balance": 10000.0,
                "peak_equity": 10000.0,
                "daily_pnl": 0.0,
            },
            "current_positions": [],
        }
        proposal = {"symbol": "BTCUSD", "direction": "BUY", "confidence": 0.9}

        inputs = pipeline._build_validation_inputs(proposal, context)

        assert spy.calls, "calculate_sl_tp harus dipanggil saat SL/TP kosong"
        assert spy.calls[-1]["spread"] == pytest.approx(
            40.0
        ), "market_info['spread_price'] harus diteruskan apa adanya"
        # BUY: SL/TP dihitung dari ask-side (entry 68000 + spread 40)
        assert inputs["proposal"]["stop_loss"] == pytest.approx(67924.95, rel=1e-5)
        assert inputs["proposal"]["take_profit"] == pytest.approx(68270.1, rel=1e-5)


class TestAccountContextSpreadPips:
    """D3: build_connector_account_context mengisi spread_pips (check gate #6)."""

    def test_context_populates_spread_pips_for_btc(self):
        """Konteks connector harus mengisi spread_pips numerik > 0."""
        from orchestration.account_context import build_connector_account_context

        context = build_connector_account_context("BTCUSD")
        market_info = context.get("market_info", {})

        assert "spread_pips" in market_info, "spread_pips wajib terisi (dead code gate #6)"
        assert float(market_info["spread_pips"]) > 0
        point = float(market_info["point_value"])
        assert point > 0
        assert float(market_info["spread_pips"]) == pytest.approx(
            float(market_info["spread_price"]) / (point * 10.0), rel=1e-6
        )


class TestRuntimeSpreadThresholdWiring:
    """D4: runtime meneruskan MAX_SPREAD_PIPS ke RiskGate (perilaku gate)."""

    _PROPOSAL = {
        "symbol": "BTCUSD",
        "direction": "BUY",
        "entry_price": 68000.0,
        "stop_loss": 67900.0,
        "take_profit": 68300.0,
        "size": 0.1,
    }
    _ACCOUNT = {
        "equity": 10000.0,
        "balance": 10000.0,
        "peak_equity": 10000.0,
        "daily_pnl": 0.0,
    }
    _MARKET = {"spread_pips": 10000.0, "point_value": 0.001, "contract_size": 1}

    def test_runtime_gate_rejects_anomalous_spread_with_env(self, monkeypatch):
        """MAX_SPREAD_PIPS=8000 → spread 10000 pips ditolak oleh gate runtime."""
        from orchestration.runtime import OrchestrationRuntime

        monkeypatch.setenv("MAX_SPREAD_PIPS", "8000")
        runtime = OrchestrationRuntime()
        gate = runtime.pipeline.risk_gate

        decision = gate.validate_proposal(self._PROPOSAL, self._ACCOUNT, [], self._MARKET)
        assert decision.checks_passed["spread"] is False

    def test_runtime_gate_default_is_wide_for_btc(self, monkeypatch):
        """Tanpa env, default 50000 → spread BTC 10000 pips diterima."""
        from orchestration.runtime import OrchestrationRuntime

        monkeypatch.delenv("MAX_SPREAD_PIPS", raising=False)
        runtime = OrchestrationRuntime()
        gate = runtime.pipeline.risk_gate

        decision = gate.validate_proposal(self._PROPOSAL, self._ACCOUNT, [], self._MARKET)
        assert decision.checks_passed["spread"] is True
