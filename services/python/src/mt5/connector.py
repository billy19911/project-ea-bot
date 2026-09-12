# -*- coding: utf-8 -*-
"""MT5 connector — data access functions for simulation and live mode.

All functions are read-only by default. Live MT5 connection
is only activated by calling use_live_mode() with credentials.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from .schemas import OHLC, AccountInfo, Order, Position, SymbolInfo, Tick

# ---------------------------------------------------------------------------
# Simulation constants
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Live / simulation mode
# ---------------------------------------------------------------------------

_live_mode: bool = False
_mt5_available: bool = False


def use_live_mode(
    terminal_path: str,
    login: int,
    password: str,
    server: str,
) -> bool:
    """Connect to a real MT5 terminal.

    Returns True on success, False if MetaTrader5 is not installed
    or credentials fail. Default is simulation mode.
    """
    global _live_mode, _mt5_available

    try:
        import MetaTrader5 as mt5
    except ImportError:
        _mt5_available = False
        return False

    init_ok = mt5.initialize(path=terminal_path)
    if not init_ok:
        return False

    login_ok = mt5.login(login, password=password, server=server)
    if not login_ok:
        mt5.shutdown()
        return False

    _live_mode = True
    _mt5_available = True
    return True


def is_live_mode() -> bool:
    """Return True if connected to a live MT5 terminal."""
    return _live_mode


def shutdown() -> None:
    """Disconnect from MT5 if in live mode."""
    global _live_mode, _mt5_available
    if _mt5_available:
        try:
            import MetaTrader5 as mt5

            mt5.shutdown()
        except Exception:
            pass
    _live_mode = False
    _mt5_available = False


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------


def _jitter(base: float, spread: float) -> float:
    """Add small random jitter to a price."""
    return round(base + random.uniform(-spread * 0.5, spread * 0.5), 5)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Connector functions (read-only)
# ---------------------------------------------------------------------------


def get_account_info() -> AccountInfo:
    """Return account info (simulated or live)."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            info = mt5.account_info()
            if info is None:
                raise RuntimeError("mt5.account_info() returned None")
            return AccountInfo(
                login=info.login,
                server=info.server,
                balance=info.balance,
                equity=info.equity,
                margin=info.margin,
                free_margin=info.margin_free,
                margin_level=info.margin_level,
                currency=info.currency,
                leverage=info.leverage,
                name=info.name,
                trade_mode=str(info.trade_mode),
            )
        except Exception as e:
            raise RuntimeError(f"MT5 live account info failed: {e}")

    # Simulation
    bal = 10000.0
    return AccountInfo(
        login=12345678,
        server="PaperTrading-Server",
        balance=bal,
        equity=bal,
        margin=0.0,
        free_margin=bal,
        margin_level=0.0,
        currency="USD",
        leverage=100,
        name="Paper Trader",
        trade_mode="FULL",
    )


def get_symbols() -> list[SymbolInfo]:
    """Return list of available symbols."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            raw = mt5.symbols_get()
            if raw is None:
                return []
            return [
                SymbolInfo(
                    symbol=s.name,
                    bid=s.bid,
                    ask=s.ask,
                    spread=s.spread,
                    digits=s.digits,
                    contract_size=s.trade_contract_size,
                    point=s.point,
                    trade_mode=str(s.trade_mode),
                    currency_profit=s.currency_profit,
                    currency_margin=s.currency_margin,
                )
                for s in raw
            ]
        except Exception:
            return []

    result = []
    for sym, (bid, ask, spread) in SIMULATED_PRICES.items():
        digits = 2 if sym in ("XAUUSD", "XAGUSD") else (5 if "." in sym and len(sym) <= 6 else 2)
        result.append(
            SymbolInfo(
                symbol=sym,
                bid=_jitter(bid, spread),
                ask=_jitter(ask, spread),
                spread=int(spread * (100 if digits <= 2 else 10000)),
                digits=digits,
                contract_size=100000 if sym not in ("XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD") else 1,
                point=0.00001 if digits == 5 else 0.01,
                trade_mode="FULL",
                currency_profit="USD",
                currency_margin="USD",
            )
        )
    return result


def get_symbol_info(symbol: str) -> Optional[SymbolInfo]:
    """Return symbol info for a specific symbol."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            raw = mt5.symbols_get(symbol)
            if raw is None:
                return None
            s = raw[0] if isinstance(raw, list) else raw
            return SymbolInfo(
                symbol=s.name,
                bid=s.bid,
                ask=s.ask,
                spread=s.spread,
                digits=s.digits,
                contract_size=s.trade_contract_size,
                point=s.point,
                trade_mode=str(s.trade_mode),
                currency_profit=s.currency_profit,
                currency_margin=s.currency_margin,
            )
        except Exception:
            return None

    if symbol not in SIMULATED_PRICES:
        return None
    bid, ask, spread = SIMULATED_PRICES[symbol]
    digits = (
        2 if symbol in ("XAUUSD", "XAGUSD") else (5 if "." in symbol and len(symbol) <= 6 else 2)
    )
    return SymbolInfo(
        symbol=symbol,
        bid=_jitter(bid, spread),
        ask=_jitter(ask, spread),
        spread=int(spread * (100 if digits <= 2 else 10000)),
        digits=digits,
        contract_size=100000 if symbol not in ("XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD") else 1,
        point=0.00001 if digits == 5 else 0.01,
        trade_mode="FULL",
        currency_profit="USD",
        currency_margin="USD",
    )


