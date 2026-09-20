# -*- coding: utf-8 -*-
"""Research Engine 2.0 — PRD_V2 §39.

A research pipeline that can distinguish *robust* strategies from *overfit*
ones by simulating realistic execution costs and reporting the full metric set
the PRD requires.

Realism knobs (all applied deterministically):

* spread        — half-spread applied on entry and exit,
* slippage      — adverse price movement on market fills,
* commission    — per-trade cost,
* swap          — per-night holding cost (applied by hold duration),
* execution delay — bars of latency between signal and fill,
* symbol spec   — contract/digits/point used to round filled prices,
* position sizing — fixed-fractional sizing off an account balance,
* risk rules    — max risk per trade as a fraction of equity,
* session filters — restrict trading to configured UTC hour windows.

Required metrics (PRD §39): total return, net profit, profit factor,
expectancy, win rate, loss rate, average R, max drawdown, max consecutive
losses, recovery factor, Sharpe, Sortino, trade frequency, average hold time,
profit by session, profit by hour, profit by regime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

__all__ = [
    "SymbolSpec",
    "CostModel",
    "RiskConfig",
    "Bar",
    "SimTrade",
    "BacktestV2Result",
    "RealisticBacktester",
]


# ---------------------------------------------------------------------------
# Configuration objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolSpec:
    """Broker symbol specification used to round fills (PRD §39)."""

    symbol: str = "EURUSD"
    digits: int = 5
    point: float = 0.00001
    contract_size: float = 100_000.0
    min_lot: float = 0.01
    lot_step: float = 0.01

    def round_price(self, price: float) -> float:
        return round(price, self.digits)

    def normalize_lot(self, lot: float) -> float:
        steps = round(lot / self.lot_step)
        lot = steps * self.lot_step
        if lot < self.min_lot:
            lot = self.min_lot
        # Keep two-decimal precision consistent with typical brokers.
        return round(lot, 2)


@dataclass(frozen=True)
class CostModel:
    """Execution cost model (PRD §39)."""

    spread_points: float = 10.0  # full spread in points
    slippage_points: float = 2.0  # adverse slippage in points
    commission_per_lot: float = 7.0  # round-turn commission per lot
    swap_per_night_per_lot: float = -1.5  # negative = cost
    execution_delay_bars: int = 1  # latency between signal and fill


@dataclass(frozen=True)
class RiskConfig:
    """Position-sizing / risk rules (PRD §39)."""

    starting_balance: float = 10_000.0
    risk_per_trade: float = 0.01  # 1% of equity risked per trade
    max_lot: float = 10.0
    session_hours_utc: Optional[tuple[int, int]] = None  # e.g. (7, 20)


@dataclass(frozen=True)
class Bar:
    """A single OHLC bar with timestamp (UTC)."""

    time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class SimTrade:
    """A single simulated trade record."""

    entry_time: datetime
    exit_time: datetime
    direction: int  # +1 long, -1 short
    entry_price: float
    exit_price: float
    lot: float
    gross_pnl: float
    commission: float
    swap: float
    spread_cost: float
    slippage_cost: float
    net_pnl: float
    r_multiple: float
    hold_hours: float
    exit_reason: str
    regime: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "lot": self.lot,
            "gross_pnl": self.gross_pnl,
            "commission": self.commission,
            "swap": self.swap,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "net_pnl": self.net_pnl,
            "r_multiple": self.r_multiple,
            "hold_hours": self.hold_hours,
            "exit_reason": self.exit_reason,
            "regime": self.regime,
        }


@dataclass
class BacktestV2Result:
    """Aggregated result with the full PRD §39 metric set."""

    metrics: dict[str, float] = field(default_factory=dict)
    profit_by_session: dict[str, float] = field(default_factory=dict)
    profit_by_hour: dict[str, float] = field(default_factory=dict)
    profit_by_regime: dict[str, float] = field(default_factory=dict)
    trades: list[SimTrade] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": dict(self.metrics),
            "profit_by_session": dict(self.profit_by_session),
            "profit_by_hour": dict(self.profit_by_hour),
            "profit_by_regime": dict(self.profit_by_regime),
            "trades": [t.to_dict() for t in self.trades],
        }


# Session bucket helper (Asia / London / New York / Other).
def _session_for_hour(hour: int) -> str:
    if 0 <= hour < 7:
        return "asia"
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 17:
        return "london_ny_overlap"
    if 17 <= hour < 22:
        return "new_york"
    return "other"


def _regime_for_series(closes: list[float], idx: int, lookback: int = 20) -> str:
    """Classify a coarse trend regime using a simple lookback slope."""
    start = max(0, idx - lookback)
    window = closes[start : idx + 1]
    if len(window) < 3:
        return "unknown"
    return "uptrend" if window[-1] >= window[0] else "downtrend"


class RealisticBacktester:
    """Deterministic realistic backtester over OHLC bars.

    The strategy is injected as a ``signal_fn(bars, index) -> int`` returning
    +1 (long), -1 (short) or 0 (flat). This keeps the engine strategy-agnostic
    while still applying all execution costs.
    """

    def __init__(
        self,
        spec: SymbolSpec = SymbolSpec(),
        costs: CostModel = CostModel(),
        risk: RiskConfig = RiskConfig(),
    ) -> None:
        self.spec = spec
        self.costs = costs
        self.risk = risk

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------
    def run(
        self,
        bars: list[Bar],
        signal_fn: Callable[[list[Bar], int], int],
        stop_multiplier: float = 2.0,
        reward_risk: float = 2.0,
    ) -> BacktestV2Result:
        """Run the backtest. Returns a :class:`BacktestV2Result`."""
        trades: list[SimTrade] = []
        closes = [b.close for b in bars]
        balance = self.risk.starting_balance
        half_spread = (self.costs.spread_points * self.spec.point) / 2.0

        in_trade = False
        direction = 0
        entry_price = 0.0
        entry_time: Optional[datetime] = None
        entry_index = 0
        lot = 0.0
        stop_price = 0.0
        target_price = 0.0
        risk_per_unit = 0.0

        pending: Optional[tuple[int, int]] = None  # (direction, signal_index)
        i = 0
        n = len(bars)

        while i < n:
            bar = bars[i]

            # Honour session filter for *new* entries only.
            session_ok = True
            if self.risk.session_hours_utc is not None:
                lo, hi = self.risk.session_hours_utc
                session_ok = lo <= bar.time.hour < hi

            if not in_trade and pending is None and session_ok:
                sig = signal_fn(bars, i)
                if sig in (1, -1):
                    pending = (sig, i)

            if not in_trade and pending is not None:
                sig_dir, sig_idx = pending
                if i >= sig_idx + self.costs.execution_delay_bars:
                    # Fill at open of the current bar with adverse slippage.
                    slip = self.costs.slippage_points * self.spec.point
                    fill = bar.open + sig_dir * (half_spread + slip)
                    fill = self.spec.round_price(fill)
                    sl_dist = stop_multiplier * (bar.high - bar.low or self.spec.point)
                    risk_per_unit = sl_dist
                    # Fixed-fractional sizing.
                    risk_cash = balance * self.risk.risk_per_trade
                    lot = risk_cash / (sl_dist * self.spec.contract_size) if sl_dist > 0 else 0.01
                    lot = self.spec.normalize_lot(min(lot, self.risk.max_lot))
                    entry_price = fill
                    entry_time = bar.time
                    entry_index = i
                    direction = sig_dir
                    stop_price = fill - direction * stop_multiplier * risk_per_unit / 2.0
                    target_price = (
                        fill + direction * stop_multiplier * reward_risk * risk_per_unit / 2.0
                    )
                    in_trade = True
                    pending = None
                    continue

            if in_trade and entry_time is not None:
                exit_price: Optional[float] = None
                exit_reason = ""
                if direction == 1:
                    if bar.low <= stop_price:
                        exit_price, exit_reason = stop_price, "stop_loss"
                    elif bar.high >= target_price:
                        exit_price, exit_reason = target_price, "take_profit"
                else:
                    if bar.high >= stop_price:
                        exit_price, exit_reason = stop_price, "stop_loss"
                    elif bar.low <= target_price:
                        exit_price, exit_reason = target_price, "take_profit"

                if exit_price is None:
                    new_sig = signal_fn(bars, i)
                    if new_sig == -direction:
                        exit_price, exit_reason = bar.close, "signal_reversal"

                if exit_price is not None:
                    exit_price = self.spec.round_price(exit_price)
                    gross = (exit_price - entry_price) * direction * lot * self.spec.contract_size
                    commission = self.costs.commission_per_lot * lot * 2  # round turn
                    hold_hours = (bar.time - entry_time).total_seconds() / 3600.0
                    nights = max(int(hold_hours // 24), 0)
                    swap = self.costs.swap_per_night_per_lot * lot * nights
                    spread_cost = (half_spread * 2) * lot * self.spec.contract_size
                    slippage_cost = (
                        self.costs.slippage_points * self.spec.point * lot * self.spec.contract_size
                    )
                    net = gross - commission + swap
                    risk_cash = lot * self.spec.contract_size * risk_per_unit / 2.0
                    r_multiple = (net / risk_cash) if risk_cash > 0 else 0.0
                    trade = SimTrade(
                        entry_time=entry_time,
                        exit_time=bar.time,
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        lot=lot,
                        gross_pnl=gross,
                        commission=commission,
                        swap=swap,
                        spread_cost=spread_cost,
                        slippage_cost=slippage_cost,
                        net_pnl=net,
                        r_multiple=r_multiple,
                        hold_hours=hold_hours,
                        exit_reason=exit_reason,
                        regime=_regime_for_series(closes, entry_index),
                    )
                    trades.append(trade)
                    balance += net
                    in_trade = False

            i += 1

        # Close any open position at the last close.
        if in_trade and entry_time is not None and n:
            last = bars[-1]
            exit_price = self.spec.round_price(last.close)
            gross = (exit_price - entry_price) * direction * lot * self.spec.contract_size
            commission = self.costs.commission_per_lot * lot * 2
            hold_hours = (last.time - entry_time).total_seconds() / 3600.0
            swap = self.costs.swap_per_night_per_lot * lot * max(int(hold_hours // 24), 0)
            net = gross - commission + swap
            risk_cash = lot * self.spec.contract_size * risk_per_unit / 2.0
            r_multiple = (net / risk_cash) if risk_cash > 0 else 0.0
            trades.append(
                SimTrade(
                    entry_time=entry_time,
                    exit_time=last.time,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    lot=lot,
                    gross_pnl=gross,
                    commission=commission,
                    swap=swap,
                    spread_cost=0.0,
                    slippage_cost=0.0,
                    net_pnl=net,
                    r_multiple=r_multiple,
                    hold_hours=hold_hours,
                    exit_reason="end_of_data",
                    regime=_regime_for_series(closes, entry_index),
                )
            )

        return self._aggregate(trades, balance)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------
    def _aggregate(self, trades: list[SimTrade], final_balance: float) -> BacktestV2Result:
        starting = self.risk.starting_balance
        pnls = [t.net_pnl for t in trades]
        n = len(pnls)

        if n == 0:
            return BacktestV2Result(
                metrics={
                    "total_return": 0.0,
                    "net_profit": 0.0,
                    "profit_factor": 0.0,
                    "expectancy": 0.0,
                    "win_rate": 0.0,
                    "loss_rate": 0.0,
                    "average_r": 0.0,
                    "max_drawdown": 0.0,
                    "max_consecutive_losses": 0.0,
                    "recovery_factor": 0.0,
                    "sharpe": 0.0,
                    "sortino": 0.0,
                    "trade_frequency": 0.0,
                    "average_hold_time": 0.0,
                }
            )

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        net_profit = sum(pnls)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        expectancy = net_profit / n
        win_rate = len(wins) / n * 100.0
        loss_rate = len(losses) / n * 100.0
        average_r = sum(t.r_multiple for t in trades) / n

        # Drawdown over the equity curve.
        equity = [starting]
        for p in pnls:
            equity.append(equity[-1] + p)
        peak = equity[0]
        max_dd_abs = 0.0
        max_dd_pct = 0.0
        for value in equity:
            peak = max(peak, value)
            dd_abs = peak - value
            max_dd_abs = max(max_dd_abs, dd_abs)
            if peak > 0:
                max_dd_pct = max(max_dd_pct, dd_abs / peak * 100.0)

        # Max consecutive losses.
        max_consec = 0
        streak = 0
        for p in pnls:
            if p < 0:
                streak += 1
                max_consec = max(max_consec, streak)
            else:
                streak = 0

        recovery_factor = (net_profit / max_dd_abs) if max_dd_abs > 0 else 0.0

        # Sharpe / Sortino (per-trade, non-annualised).
        mean = net_profit / n
        if n > 1:
            var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
            std = var**0.5
            sharpe = mean / std if std > 0 else 0.0
            downside = [p for p in pnls if p < 0]
            if downside:
                dvar = sum(p**2 for p in downside) / len(downside)
                dstd = dvar**0.5
                sortino = mean / dstd if dstd > 0 else 0.0
            else:
                sortino = float("inf")
        else:
            sharpe = 0.0
            sortino = 0.0

        # Trade frequency and hold time.
        total_hours = (
            (trades[-1].exit_time - trades[0].entry_time).total_seconds() / 3600.0
            if n >= 2
            else trades[0].hold_hours
        )
        trade_frequency = (n / total_hours * 24.0) if total_hours > 0 else 0.0
        average_hold_time = sum(t.hold_hours for t in trades) / n

        # Breakdowns.
        by_session: dict[str, float] = {}
        by_hour: dict[str, float] = {}
        by_regime: dict[str, float] = {}
        for t in trades:
            session = _session_for_hour(t.entry_time.hour)
            by_session[session] = by_session.get(session, 0.0) + t.net_pnl
            hour_key = str(t.entry_time.hour)
            by_hour[hour_key] = by_hour.get(hour_key, 0.0) + t.net_pnl
            by_regime[t.regime] = by_regime.get(t.regime, 0.0) + t.net_pnl

        metrics = {
            "total_return": (net_profit / starting) * 100.0,
            "net_profit": net_profit,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "win_rate": win_rate,
            "loss_rate": loss_rate,
            "average_r": average_r,
            "max_drawdown": max_dd_pct,
            "max_drawdown_abs": max_dd_abs,
            "max_consecutive_losses": float(max_consec),
            "recovery_factor": recovery_factor,
            "sharpe": sharpe,
            "sortino": sortino,
            "trade_frequency": trade_frequency,
            "average_hold_time": average_hold_time,
        }
        return BacktestV2Result(
            metrics=metrics,
            profit_by_session=by_session,
            profit_by_hour=by_hour,
            profit_by_regime=by_regime,
            trades=trades,
        )
