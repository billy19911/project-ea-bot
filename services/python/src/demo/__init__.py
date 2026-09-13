# -*- coding: utf-8 -*-
"""Demo trading package — Phase 20.

MT5 demo account integration with stability, latency, execution,
risk enforcement, and agent consistency verification.
"""

from __future__ import annotations

from .demo_trading import DemoTrade, DemoTradingManager, DemoTradingSession
from .stability import StabilityMonitor

__all__ = [
    "DemoTrade",
    "DemoTradingSession",
    "DemoTradingManager",
    "StabilityMonitor",
]
