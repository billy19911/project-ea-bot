# -*- coding: utf-8 -*-
"""MT5 connector — data access functions for simulation and live mode.

All functions are read-only by default. Live MT5 connection
is only activated by calling use_live_mode() with credentials.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .schemas import OHLC, AccountInfo, Order, Position, SymbolInfo, Tick
from .write_guard import MT5WriteGuard

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


def use_live_data_mode(path: Optional[str] = None) -> bool:
    """Connect to running MT5 terminal for read-only data without credentials.

    When ``path`` is given it must point at a ``terminal64.exe`` (a folder
    path fails — verified on a real machine). Without ``path`` the binding
    attaches to the most recently used terminal, which keeps the original
    single-terminal behaviour.
    """
    global _live_mode, _mt5_available
    try:
        import MetaTrader5 as mt5
    except ImportError:
        _mt5_available = False
        return False

    try:
        ok = mt5.initialize(path=path) if path else mt5.initialize()
    except Exception:
        # A missing/dead terminal must never break service startup.
        _mt5_available = False
        return False
    if ok:
        _live_mode = True
        _mt5_available = True
        return True
    return False


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


# Seconds per timeframe — used to estimate how far back to request bars when
# lazy-loading chart history (`before`).
_TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
    "MN1": 2592000,
}


def _mt5_timeframe(timeframe: str) -> Any:
    """Resolve a timeframe label to its ``mt5.TIMEFRAME_*`` constant.

    Importing MetaTrader5 lazily (inside the function) keeps the module
    importable on machines without the MT5 package installed. The function
    returns the constant for ``H1`` when the label is unrecognised.
    """
    import MetaTrader5 as mt5

    _TF_MAP = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
        "MN1": mt5.TIMEFRAME_MN1,
    }
    return _TF_MAP.get(str(timeframe).upper(), mt5.TIMEFRAME_H1)


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
        digits = (
            2
            if sym in ("XAUUSD", "XAGUSD")
            else (5 if "." in sym and len(sym) <= 6 else 2)
        )
        result.append(
            SymbolInfo(
                symbol=sym,
                bid=_jitter(bid, spread),
                ask=_jitter(ask, spread),
                spread=int(spread * (100 if digits <= 2 else 10000)),
                digits=digits,
                contract_size=(
                    100000 if sym not in ("XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD") else 1
                ),
                point=0.00001 if digits == 5 else 0.01,
                trade_mode="FULL",
                currency_profit="USD",
                currency_margin="USD",
            )
        )
    return result


def get_symbol_info(symbol: str) -> Optional[SymbolInfo]:
    """Return symbol info for a specific symbol (auto-resolves broker suffix)."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            from .symbol_resolver import resolve_symbol

            resolved = resolve_symbol(symbol)
            raw = mt5.symbols_get(resolved)
            if raw is None:
                return None
            s = raw[0] if isinstance(raw, (list, tuple)) else raw
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
        2
        if symbol in ("XAUUSD", "XAGUSD")
        else (5 if "." in symbol and len(symbol) <= 6 else 2)
    )
    return SymbolInfo(
        symbol=symbol,
        bid=_jitter(bid, spread),
        ask=_jitter(ask, spread),
        spread=int(spread * (100 if digits <= 2 else 10000)),
        digits=digits,
        contract_size=(
            100000 if symbol not in ("XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD") else 1
        ),
        point=0.00001 if digits == 5 else 0.01,
        trade_mode="FULL",
        currency_profit="USD",
        currency_margin="USD",
    )


