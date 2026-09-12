# -*- coding: utf-8 -*-
"""FastAPI router for deterministic trading engine endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from .engine import TradingEngine

router = APIRouter(prefix="/trading", tags=["deterministic-trading"])


@router.get("/analyze", summary="Analyze market data")
async def analyze_market(
    ohlc_data: list[dict[str, float]] | list[list[float]],
):
    """Get comprehensive market analysis from the trading engine."""
    engine = TradingEngine()
    try:
        signal = engine.generate_signal(ohlc_data)
        return {
            "success": True,
            "signal": {
                "type": signal.signal_type.value,
                "confidence": signal.confidence,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "position_size": signal.position_size,
                "atr_value": signal.atr_value,
                "reason": signal.reason,
                "indicators": {
                    "ema_fast": signal.indicators.ema_fast,
                    "ema_slow": signal.indicators.ema_slow,
                    "rsi": signal.indicators.rsi,
                    "macd_line": signal.indicators.macd_line,
                    "signal_line": signal.indicators.signal_line,
                    "macd_histogram": signal.indicators.macd_histogram,
                    "atr": signal.indicators.atr,
                    "adx": signal.indicators.adx,
                    "stoch_k": signal.indicators.stoch_k,
                    "stoch_d": signal.indicators.stoch_d,
                },
            },
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@router.post("/signal", summary="Generate trading signal")
async def generate_signal(
    ohlc_data: list[dict[str, float]] | list[list[float]],
    account_equity: float = 10000.0,
):
    """Generate a trading signal with position sizing."""
    engine = TradingEngine()
    signal = engine.generate_signal(ohlc_data, account_equity)
    return {
        "signal": {
            "type": signal.signal_type.value,
            "confidence": signal.confidence,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "position_size": signal.position_size,
            "atr_value": signal.atr_value,
            "reason": signal.reason,
        },
        "id": f"sig_{hash(str(ohlc_data))}",
        "generated_at": datetime.now().isoformat(),
    }


@router.get("/config", summary="Get default trading engine configuration")
async def get_config():
    """Return default trading engine configuration."""
    return {
        "fast_ema_period": 9,
        "slow_ema_period": 21,
        "rsi_period": 14,
        "rsi_overbought": 70.0,
        "rsi_oversold": 30.0,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "atr_period": 14,
        "adx_period": 14,
        "stoch_period": 14,
        "stoch_smooth": 3,
        "risk_percent": 2.0,
        "atr_stop_multiplier": 2.0,
        "reward_risk_ratio": 2.0,
        "min_confidence": 0.5,
    }
