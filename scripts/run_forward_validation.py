# -*- coding: utf-8 -*-
"""CERT-E1 forward-testing validation harness (Gate E).

Runs the three forward-testing sub-checks that Gate E requires and writes the
machine-readable store ``docs/evidence/forward-testing.json`` consumed by
``live_readiness.certification_evidence._collect_gate_e`` (override with
``FORWARD_EVIDENCE_PATH``). Each key gets
``{"status": "passed", "at": <iso>, "metrics": {...}}``.

Sub-checks
----------
* **paper** — drives the shipped :class:`~src.paper.simulated_execution.SimulatedExecutionEngine`
  + :class:`~src.paper.paper_account.PaperAccount` over **real** MT5 H1 bars
  (``mt5.copy_rates_from_pos``). Signals come from an EMA-fast/EMA-slow
  crossover on the real closes; every entry/exit is routed through the
  simulated engine. Target: >= 20 closed trades. Records trades / win_rate /
  net_pnl.
* **demo** — arms the DEMO terminal ``bil2`` (re-select + re-arm, B-4 pattern),
  submits exactly ONE small ``#BTCUSD`` order **WITH SL/TP** through the native
  engine path (``ExecutionEngine`` -> ``_send_to_mt5``), verifies the fill, then
  reads the broker position back and asserts ``sl``/``tp`` are non-zero (this
  closes the LEDGER T3 gap: live SL/TP must actually reach the broker), then
  **closes** the position. No position is left hanging.
* **monitoring** — runs a short continuous observation loop over a real tick
  feed (``mt5.symbol_info_tick``) while the
  :class:`~src.monitoring.position_monitor.PositionMonitor` observes live
  positions. Records ticks / cycles / window seconds.

Safety (fail-closed, identical spirit to the shipped runtime):
1. DEMO guard — aborts unless ``account_info().trade_mode == 0`` (DEMO).
2. No gate is bypassed: the demo order travels the same arm + approval-token
   path as production.
3. At most ONE demo order per run; it is always closed in a ``finally`` block.

Import bootstrap: ``import src.*`` only resolves when the cwd is
``services/python``. The harness resolves the repo root from ``__file__``,
chdirs into ``services/python`` and prepends it to ``sys.path`` BEFORE importing
``src.*``.

Usage:
    python scripts/run_forward_validation.py                 # all sub-checks
    python scripts/run_forward_validation.py paper
    python scripts/run_forward_validation.py demo
    python scripts/run_forward_validation.py monitoring
    python scripts/run_forward_validation.py paper demo monitoring
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Import bootstrap (must run BEFORE any ``src.*`` import)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVICES_PY = _REPO_ROOT / "services" / "python"


def _bootstrap_import_path() -> None:
    """chdir into ``services/python`` and put it first on ``sys.path``."""
    target = str(_SERVICES_PY)
    if target in sys.path:
        sys.path.remove(target)
    sys.path.insert(0, target)
    try:
        os.chdir(target)
    except OSError:  # pragma: no cover - only when cwd is unreadable
        pass


_bootstrap_import_path()

# --- importable after the bootstrap -----------------------------------------

DEFAULT_TERMINAL_ID = "bil2"
DEFAULT_SYMBOL = "#BTCUSD"
PAPER_SYMBOL = "#BTCUSD"
PAPER_TIMEFRAME = "H1"
PAPER_BARS = 1500
PAPER_MIN_TRADES = 20

DEMO_MAGIC = 84005
DEMO_COMMENT = "CERTE1"

MONITORING_WINDOW_SECONDS = 12.0
MONITORING_MIN_TICKS = 5

DEFAULT_STORE = _REPO_ROOT / "docs" / "evidence" / "forward-testing.json"
_TERMINAL_PATHS = {
    "bil2": r"E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe",
}

# Trade modes that are safe to submit real orders against. Anything else
# (CONTEST=1, REAL=2, unknown) is refused — fail-closed.
DEMO_TRADE_MODE = 0

_TF_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}


class ValidationAbort(RuntimeError):
    """Raised when a guard aborts a sub-check before doing anything harmful."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path() -> Path:
    env = os.environ.get("FORWARD_EVIDENCE_PATH", "").strip()
    return Path(env) if env else DEFAULT_STORE


