# -*- coding: utf-8 -*-
"""
Live Readiness Evaluation Package — Phase 30 Gates Check

Gate checkpoints:
- backtest: passed
- forward_test: passed
- paper_trading: passed
- demo_trading: passed
- risk_validation: passed
- kill_switch: tested
- monitoring: active
- alerts: active
- backup: active
- recovery_tested: tested
- manual_emergency_control: available

Deterministic fail-closed policy: if any gate fails, overall readiness = FAIL.
"""

from __future__ import annotations

from .evaluator import LiveReadinessEvaluator, LiveReadinessGate, LiveReadinessStatus, Phase30Gate

__all__ = [
    "LiveReadinessEvaluator",
    "LiveReadinessGate",
    "LiveReadinessStatus",
    "Phase30Gate",
]
