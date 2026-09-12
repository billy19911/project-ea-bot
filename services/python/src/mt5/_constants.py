# -*- coding: utf-8 -*-
"""Simulation constants for MT5 paper-trading connector.

Shared constants extracted to break circular imports between
connector.py and _connector_base.py.
"""

SIMULATED_SYMBOLS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
    "USDCHF",
    "EURGBP",
    "EURJPY",
    "GBPJPY",
    "XAUUSD",
    "XAGUSD",
    "BTCUSD",
    "ETHUSD",
]

SIMULATED_PRICES: dict[str, tuple[float, float, float]] = {
    "EURUSD": (1.0850, 1.0852, 0.0001),
    "GBPUSD": (1.2650, 1.2653, 0.0003),
    "USDJPY": (147.30, 147.33, 0.01),
    "AUDUSD": (0.6520, 0.6522, 0.0002),
    "USDCAD": (1.3680, 1.3683, 0.0003),
    "NZDUSD": (0.5980, 0.5982, 0.0002),
    "USDCHF": (0.8050, 0.8052, 0.0002),
    "EURGBP": (0.8600, 0.8603, 0.0003),
    "EURJPY": (160.10, 160.14, 0.01),
    "GBPJPY": (186.20, 186.24, 0.01),
    "XAUUSD": (2345.50, 2346.00, 0.50),
    "XAGUSD": (27.85, 27.87, 0.02),
    "BTCUSD": (64250.0, 64280.0, 10.0),
    "ETHUSD": (3420.0, 3422.5, 0.5),
}