def get_tick(symbol: str) -> Optional[Tick]:
    """Return latest tick for a symbol (auto-resolves broker suffix)."""
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            from .symbol_resolver import resolve_symbol

            resolved = resolve_symbol(symbol)
            t = mt5.symbol_info_tick(resolved)
            if t is None:
                return None
            return Tick(
                symbol=resolved,
                bid=t.bid,
                ask=t.ask,
                last=t.last,
                volume=float(t.volume),
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


def get_ohlc(
    symbol: str,
    timeframe: str = "H1",
    count: int = 100,
    before: Optional[datetime] = None,
) -> list[OHLC]:
    """Return OHLC bars for a symbol (oldest → newest).

    Args:
        symbol: Symbol name (broker suffix resolved automatically).
        timeframe: MT5 timeframe label (M1..MN1).
        count: Number of bars to return.
        before: When given, return the ``count`` bars immediately *before* this
            timestamp (used by the chart's lazy-load-history on pan-left).
    """
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            tf = _mt5_timeframe(timeframe)
            # Auto-resolve the broker's symbol name, then try the best
            # candidates in order until one returns bars. This makes charts and
            # backtests work regardless of suffix (XAUUSDc / XAUUSD247c / …).
            from .symbol_resolver import candidate_matches, resolve_symbol

            resolved = resolve_symbol(symbol)
            candidates = [resolved]
            try:
                all_syms = [str(s.name).upper() for s in (mt5.symbols_get() or [])]
                for cand in candidate_matches(symbol, all_syms):
                    if cand not in candidates:
                        candidates.append(cand)
            except Exception:  # noqa: BLE001 - enumeration is best-effort
                pass

            # When loading history before a timestamp, ask MT5 for bars from an
            # estimated start (count bars back, with slack) and keep the last
            # `count` strictly older than `before`.
            if before is not None:
                tf_seconds = _TIMEFRAME_SECONDS.get(str(timeframe).upper(), 3600)
                start_ts = int(before.timestamp()) - (count + 8) * tf_seconds
                before_ts = int(before.timestamp())
                for cand in candidates:
                    rates = mt5.copy_rates_from(cand, tf, start_ts, (count + 8) * 2)
                    if rates is None or len(rates) == 0:
                        continue
                    older = [r for r in rates if int(r["time"]) < before_ts]
                    if not older:
                        continue
                    older = older[-count:]
                    return [
                        OHLC(
                            symbol=cand,
                            timeframe=timeframe,
                            open=r["open"],
                            high=r["high"],
                            low=r["low"],
                            close=r["close"],
                            volume=float(r["tick_volume"]),
                            time=datetime.fromtimestamp(int(r["time"])),
                        )
                        for r in older
                    ]
                return []

            for cand in candidates:
                rates = mt5.copy_rates_from_pos(cand, tf, 0, count)
                if rates is not None and len(rates) > 0:
                    return [
                        OHLC(
                            symbol=cand,
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
            return []
        except Exception:
            return []

    if symbol not in SIMULATED_PRICES:
        return []
    base_price = SIMULATED_PRICES[symbol][0]
    now = before if before is not None else _now()
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


def get_ohlc_range(
    symbol: str,
    timeframe: str = "H1",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[OHLC]:
    """Return OHLC bars between start_date and end_date (oldest → newest).

    Args:
        symbol: Symbol name (broker suffix resolved automatically).
        timeframe: MT5 timeframe label (M1..MN1).
        start_date: Start datetime (UTC, inclusive).
        end_date: End datetime (UTC, inclusive).

    Returns:
        OHLC bars in the date range, or empty list if dates invalid/no data.
    """
    if start_date is None or end_date is None:
        return []
    if start_date >= end_date:
        return []

    if _live_mode:
        try:
            import MetaTrader5 as mt5

            tf = _mt5_timeframe(timeframe)

            from .symbol_resolver import candidate_matches, resolve_symbol

            resolved = resolve_symbol(symbol)
            candidates = [resolved]
            try:
                all_syms = [str(s.name).upper() for s in (mt5.symbols_get() or [])]
                for cand in candidate_matches(symbol, all_syms):
                    if cand not in candidates:
                        candidates.append(cand)
            except Exception:  # noqa: BLE001
                pass

            start_ts = int(start_date.timestamp())
            end_ts = int(end_date.timestamp())

            for cand in candidates:
                rates = mt5.copy_rates_range(cand, tf, start_ts, end_ts)
                if rates is not None and len(rates) > 0:
                    return [
                        OHLC(
                            symbol=cand,
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
            return []
        except Exception:
            return []

    # Simulation: generate synthetic bars between start_date and end_date
    if symbol not in SIMULATED_PRICES:
        return []
    base_price = SIMULATED_PRICES[symbol][0]
    tf_seconds = _TIMEFRAME_SECONDS.get(str(timeframe).upper(), 3600)
    bars = []
    current = start_date
    while current <= end_date:
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
                time=current.replace(tzinfo=None),
            )
        )
        current += timedelta(seconds=tf_seconds)
    return bars


def get_data_info(symbol: str, timeframe: str = "H1") -> dict[str, Any]:
    """Return metadata about available historical data for a symbol/timeframe.

    Args:
        symbol: Symbol name (broker suffix resolved automatically).
        timeframe: MT5 timeframe label (M1..MN1).

    Returns:
        Dict with keys:
            - available: bool (whether any data found)
            - oldest_bar: datetime | None (earliest bar available)
            - newest_bar: datetime | None (latest bar available)
            - total_bars: int (approximate, capped at probed depth)
            - max_bars_supported: int (platform limit)
            - supports_date_range: bool (always True for MT5)
    """
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            tf = _mt5_timeframe(timeframe)

            from .symbol_resolver import resolve_symbol

            resolved = resolve_symbol(symbol)
            # Probe: fetch 1 bar from 5 years ago to check depth
            probe_start = datetime.now(timezone.utc) - timedelta(days=5 * 365)
            probe_ts = int(probe_start.timestamp())
            rates_old = mt5.copy_rates_from(resolved, tf, probe_ts, 1)
            # Fetch latest bar
            rates_new = mt5.copy_rates_from_pos(resolved, tf, 0, 1)

            if rates_new is not None and len(rates_new) > 0:
                newest = datetime.fromtimestamp(rates_new[0]["time"])
            else:
                newest = None

            if rates_old is not None and len(rates_old) > 0:
                oldest = datetime.fromtimestamp(rates_old[0]["time"])
            else:
                oldest = None

            available = newest is not None
            # Estimate total bars (not exact, just rough count)
            total_bars = 0
            if oldest is not None and newest is not None:
                delta = newest - oldest
                tf_seconds = _TIMEFRAME_SECONDS.get(str(timeframe).upper(), 3600)
                total_bars = int(delta.total_seconds() / tf_seconds)

            return {
                "available": available,
                "oldest_bar": oldest,
                "newest_bar": newest,
                "total_bars": total_bars,
                "max_bars_supported": 100000,
                "supports_date_range": True,
            }
        except Exception:
            return {
                "available": False,
                "oldest_bar": None,
                "newest_bar": None,
                "total_bars": 0,
                "max_bars_supported": 100000,
                "supports_date_range": True,
            }

    # Simulation mode
    return {
        "available": symbol in SIMULATED_PRICES,
        "oldest_bar": datetime.now(timezone.utc) - timedelta(days=365 * 5),
        "newest_bar": datetime.now(timezone.utc),
        "total_bars": 50000,
        "max_bars_supported": 100000,
        "supports_date_range": True,
    }


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
                    margin=0.0,
                    # EA magic number labels our own orders (0 → none).
                    magic=int(getattr(p, "magic", 0) or 0) or None,
                    # MT5 reports 0.0 when no level is placed — that is "none",
                    # not a real price of zero.
                    sl=float(p.sl) if float(getattr(p, "sl", 0.0) or 0.0) > 0 else None,
                    tp=float(p.tp) if float(getattr(p, "tp", 0.0) or 0.0) > 0 else None,
                    entry=(
                        "POSITION_ENTRY_IN"
                        if p.reason == mt5.POSITION_REASON_CLIENT
                        else "POSITION_ENTRY_OUT"
                    ),
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
            magic=None,  # simulated positions carry no EA magic
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
            magic=None,  # simulated positions carry no EA magic
            entry="POSITION_ENTRY_IN",
            status="OPEN",
            time=now - timedelta(hours=5),
            time_update=now,
        ),
    ]


def get_positions_ex() -> tuple[bool, list[Position]]:
    """Return open positions plus a read-verified flag.

    ``get_positions()`` returns ``[]`` both when the broker genuinely holds no
    positions AND when the live read fails — a caller that closes internal
    ledger records on an empty list would therefore false-close on a terminal
    hiccup. This variant disambiguates the two cases for the closure path
    (LEDGER-SLTP T1).

    Returns:
        ``(ok, positions)`` where ``ok`` is True only when the position list
        was read successfully:

        * live mode, ``mt5.positions_get()`` returns ``None`` (read error) →
          ``(False, [])``;
        * live mode, empty result → ``(True, [])``;
        * live mode, data → ``(True, [...])``;
        * simulation mode → ``(True, [...simulated positions...])`` (the sim
          list legitimately represents the broker's positions, so it is
          verified).
    """
    if _live_mode:
        try:
            import MetaTrader5 as mt5

            raw = mt5.positions_get()
            if raw is None:
                # Read failure — NOT an empty book. Signal unverified.
                return False, []
            positions = list(get_positions())
            return True, positions
        except Exception:
            return False, []

    # Simulation — the (synthetic) position list is authoritative here.
    return True, list(get_positions())


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
                    side="BUY" if o.type in (0, 2, 4) else "SELL",
                    order_type=str(o.type),
                    price=o.price_open,
                    stop_price=getattr(o, "price_stoplimit", None),
                    quantity=o.volume_initial,
                    filled_qty=o.volume_current,
                    status=str(o.state),
                    time_setup=datetime.fromtimestamp(o.time_setup),
                    time_expiration=(
                        datetime.fromtimestamp(o.time_expiration)
                        if o.time_expiration > 0
                        else None
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
        return {
            "success": False,
            "order_id": None,
            "message": "LIVE DATA MODE (read-only) — order execution disabled. "
            "Paper order not sent to broker.",
            "price": None,
            "executed_at": None,
        }

    # Simulation — always succeeds, paper trading
    sym = (
        request.symbol
        if hasattr(request, "symbol")
        else request.get("symbol", "EURUSD")
    )
    price_base = SIMULATED_PRICES.get(sym, (1.0, 1.0, 0.0))[0]
    price = round(price_base + random.uniform(-0.001, 0.001), 5)
    return {
        "success": True,
        "order_id": random.randint(10000, 99999),
        "message": "PAPER ORDER EXECUTED — simulated, no real funds at risk",
        "price": price,
        "executed_at": _now(),
    }


def guarded_execute_order(
    agent,
    order: dict,
    guard: Optional[MT5WriteGuard] = None,
    executor=execute_order,
    positions: Optional[list[dict]] = None,
    account_state: Optional[dict] = None,
) -> dict:
    """Execute order only after MT5 write guard approval.

    This is the safe write path for MT5 execution. Raw execute_order remains
    available for paper/demo compatibility, but live agent flows should call
    this wrapper so permission and monetary checks run before order_send.
    """
    active_guard = guard or MT5WriteGuard()
    validation = active_guard.validate_order(
        agent=agent,
        order=order,
        positions=positions,
        account_state=account_state,
    )
    if not validation["valid"]:
        return {
            "success": False,
            "order_id": None,
            "message": validation["reason"],
            "reason": validation["reason"],
            "price": None,
            "executed_at": None,
            "checked": validation["checked"],
        }

    normalized_order = dict(order)
    if "quantity" not in normalized_order and "volume" in normalized_order:
        normalized_order["quantity"] = normalized_order["volume"]

    result = executor(normalized_order)
    if isinstance(result, dict):
        result.setdefault("checked", validation["checked"])
    return result or {
        "success": False,
        "order_id": None,
        "message": "MT5 executor returned no result",
        "reason": "MT5 executor returned no result",
        "price": None,
        "executed_at": None,
        "checked": validation["checked"],
    }
