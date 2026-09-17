# -*- coding: utf-8 -*-
"""Daily trading report — REAL closed deals from the attached MT5 terminal.

UI/UX ide #9. Read-only by construction:

- only calls ``mt5.history_deals_get`` on the CURRENT binding (no re-bind,
  no login, no orders, no arm changes);
- when live mode is off, or MT5 returns no data, the report says so honestly
  instead of fabricating numbers;
- aggregation is a pure function so it can be unit-tested without MT5.

Deal ``entry`` values (MT5): 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY. A *closed*
trade is a deal with ``entry`` in (1, 3) — those carry the realized profit.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

MAX_DAYS = 90
DEFAULT_DAYS = 7

# MT5 deal entry constants that represent a realized (closed) trade.
_ENTRY_OUT = 1
_ENTRY_OUT_BY = 3


def _to_float(value: Any) -> float:
    """Coerce an MT5 numeric field to float; ``None`` becomes 0.0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_deal(deal: Any) -> dict:
    """Flatten one MT5 deal into the plain dict used by the aggregator.

    Works with MetaTrader5 named-tuples (attribute access). Missing fields
    become ``None``/0 honestly — never guessed.
    """
    return {
        "ts": int(getattr(deal, "time", 0) or 0),
        "ticket": getattr(deal, "ticket", None),
        "symbol": str(getattr(deal, "symbol", "") or ""),
        "entry": int(getattr(deal, "entry", 0) or 0),
        "volume": _to_float(getattr(deal, "volume", 0)),
        "price": _to_float(getattr(deal, "price", 0)),
        "profit": _to_float(getattr(deal, "profit", 0)),
        "commission": _to_float(getattr(deal, "commission", 0)),
        "swap": _to_float(getattr(deal, "swap", 0)),
    }


def aggregate_deals(deals: list[dict], days: int) -> dict:
    """Aggregate normalized deals into a per-day + per-symbol report.

    Pure function: takes the normalized dicts from :func:`normalize_deal`.
    Only *closed* deals (entry 1/3) count towards wins/losses and PnL;
    commission and swap of every deal in the period are still summed into
    the day they belong to, so the net is complete.
    """
    cutoff = datetime.now() - timedelta(days=days)
    by_day: dict[str, dict] = {}
    by_symbol: dict[str, dict] = {}

    for d in deals:
        ts = d.get("ts") or 0
        if ts <= 0:
            continue
        moment = datetime.fromtimestamp(ts)
        if moment < cutoff:
            continue
        day = moment.strftime("%Y-%m-%d")

        bucket = by_day.setdefault(
            day,
            {
                "date": day,
                "deals": 0,
                "closed": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0,
                "net": 0.0,
                "best": None,
                "worst": None,
            },
        )
        bucket["deals"] += 1
        bucket["net"] += d["profit"] + d["commission"] + d["swap"]

        closed = d["entry"] in (_ENTRY_OUT, _ENTRY_OUT_BY)
        if closed:
            bucket["closed"] += 1
            pnl = d["profit"] + d["commission"] + d["swap"]
            if pnl > 0:
                bucket["wins"] += 1
            elif pnl < 0:
                bucket["losses"] += 1
            else:
                bucket["breakeven"] += 1
            if bucket["best"] is None or pnl > bucket["best"]:
                bucket["best"] = pnl
            if bucket["worst"] is None or pnl < bucket["worst"]:
                bucket["worst"] = pnl

            sym = by_symbol.setdefault(
                d["symbol"] or "(tanpa simbol)",
                {"symbol": d["symbol"] or "(tanpa simbol)", "closed": 0, "wins": 0, "net": 0.0},
            )
            sym["closed"] += 1
            if pnl > 0:
                sym["wins"] += 1
            sym["net"] += pnl

    daily = sorted(by_day.values(), key=lambda b: b["date"], reverse=True)
    for b in daily:
        decided = b["wins"] + b["losses"]
        b["win_rate"] = round(b["wins"] / decided, 4) if decided else None

    symbols = sorted(by_symbol.values(), key=lambda s: abs(s["net"]), reverse=True)[:10]
    for s in symbols:
        s["win_rate"] = round(s["wins"] / s["closed"], 4) if s["closed"] else None

    totals = {
        "deals": sum(b["deals"] for b in daily),
        "closed": sum(b["closed"] for b in daily),
        "wins": sum(b["wins"] for b in daily),
        "losses": sum(b["losses"] for b in daily),
        "net": round(sum(b["net"] for b in daily), 2),
    }
    decided = totals["wins"] + totals["losses"]
    totals["win_rate"] = round(totals["wins"] / decided, 4) if decided else None
    best_day = max(daily, key=lambda b: b["net"], default=None)
    worst_day = min(daily, key=lambda b: b["net"], default=None)
    totals["best_day"] = (
        {"date": best_day["date"], "net": round(best_day["net"], 2)} if best_day else None
    )
    totals["worst_day"] = (
        {"date": worst_day["date"], "net": round(worst_day["net"], 2)} if worst_day else None
    )

    return {"totals": totals, "daily": daily, "symbols": symbols}


def build_daily_report(days: int = DEFAULT_DAYS) -> dict:
    """Build the report from the CURRENTLY attached terminal (read-only).

    Never re-binds the process-wide connection: it reads whatever terminal
    the operator already selected. All failure modes return ``ok: false``
    with a human-readable reason — the UI must not show fake zeros.
    """
    days = max(1, min(int(days or DEFAULT_DAYS), MAX_DAYS))

    from ..mt5 import connector

    if not connector.is_live_mode():
        return {
            "ok": False,
            "reason": "MT5 tidak dalam mode data live — laporan tidak tersedia.",
            "days": days,
        }

    try:
        import MetaTrader5 as mt5
    except ImportError:
        return {"ok": False, "reason": "Paket MetaTrader5 tidak terpasang.", "days": days}

    info = mt5.account_info()
    if info is None:
        return {
            "ok": False,
            "reason": "account_info() tidak mengembalikan data — terminal mungkin terputus.",
            "days": days,
        }

    date_to = datetime.now()
    date_from = date_to - timedelta(days=days)
    try:
        deals = mt5.history_deals_get(date_from, date_to)
    except Exception as exc:  # never let a terminal hiccup crash the endpoint
        return {"ok": False, "reason": f"history_deals_get gagal: {exc}"[:200], "days": days}

    if deals is None:
        code, msg = mt5.last_error()
        return {
            "ok": False,
            "reason": f"history_deals_get mengembalikan None (error {code}: {msg}).",
            "days": days,
        }

    normalized = [normalize_deal(d) for d in deals]
    report = aggregate_deals(normalized, days)

    return {
        "ok": True,
        "days": days,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "account": {
            "login": getattr(info, "login", None),
            "server": getattr(info, "server", None),
            "currency": getattr(info, "currency", None),
            "balance": _to_float(getattr(info, "balance", 0)),
            "equity": _to_float(getattr(info, "equity", 0)),
        },
        # Label waktu: MT5 mengembalikan waktu server broker; tanggal di sini
        # memakai zona waktu mesin ini — UI menyebutkannya supaya jujur.
        "note": "Tanggal mengikuti zona waktu mesin ini.",
        **report,
    }
