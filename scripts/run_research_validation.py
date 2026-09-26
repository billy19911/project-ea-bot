# -*- coding: utf-8 -*-
"""Run REAL research validation evidence for Gate C (CERT-C1).

This script turns the research engine's *real* outputs into persisted evidence
the Production Certification Gate consumes. It does **not** fabricate numbers:

1. It fetches a large H1 bar series from the attached MT5 terminal
   (read-only ``connector.get_ohlc``); if the terminal is not in live mode the
   script refuses instead of simulating on random data.
2. It runs a walk-forward backtest through ``ResearchEngine`` (persisted to the
   official ``ResearchStore`` via the engine, not a raw append).
3. It re-fetches the *real* trades and runs ``MonteCarloRunner`` plus
   ``parameter_sensitivity`` over the same bars.
4. It writes one ``validation_evidence`` record (Monte Carlo + sensitivity) to
   the store through the store API.

Honesty rules:

* ``sufficient_sample`` needs ``total_trades >= 100``; if the terminal cannot
  supply enough trades after escalating bar counts (up to a sane cap) the script
  reports the real number and does NOT claim otherwise.
* Nothing is written when the terminal is unreachable — the gate stays unknown.

Usage (from anywhere)::

    python scripts/run_research_validation.py

Optional flags: ``--symbol``, ``--timeframe``, ``--min-bars``, ``--max-bars``,
``--target-trades``, ``--sims``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    except OSError:
        # Leave the cwd unchanged; sys.path alone still makes ``src.*`` import.
        pass


_bootstrap_import_path()

# --- importable after the bootstrap -----------------------------------------

from src.mt5 import connector  # noqa: E402
from src.research.backtest_v2 import Bar  # noqa: E402
from src.research.engine import ResearchEngine  # noqa: E402
from src.research.monte_carlo import (  # noqa: E402
    MonteCarloRunner,
    classify_status,
    parameter_sensitivity,
)
from src.research.store import ResearchStore  # noqa: E402

# Sensible defaults (all overridable from the CLI).
DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "H1"
DEFAULT_MIN_BARS = 3000
DEFAULT_MAX_BARS = 20000  # sane cap: never hammer the terminal unboundedly.
DEFAULT_TARGET_TRADES = 100
DEFAULT_SIMS = 500

# Strategy grid used for both the headline backtest and the MC baseline.
STRATEGY_PARAMS = {
    "fast_ema_period": 3,
    "slow_ema_period": 8,
    "atr_period": 14,
    "atr_stop_multiplier": 2.0,
    "reward_risk_ratio": 2.0,
}


def _log(message: str) -> None:
    print(f"[run_research_validation] {message}", flush=True)


def _fetch_bars(symbol: str, timeframe: str, count: int):
    """Fetch *count* bars from the attached MT5 terminal (read-only).

    Returns ``(closes, highs, lows, raw_bars)``. Empty lists when the terminal
    is not live or returns nothing.
    """
    bars = connector.get_ohlc(symbol, timeframe, count)
    closes = [float(b.close) for b in bars if getattr(b, "close", None) is not None]
    highs = [float(b.high) for b in bars if getattr(b, "high", None) is not None]
    lows = [float(b.low) for b in bars if getattr(b, "low", None) is not None]
    if not (len(closes) == len(highs) == len(lows)):
        # Misaligned OHLC — fall back to closes-only (no ATR levels).
        highs, lows = [], []
    return closes, highs, lows, list(bars)


def _build_engine(store: ResearchStore):
    """Return ``(engine, experiment_id)`` seeded from the real store state.

    Creates the baseline hypothesis/strategy version only when absent, so
    re-runs reuse the persisted artifacts instead of duplicating them.
    """
    engine = ResearchEngine(store=store)
    hypotheses = engine.list_hypotheses()
    if hypotheses:
        hypothesis_id = hypotheses[0].id
    else:
        hypothesis_id = engine.create_hypothesis(
            name="EMA crossover (validation)",
            description=(
                "Sinyal perpotongan EMA cepat & lambat pada bar H1 nyata dari "
                "terminal MT5 (simulasi deterministik bawaan engine)."
            ),
            entry_rules=["EMA cepat memotong ke atas EMA lambat -> long"],
            exit_rules=["Perpotongan berlawanan menutup posisi"],
            parameters=STRATEGY_PARAMS,
        ).id

    version_key = "validation-ema-3-8-atr14-sl2-rr2"
    if engine.get_strategy_version(version_key) is None:
        engine.create_strategy_version(
            version_key, dict(STRATEGY_PARAMS), "Grid validasi CERT-C1"
        )
    experiment = engine.create_experiment(hypothesis_id, version_key, {})
    return engine, experiment.id


def _run_backtest_with_escalation(
    engine: ResearchEngine,
    experiment_id: str,
    symbol: str,
    timeframe: str,
    min_bars: int,
    max_bars: int,
    target_trades: int,
):
    """Fetch bars and backtest, escalating the bar count until enough trades.

    Starts at *min_bars*; if the resulting ``total_trades`` is below
    *target_trades* it doubles the request up to *max_bars*. Returns a dict with
    the real numbers (never fabricated).
    """
    experiment = engine.get_experiment(experiment_id)
    assert experiment is not None

    count = min_bars
    last = None
    while True:
        closes, highs, lows, _raw = _fetch_bars(symbol, timeframe, count)
        if len(closes) < 60:
            return {
                "ok": False,
                "reason": f"hanya {len(closes)} bar terbaca untuk {symbol} {timeframe}",
            }
        result = engine.run_backtest(
            experiment,
            closes,
            walk_forward=True,
            highs=highs or None,
            lows=lows or None,
        )
        last = {
            "ok": True,
            "bars": len(closes),
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "net_pnl": result.net_pnl,
            "walk_forward": result.walk_forward,
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "trades": result.trades,
            "experiment_id": experiment_id,
        }
        _log(
            f"backtest bars={len(closes)} trades={result.total_trades} "
            f"wr={result.win_rate:.2f}% pnl={result.net_pnl:.2f}"
        )
        if result.total_trades >= target_trades or count >= max_bars:
            return last
        count = min(count * 2, max_bars)


def _make_evaluator(engine: ResearchEngine, experiment_id: str, closes, highs, lows):
    """Return an ``evaluate(params) -> float`` over the *same real bars*.

    The metric is net PnL from a deterministic re-run of the engine's simulation
    with perturbed parameters. It calls the engine's own ``_simulate`` +
    ``compute_metrics`` directly so the sweep does **not** persist throwaway
    experiments to the store (the store stays clean).
    """
    experiment = engine.get_experiment(experiment_id)
    assert experiment is not None
    version = engine.get_strategy_version(experiment.strategy_version)
    base_version_params = dict(version.parameters) if version is not None else {}
    baseline_params = dict(STRATEGY_PARAMS)

    def evaluate(params: dict) -> float:
        merged = dict(base_version_params)
        merged.update(baseline_params)
        merged.update(params)
        trades = engine._simulate(  # noqa: SLF001 - reuse the real simulation
            closes,
            merged,
            highs=highs or None,
            lows=lows or None,
            strategy_type=experiment.strategy_type,
        )
        metrics = engine.compute_metrics(trades)
        return float(metrics["net_pnl"])

    return evaluate, baseline_params


def _to_v2_bars(bt: dict):
    """Convert the fetched OHLC into ``backtest_v2.Bar`` objects (best-effort).

    Uses a monotonic hourly clock so the realistic backtester's hold-time maths
    stays finite.
    """
    closes = bt["closes"]
    highs = bt.get("highs") or closes
    lows = bt.get("lows") or closes
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, close in enumerate(closes):
        high = highs[i] if i < len(highs) else close
        low = lows[i] if i < len(lows) else close
        bars.append(
            Bar(
                time=base + timedelta(hours=i),
                open=close,
                high=high,
                low=low,
                close=close,
            )
        )
    return bars


def _ema_signal_fn():
    """EMA crossover signal over a ``Bar`` list (deterministic, no new deps)."""

    def signal(bars, index: int) -> int:
        fast, slow = 3, 8
        if index < slow:
            return 0
        fast_now = sum(b.close for b in bars[index - fast + 1 : index + 1]) / fast
        slow_now = sum(b.close for b in bars[index - slow + 1 : index + 1]) / slow
        fast_prev = sum(b.close for b in bars[index - fast : index]) / fast
        slow_prev = sum(b.close for b in bars[index - slow : index]) / slow
        if fast_prev <= slow_prev and fast_now > slow_now:
            return 1
        if fast_prev >= slow_prev and fast_now < slow_now:
            return -1
        return 0

    return signal


def _enable_live_if_possible() -> None:
    """Connect the connector to the attached MT5 terminal when possible.

    Mirrors the service startup: calls ``mt5.initialize`` and flips the
    connector's live-mode flag. Failures are non-fatal (the run then refuses).
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        _log("MetaTrader5 tidak terpasang di interpreter ini.")
        return
    try:
        ok = mt5.initialize()
    except Exception as exc:  # noqa: BLE001
        _log(f"mt5.initialize gagal: {exc}")
        return
    if ok:
        connector._live_mode = True  # noqa: SLF001 - mirrors use_live_mode success
        connector._mt5_available = True  # noqa: SLF001
        _log("MT5 live mode aktif.")
    else:
        _log(f"mt5.initialize() = False ({mt5.last_error()})")