def get_tick(symbol: str) -> Optional[Tick]:
    """Return latest tick for a symbol."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            ticks = mt5.symbols_get_tick(symbol)
            if ticks is None or len(ticks) == 0:
                return None
            t = ticks[-1]
            return Tick(
                symbol=t.symbol,
                bid=t.bid,
                ask=t.ask,
                last=t.last,
                volume=t.volume,
                time=datetime.fromtimestamp(t.time),
            )
        except Exception:
            return None

    if symbol not in SIMULATED_PRICES:
        return None
    bid, ask, _spread = SIMULATED_PRICES[symbol]
    now = _now()
    return Tick(
        symbol=symbol,
        bid=_jitter(bid, 0.0001),
        ask=_jitter(ask, 0.0001),
        last=_jitter(bid, 0.0001),
        volume=random.uniform(100, 10000),
        time=now,
    )


def get_ohlc(symbol: str, timeframe: str = "H1", count: int = 100) -> list[OHLC]:
    """Return OHLC bars for a symbol."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, count)
            if rates is None:
                return []
            return [
                OHLC(
                    symbol=r.symbol,
                    timeframe=timeframe,
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=float(r["tick_volume"]),
                    time=datetime.fromtimestamp(r["time"]),
                )
                for r in rates
            ]
        except Exception:
            return []

    if symbol not in SIMULATED_PRICES:
        return []
    base_price = SIMULATED_PRICES[symbol][0]
    now = _now()
    bars = []
    for i in range(count):
        t = now - timedelta(hours=i)
        open_ = round(base_price + random.uniform(-0.002, 0.002), 5)
        close = round(base_price + random.uniform(-0.002, 0.002), 5)
        high = round(max(open_, close) + random.uniform(0, 0.001), 5)
        low = round(min(open_, close) - random.uniform(0, 0.001), 5)
        bars.append(
            OHLC(
                symbol=symbol,
                timeframe=timeframe,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=random.uniform(100, 5000),
                time=t.replace(tzinfo=None),
            )
        )
    return list(reversed(bars))


def get_positions() -> list[Position]:
    """Return open positions."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            raw = mt5.positions_get()
            if raw is None:
                return []
            return [
                Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    side="BUY" if p.type == 0 else "SELL",
                    quantity=p.volume,
                    price_open=p.price_open,
                    price_current=p.price_current,
                    swap=p.swap,
                    profit=p.profit,
                    unrealized_pnl=p.profit,
                    margin=p.margin,
                    entry="POSITION_ENTRY_IN" if p.entry == 0 else "POSITION_ENTRY_OUT",
                    status="OPEN",
                    time=datetime.fromtimestamp(p.time),
                    time_update=datetime.fromtimestamp(p.time_update),
                )
                for p in raw
            ]
        except Exception:
            return []

    # Simulation — 2 sample positions
    now = _now()
    return [
        Position(
            ticket=1001,
            symbol="EURUSD",
            side="BUY",
            quantity=1.0,
            price_open=1.0840,
            price_current=1.0852,
            swap=0.0,
            profit=12.0,
            unrealized_pnl=12.0,
            margin=108.4,
            entry="POSITION_ENTRY_IN",
            status="OPEN",
            time=now - timedelta(hours=3),
            time_update=now,
        ),
        Position(
            ticket=1002,
            symbol="XAUUSD",
            side="SELL",
            quantity=0.5,
            price_open=2350.0,
            price_current=2345.5,
            swap=-0.5,
            profit=2.25,
            unrealized_pnl=2.25,
            margin=1175.0,
            entry="POSITION_ENTRY_IN",
            status="OPEN",
            time=now - timedelta(hours=5),
            time_update=now,
        ),
    ]


def get_orders() -> list[Order]:
    """Return pending orders."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            raw = mt5.orders_get()
            if raw is None:
                return []
            return [
                Order(
                    ticket=o.ticket,
                    symbol=o.symbol,
                    side="BUY" if o.type == 0 else "SELL",
                    order_type=str(o.type),
                    price=o.price_open,
                    stop_price=o.stoplimit,
                    quantity=o.volume,
                    filled_qty=o.volume_current,
                    status=str(o.state),
                    time_setup=datetime.fromtimestamp(o.time_setup),
                    time_expiration=(
                        datetime.fromtimestamp(o.time_expiration) if o.time_expiration > 0 else None
                    ),
                )
                for o in raw
            ]
        except Exception:
            return []

    return []


def execute_order(request) -> dict:
    """Execute an order (paper trading — simulated, no real execution)."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            req = request if isinstance(request, dict) else request.model_dump()
            order_type = mt5.ORDER_TYPE_BUY if req["side"] == "BUY" else mt5.ORDER_TYPE_SELL
            price = req.get("price") or (
                get_tick(req["symbol"]).ask if req["side"] == "BUY" else get_tick(req["symbol"]).bid
            )
            request_obj = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": req["symbol"],
                "volume": req["quantity"],
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": 123456,
                "comment": req.get("comment", "paper"),
                "type_time": mt5.ORDER_TIME_GTC,
            }
            result = mt5.order_send(request_obj)
            return {
                "success": result.retcode == mt5.TRADE_RETCODE_DONE,
                "order_id": result.order if result.retcode == mt5.TRADE_RETCODE_DONE else None,
                "message": result.comment,
                "price": result.price,
                "executed_at": datetime.now(),
            }
        except Exception as e:
            return {
                "success": False,
                "order_id": None,
                "message": str(e),
                "price": None,
                "executed_at": None,
            }

    # Simulation — always succeeds, paper trading
    sym = request.symbol if hasattr(request, "symbol") else request.get("symbol", "EURUSD")
    price_base = SIMULATED_PRICES.get(sym, (1.0, 1.0, 0.0))[0]
    price = round(price_base + random.uniform(-0.001, 0.001), 5)
    return {
        "success": True,
        "order_id": random.randint(10000, 99999),
        "message": "PAPER ORDER EXECUTED — simulated, no real funds at risk",
        "price": price,
        "executed_at": _now(),
    }
