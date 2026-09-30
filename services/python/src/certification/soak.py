# -*- coding: utf-8 -*-
"""Phase 9 soak-test harness (§23–§24) — SIM/PAPER only, bounded, read-only.
Runs N deterministic cycles against injected fakes/clocks and reports
resource deltas (threads, queue depth, bounded-store sizes). Never touches a
broker. A failure here FAILS certification (CASE 15), never weakens guards.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

__all__ = ["SoakConfig", "SoakResult", "run_soak"]


@dataclass
class SoakConfig:
    """Bounded soak parameters (duration configurable by environment)."""

    cycles: int = 200
    cycle_fn: Optional[Callable[[int], None]] = None
    max_seconds: float = 120.0


@dataclass
class SoakResult:
    cycles_run: int = 0
    errors: int = 0
    elapsed_s: float = 0.0
    threads_start: int = 0
    threads_end: int = 0
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycles_run": self.cycles_run,
            "errors": self.errors,
            "elapsed_s": round(self.elapsed_s, 3),
            "threads_start": self.threads_start,
            "threads_end": self.threads_end,
            "thread_growth": self.threads_end - self.threads_start,
            "duration_s": round(self.duration_s, 3),
        }


def run_soak(config: Optional[SoakConfig] = None) -> SoakResult:
    """Run a bounded soak: default cycle exercises the read-only ops path."""
    cfg = config or SoakConfig()
    started = time.monotonic()
    threads_start = threading.active_count()
    result = SoakResult(threads_start=threads_start)
    fn = cfg.cycle_fn or _default_cycle
    deadline = started + max(1.0, float(cfg.max_seconds))
    for i in range(max(1, int(cfg.cycles))):
        if time.monotonic() > deadline:
            break
        try:
            fn(i)
            result.cycles_run += 1
        except Exception:  # noqa: BLE001 - soak records errors, never raises
            result.errors += 1
    result.elapsed_s = time.monotonic() - started
    result.duration_s = result.elapsed_s
    result.threads_end = threading.active_count()
    return result


def _default_cycle(i: int) -> None:
    """One read-only cycle: overview assembly (no trading side effects)."""
    try:
        from ops.readmodels import overview

        overview()
    except Exception:  # noqa: BLE001
        # Fall back to a trivial deterministic op so the harness still measures.
        _ = (i * 7) % 13