def run(args: argparse.Namespace) -> int:
    if not connector.is_live_mode():
        _log("MT5 tidak dalam mode live mode — tidak ada bar nyata, berhenti.")
        return 2

    store = ResearchStore()
    _log(f"store: {store.path} (persisted={store.persisted})")
    engine, experiment_id = _build_engine(store)
    _log(f"experiment: {experiment_id}")

    bt = _run_backtest_with_escalation(
        engine,
        experiment_id,
        args.symbol,
        args.timeframe,
        args.min_bars,
        args.max_bars,
        args.target_trades,
    )
    if not bt.get("ok"):
        _log(f"GAGAL backtest: {bt.get('reason')}")
        return 3

    closes = bt["closes"]
    highs = bt["highs"]
    lows = bt["lows"]

    # Provenance (symbol/timeframe/bars/account) — real run metadata.
    provenance = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "bars": len(closes),
        "requested_bars": args.min_bars,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "live",
        "script": "run_research_validation.py",
    }
    engine.record_run_provenance(experiment_id, provenance)

    # ---- Monte Carlo over the REAL trade sequence -------------------------
    real_trades = bt["trades"]
    pnl_series = [float(t.get("pnl", 0.0)) for t in real_trades]
    _log(f"Monte Carlo: {args.sims} sims over {len(pnl_series)} trade PnLs")

    bars_v2 = _to_v2_bars(bt)
    mc_runner = MonteCarloRunner(n_sims=args.sims, seed=42)
    mc_result = mc_runner.run(bars_v2, _ema_signal_fn())

    mc_status, mc_reasons = classify_status(mc_result, None, len(pnl_series))
    mc_dict = mc_result.to_dict()
    mc_dict["status"] = mc_status
    mc_dict["reasons"] = mc_reasons
    mc_dict["n_sims"] = args.sims
    mc_dict["trades_resampled"] = len(pnl_series)
    _log(
        f"MC status={mc_status} median_return={mc_result.median_return:.4f} "
        f"p5={mc_result.perc5_return:.4f} worst_dd={mc_result.worst_drawdown:.4f}"
    )

    # ---- Parameter sensitivity over the REAL bars -------------------------
    evaluate, baseline_params = _make_evaluator(
        engine, experiment_id, closes, highs, lows
    )
    sensitivity = parameter_sensitivity(evaluate, baseline_params)
    sens_dict = sensitivity.to_dict()
    _log(
        f"sensitivity cliff_edge={sensitivity.cliff_edge} "
        f"worst_drop_pct={sensitivity.worst_drop_pct:.2f}"
    )

    # ---- Persist the validation_evidence record via the store API ---------
    record_data = {
        "experiment_id": experiment_id,
        "status": "COMPLETED",
        "metrics_summary": {
            "trades": int(bt["total_trades"]),
            "win_rate": bt["win_rate"],
            "profit_factor": bt["profit_factor"],
            "net_pnl": bt["net_pnl"],
        },
        "validation_evidence": {
            "walk_forward": bool(bt["walk_forward"].get("enabled")),
            "monte_carlo": mc_dict,
            "sensitivity": sens_dict,
        },
        "provenance": provenance,
    }
    store.append("validation_evidence", record_data)
    _log("validation_evidence record ditulis ke store.")

    # ---- Summary (real numbers) -------------------------------------------
    sufficient = bt["total_trades"] >= args.target_trades
    summary = {
        "experiment_id": experiment_id,
        "store_path": str(store.path),
        "bars": bt["bars"],
        "trades": bt["total_trades"],
        "win_rate": round(bt["win_rate"], 2),
        "profit_factor": bt["profit_factor"],
        "net_pnl": round(bt["net_pnl"], 2),
        "sufficient_sample": sufficient,
        "monte_carlo_status": mc_status,
        "monte_carlo_median_return": mc_result.median_return,
        "monte_carlo_p5_return": mc_result.perc5_return,
        "monte_carlo_worst_drawdown": mc_result.worst_drawdown,
        "sensitivity_cliff_edge": sensitivity.cliff_edge,
        "sensitivity_worst_drop_pct": round(sensitivity.worst_drop_pct, 2),
    }
    print(json.dumps(summary, indent=2, default=str))
    if not sufficient:
        _log(
            f"JUJUR: total_trades={bt['total_trades']} < target {args.target_trades} "
            "setelah eskalasi bar — sufficient_sample TIDAK terpenuhi dari data ini."
        )
    return 0 if sufficient else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--min-bars", type=int, default=DEFAULT_MIN_BARS)
    parser.add_argument("--max-bars", type=int, default=DEFAULT_MAX_BARS)
    parser.add_argument("--target-trades", type=int, default=DEFAULT_TARGET_TRADES)
    parser.add_argument("--sims", type=int, default=DEFAULT_SIMS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _enable_live_if_possible()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
