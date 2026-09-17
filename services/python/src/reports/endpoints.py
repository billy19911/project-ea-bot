# -*- coding: utf-8 -*-
"""Reports FastAPI router — read-only daily trading report (UI/UX ide #9)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from .daily import DEFAULT_DAYS, MAX_DAYS, build_daily_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/daily")
async def get_daily_report(days: int = Query(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS)) -> dict:
    """Daily PnL report from REAL closed deals on the attached terminal.

    Read-only: never re-binds the terminal, never sends orders. When data is
    unavailable the payload says ``ok: false`` with a reason — no fake zeros.
    """
    return build_daily_report(days)