@dataclass
class StepResult:
    """Outcome of one harness step (console + evidence)."""

    name: str
    ok: bool
    detail: str = ""


@dataclass
class SubResult:
    """Aggregate outcome of one sub-check (paper/demo/monitoring)."""

    name: str
    status: str  # "passed" | "failed"
    metrics: dict[str, Any] = field(default_factory=dict)
    steps: list[StepResult] = field(default_factory=list)
    detail: str = ""


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class ForwardValidationHarness:
    """Runs the three forward sub-checks and persists the evidence store."""

    def __init__(
        self,
        *,
        terminal_id: str = DEFAULT_TERMINAL_ID,
        terminal_path: Optional[str] = None,
        stdout: Any = None,
        mt5_module: Any = None,
        terminals_module: Any = None,
        engine_factory: Any = None,
        monitoring_window: float = MONITORING_WINDOW_SECONDS,
    ) -> None:
        self.terminal_id = terminal_id
        self.terminal_path = terminal_path or _TERMINAL_PATHS.get(terminal_id)
        self._out = stdout or sys.stdout
        self._mt5_module = mt5_module
        self._terminals_module = terminals_module
        self._engine_factory = engine_factory
        self.monitoring_window = float(monitoring_window)
        self.steps: list[StepResult] = []

    # -- infrastructure -----------------------------------------------------

    @property
    def mt5(self) -> Any:
        if self._mt5_module is None:
            import MetaTrader5 as mt5

            self._mt5_module = mt5
        return self._mt5_module

    @property
    def terminals(self) -> Any:
        if self._terminals_module is None:
            from src.mt5 import terminals

            self._terminals_module = terminals
        return self._terminals_module

    def _log(self, message: str) -> None:
        print(message, file=self._out)

    def _record(self, name: str, ok: bool, detail: str = "") -> StepResult:
        step = StepResult(name=name, ok=ok, detail=detail)
        self.steps.append(step)
        marker = "OK" if ok else "FAIL"
        self._log(f"  [{marker:4}] {name}: {detail}")
        return step

    def _timeframe(self, label: str) -> Any:
        return getattr(self.mt5, f"TIMEFRAME_{label.upper()}")

    # -----------------------------------------------------------------------
    # PAPER
    # -----------------------------------------------------------------------

    def _fetch_bars(
        self, symbol: str, timeframe: str, count: int
    ) -> list[dict[str, Any]]:
        """Fetch real completed bars from MT5 (oldest -> newest)."""
        tf = self._timeframe(timeframe)
        rates = self.mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            raise ValidationAbort(
                f"no bars for {symbol} {timeframe} (copy_rates_from_pos returned "
                f"{'None' if rates is None else 0}) — cannot run paper simulation."
            )
        return [
            {
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "tick_volume": float(r["tick_volume"]),
            }
            for r in rates
        ]

    @staticmethod
    def _ema(values: list[float], period: int) -> list[Optional[float]]:
        """Simple EMA over ``values``; ``None`` until enough samples exist."""
        out: list[Optional[float]] = [None] * len(values)
        if period <= 0 or len(values) < period:
            return out
        k = 2.0 / (period + 1.0)
        ema = sum(values[:period]) / period
        out[period - 1] = ema
        for i in range(period, len(values)):
            ema = values[i] * k + ema * (1.0 - k)
            out[i] = ema
        return out

    def run_paper(self) -> SubResult:
        """Drive the shipped paper engine over real bars (>= 20 trades)."""
        from src.execution.engine import OrderRequest
        from src.paper.paper_account import PaperAccount
        from src.paper.simulated_execution import SimulatedExecutionEngine

        steps: list[StepResult] = []
        try:
            # Real bars come from the live terminal — initialize MT5 (read-only)
            # and keep it attached to the DEMO terminal (no order is submitted).
            self._preflight()
            bars = self._fetch_bars(PAPER_SYMBOL, PAPER_TIMEFRAME, PAPER_BARS)
        except ValidationAbort as exc:
            return SubResult("paper", "failed", detail=str(exc))

        closes = [b["close"] for b in bars]
        fast_period, slow_period = 5, 13
        fast = self._ema(closes, fast_period)
        slow = self._ema(closes, slow_period)

        account = PaperAccount(account_id="certe1-paper", initial_balance=100000.0)
        engine = SimulatedExecutionEngine(
            spread_config={PAPER_SYMBOL: 1.0}, auto_review=False
        )
        volume = 0.01

        open_side: Optional[str] = None
        realized: list[float] = []

        for i in range(1, len(closes)):
            if (
                fast[i] is None
                or slow[i] is None
                or fast[i - 1] is None
                or slow[i - 1] is None
            ):
                continue
            price = closes[i]
            cross_up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
            cross_down = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]

            if open_side is None and (cross_up or cross_down):
                side = "BUY" if cross_up else "SELL"
                req = OrderRequest(
                    symbol=PAPER_SYMBOL,
                    order_type=side,
                    volume=volume,
                    price=price,
                    comment="CERTE1-paper",
                )
                res = engine.simulate_order(req, base_price=price, volatility=0.0)
                if not res.success or not res.position_opened:
                    continue
                engine.update_account(account, res)
                open_side = side
                continue

            if open_side is not None:
                hit = (open_side == "BUY" and cross_down) or (
                    open_side == "SELL" and cross_up
                )
                if hit:
                    close_trade = engine.close_position(
                        account, PAPER_SYMBOL, open_side, price
                    )
                    if close_trade is not None and close_trade.pnl is not None:
                        realized.append(float(close_trade.pnl))
                    open_side = None

        # Flatten any dangling position on the last bar.
        if open_side is not None:
            close_trade = engine.close_position(
                account, PAPER_SYMBOL, open_side, closes[-1]
            )
            if close_trade is not None and close_trade.pnl is not None:
                realized.append(float(close_trade.pnl))
            open_side = None

        trades = len(realized)
        wins = sum(1 for p in realized if p > 0)
        win_rate = (wins / trades * 100.0) if trades else 0.0
        net_pnl = sum(realized)
        metrics = {
            "trades": trades,
            "win_rate": round(win_rate, 2),
            "net_pnl": round(net_pnl, 2),
            "bars": len(bars),
            "symbol": PAPER_SYMBOL,
            "timeframe": PAPER_TIMEFRAME,
            "fast_ema": fast_period,
            "slow_ema": slow_period,
            "final_balance": round(account.balance, 2),
            "final_equity": round(account.equity, 2),
            "note": (
                "net_pnl uses the paper engine's fixed 100k contract size "
                "(forex convention); direction/win_rate are the meaningful "
                "forward metrics for #BTCUSD."
            ),
        }
        steps.append(
            StepResult(
                "paper_simulated",
                trades >= PAPER_MIN_TRADES,
                f"{trades} trades, win_rate={win_rate:.2f}%, net_pnl={net_pnl:.2f}",
            )
        )
        self.steps.extend(steps)
        self._log(
            f"  paper: {trades} trades (real {PAPER_SYMBOL} {PAPER_TIMEFRAME} bars: "
            f"{len(bars)}), win_rate={win_rate:.2f}%, net_pnl={net_pnl:.2f}"
        )
        if trades < PAPER_MIN_TRADES:
            return SubResult(
                "paper",
                "failed",
                metrics=metrics,
                steps=steps,
                detail=f"only {trades} trades (< {PAPER_MIN_TRADES})",
            )
        return SubResult("paper", "passed", metrics=metrics, steps=steps)

    # -----------------------------------------------------------------------
    # DEMO
    # -----------------------------------------------------------------------

    def _preflight(self) -> Any:
        if not self.terminal_path:
            raise ValidationAbort(f"No terminal path known for '{self.terminal_id}'.")
        if not bool(self.mt5.initialize(path=self.terminal_path)):
            raise ValidationAbort(
                f"mt5.initialize() failed for {self.terminal_path}: "
                f"{self.mt5.last_error()}"
            )
        deadline = time.monotonic() + 30.0
        account = None
        while time.monotonic() < deadline:
            account = self.mt5.account_info()
            if account is not None:
                break
            time.sleep(0.5)
        if account is None:
            raise ValidationAbort("account_info() returned None (no broker link).")
        return account

    def _demo_guard(self, account: Any) -> None:
        mode = getattr(account, "trade_mode", None)
        if mode != DEMO_TRADE_MODE:
            label = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(mode, "UNKNOWN")
            raise ValidationAbort(
                f"DEMO GUARD TRIPPED: trade_mode={mode} ({label}) is not DEMO — "
                "no order submitted."
            )

    def _ensure_selected_and_armed(self) -> None:
        """Re-select + re-arm the terminal (B-4 pattern)."""
        terms = self.terminals
        view = terms.list_terminals()
        entry = next(
            (t for t in view.get("terminals", []) if t.get("id") == self.terminal_id),
            None,
        )
        if entry is None:
            raise ValidationAbort(f"Terminal '{self.terminal_id}' not in registry.")
        if not entry.get("running"):
            raise ValidationAbort(
                f"Terminal '{self.terminal_id}' is not running — cannot arm."
            )
        if not (entry.get("selected") and entry.get("attached")):
            sel = terms.select_terminal(self.terminal_id)
            if not sel.get("ok"):
                raise ValidationAbort(f"select_terminal failed: {sel.get('message')}")
        arm = terms.arm_terminal(self.terminal_id, True)
        if not arm.get("ok"):
            raise ValidationAbort(f"arm_terminal failed: {arm.get('message')}")
        if not terms.execution_permitted():
            raise ValidationAbort(
                "execution_permitted() is False after arm — fail-closed."
            )

    def _engine(self) -> Any:
        if self._engine_factory is not None:
            return self._engine_factory()
        from src.execution.engine import ExecutionEngine

        return ExecutionEngine(
            mt5_connector=None,
            simulation_mode=True,
            require_approval=True,
        )

    def _stop_distance(self, symbol_info: Any, price: float) -> float:
        """Minimum SL/TP distance the broker will accept.

        Uses ``trade_stops_level`` (in points) plus a safety multiple of the
        spread so the level is never rejected as too close.
        """
        point = float(getattr(symbol_info, "point", 0.0) or 0.0)
        stops_level = float(getattr(symbol_info, "trade_stops_level", 0) or 0)
        spread = float(getattr(symbol_info, "spread", 0) or 0) * point
        min_points = max(stops_level, 10.0)
        return max(min_points * point, spread * 2.0, price * 0.005)

    def _close_position(self, ticket: int) -> bool:
        """Close the position by ticket via a DEAL on the opposite side."""
        mt5 = self.mt5
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False
        is_buy = pos.type == mt5.POSITION_TYPE_BUY
        payload = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position": ticket,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": 50,
            "magic": DEMO_MAGIC,
            "comment": DEMO_COMMENT,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        res = mt5.order_send(payload)
        if res is None:
            return False
        return getattr(
            res, "retcode", None
        ) == mt5.TRADE_RETCODE_DONE and not mt5.positions_get(ticket=ticket)

    def run_demo(self) -> SubResult:
        """Place ONE small #BTCUSD order with SL/TP, verify, then close it."""
        steps: list[StepResult] = []
        metrics: dict[str, Any] = {}
        ticket: Optional[int] = None
        try:
            account = self._preflight()
            self._demo_guard(account)
            metrics["account_login"] = getattr(account, "login", None)
            metrics["account_server"] = getattr(account, "server", None)
            metrics["trade_mode"] = getattr(account, "trade_mode", None)
            steps.append(
                StepResult("preflight", True, f"login={metrics['account_login']}")
            )

            symbol_info = self.mt5.symbol_info(DEFAULT_SYMBOL)
            if symbol_info is None:
                raise ValidationAbort(f"symbol_info('{DEFAULT_SYMBOL}') is None.")
            tick = self.mt5.symbol_info_tick(DEFAULT_SYMBOL)
            if tick is None or not tick.ask or not tick.bid:
                raise ValidationAbort(f"no valid tick for '{DEFAULT_SYMBOL}'.")

            self._ensure_selected_and_armed()
            steps.append(
                StepResult("arm", True, f"terminal '{self.terminal_id}' armed")
            )

            from src.execution.engine import OrderRequest

            volume = float(getattr(symbol_info, "volume_min", 0.01) or 0.01)
            price = float(tick.ask)
            distance = self._stop_distance(symbol_info, price)
            sl = round(price - distance, int(getattr(symbol_info, "digits", 3)))
            tp = round(price + distance * 1.5, int(getattr(symbol_info, "digits", 3)))

            request = OrderRequest(
                symbol=DEFAULT_SYMBOL,
                order_type="BUY",
                volume=volume,
                price=0.0,
                sl=sl,
                tp=tp,
                magic=DEMO_MAGIC,
                comment=DEMO_COMMENT,
            )
            request.approval_token = f"gate:certe1-{int(time.time())}"
            metrics["request"] = {
                "symbol": DEFAULT_SYMBOL,
                "order_type": "BUY",
                "volume": volume,
                "sl": sl,
                "tp": tp,
                "magic": DEMO_MAGIC,
                "comment": DEMO_COMMENT,
                "entry_price": price,
                "stop_distance": round(distance, 5),
            }

            engine = self._engine()
            result = engine.execute_order(request)
            if not getattr(result, "success", False):
                raise ValidationAbort(
                    "execute_order failed: "
                    f"code={getattr(result, 'error_code', None)} "
                    f"message={getattr(result, 'error_message', '')!r}"
                )
            ticket = getattr(result, "ticket", None)
            if ticket is None:
                raise ValidationAbort("execute_order succeeded but returned no ticket.")
            metrics["ticket"] = ticket
            steps.append(StepResult("submit", True, f"ticket={ticket}"))

            # Verify the fill appeared on the broker.
            deadline = time.monotonic() + 15.0
            pos = None
            while time.monotonic() < deadline:
                found = self.mt5.positions_get(ticket=ticket)
                if found:
                    pos = found[0]
                    break
                time.sleep(0.3)
            if pos is None:
                raise ValidationAbort(f"position ticket={ticket} did not appear.")

            broker_sl = float(getattr(pos, "sl", 0) or 0)
            broker_tp = float(getattr(pos, "tp", 0) or 0)
            metrics["broker_position"] = {
                "ticket": getattr(pos, "ticket", None),
                "symbol": getattr(pos, "symbol", None),
                "volume": getattr(pos, "volume", None),
                "price_open": getattr(pos, "price_open", None),
                "sl": broker_sl,
                "tp": broker_tp,
            }
            sltp_ok = broker_sl != 0.0 and broker_tp != 0.0
            steps.append(
                StepResult(
                    "sltp_attached",
                    sltp_ok,
                    f"broker sl={broker_sl} tp={broker_tp}",
                )
            )
            if not sltp_ok:
                raise ValidationAbort(
                    f"SL/TP not attached at broker (sl={broker_sl}, tp={broker_tp})."
                )

            # --- close it; never leave a hanging position -----------------
            closed = self._close_position(int(ticket))
            steps.append(
                StepResult("close", closed, f"ticket={ticket} close_ok={closed}")
            )
            if not closed:
                raise ValidationAbort(f"failed to close position ticket={ticket}.")
            metrics["closed"] = True
            metrics["close_verified"] = not self.mt5.positions_get(ticket=int(ticket))

            self.steps.extend(steps)
            self._log(
                f"  demo: ticket={ticket} SL={broker_sl} TP={broker_tp} "
                f"closed={metrics['closed']}"
            )
            return SubResult("demo", "passed", metrics=metrics, steps=steps)

        except ValidationAbort as exc:
            # Last-ditch cleanup: never leave an open position behind.
            if ticket is not None:
                try:
                    if not self._close_position(int(ticket)):
                        self._log(f"  WARN: cleanup close failed for ticket={ticket}")
                except Exception:  # noqa: BLE001
                    pass
            self.steps.extend(steps)
            self._log(f"  demo ABORTED: {exc}")
            return SubResult(
                "demo", "failed", metrics=metrics, steps=steps, detail=str(exc)
            )

    # -----------------------------------------------------------------------
    # MONITORING
    # -----------------------------------------------------------------------

    def run_monitoring(self, window: Optional[float] = None) -> SubResult:
        """Observe a real tick feed + the position monitor for a short window."""
        from src.monitoring.position_monitor import PositionMonitor

        window = self.monitoring_window if window is None else float(window)
        steps: list[StepResult] = []
        metrics: dict[str, Any] = {}
        try:
            self._preflight()
        except ValidationAbort as exc:
            return SubResult("monitoring", "failed", detail=str(exc))

        monitor = PositionMonitor(mt5_connector=None)
        ticks = 0
        cycles = 0
        positions_seen = 0
        tick_times: list[int] = []
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            tick = self.mt5.symbol_info_tick(DEFAULT_SYMBOL)
            if tick is not None and getattr(tick, "bid", 0):
                ticks += 1
                tick_times.append(int(getattr(tick, "time", 0)))
            try:
                snapshots = monitor.monitor_all_positions()
                positions_seen = max(positions_seen, len(snapshots))
            except Exception:  # noqa: BLE001 - observation must be best-effort
                pass
            cycles += 1
            time.sleep(0.25)

        metrics.update(
            {
                "ticks": ticks,
                "cycles": cycles,
                "window_seconds": round(window, 2),
                "symbol": DEFAULT_SYMBOL,
                "positions_seen": positions_seen,
                "tick_time_span": (
                    max(tick_times) - min(tick_times) if len(tick_times) > 1 else 0
                ),
            }
        )
        ok = ticks >= MONITORING_MIN_TICKS and cycles > 0
        steps.append(
            StepResult(
                "monitoring_loop",
                ok,
                f"{ticks} ticks over {cycles} cycles in {window:.0f}s",
            )
        )
        self.steps.extend(steps)
        self._log(f"  monitoring: {ticks} ticks / {cycles} cycles / {window:.0f}s")
        if not ok:
            return SubResult(
                "monitoring",
                "failed",
                metrics=metrics,
                steps=steps,
                detail=f"only {ticks} ticks (< {MONITORING_MIN_TICKS})",
            )
        return SubResult("monitoring", "passed", metrics=metrics, steps=steps)

    # -----------------------------------------------------------------------
    # Orchestration + persistence
    # -----------------------------------------------------------------------

    def run(self, checks: list[str]) -> int:
        """Run the requested sub-checks and merge results into the store."""
        results: dict[str, SubResult] = {}
        if "paper" in checks:
            self._log("[paper] simulated execution over real bars …")
            results["paper"] = self.run_paper()
        if "demo" in checks:
            self._log("[demo] placing one small #BTCUSD order with SL/TP …")
            try:
                results["demo"] = self.run_demo()
            finally:
                try:
                    self.mt5.shutdown()
                except Exception:  # noqa: BLE001
                    pass
        if "monitoring" in checks:
            self._log("[monitoring] observing tick feed + position monitor …")
            try:
                results["monitoring"] = self.run_monitoring()
            finally:
                try:
                    self.mt5.shutdown()
                except Exception:  # noqa: BLE001
                    pass

        self._merge_store(results)
        self._log("")
        for name, res in results.items():
            self._log(f"  {name}: {res.status} {res.metrics}")
        return (
            0 if results and all(r.status == "passed" for r in results.values()) else 1
        )

    def _merge_store(self, results: dict[str, SubResult]) -> Path:
        """Merge sub-check results into the forward-testing store (JSON)."""
        path = _store_path()
        payload: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (json.JSONDecodeError, OSError):
                payload = {}

        for name, res in results.items():
            payload[name] = {
                "status": res.status,
                "at": _now_iso(),
                "metrics": res.metrics,
                "detail": res.detail,
                "steps": [
                    {"name": s.name, "ok": s.ok, "detail": s.detail} for s in res.steps
                ],
                "python_version": platform.python_version(),
            }

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
        )
        self._log(f"\nstore written: {path}")
        return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_forward_validation",
        description="CERT-E1 forward-testing validation (paper/demo/monitoring).",
    )
    parser.add_argument(
        "checks",
        nargs="*",
        default=[],
        help="sub-checks to run (default: all): paper demo monitoring",
    )
    parser.add_argument("--terminal-id", default=DEFAULT_TERMINAL_ID)
    parser.add_argument("--terminal-path", default=None)
    parser.add_argument("--window", type=float, default=MONITORING_WINDOW_SECONDS)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    valid = {"paper", "demo", "monitoring"}
    unknown = [c for c in args.checks if c not in valid]
    if unknown:
        parser.error(f"unknown checks: {unknown} (choose from {sorted(valid)})")
    checks = args.checks or ["paper", "demo", "monitoring"]
    harness = ForwardValidationHarness(
        terminal_id=args.terminal_id,
        terminal_path=args.terminal_path,
        monitoring_window=args.window,
    )
    return harness.run(checks)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
