# -*- coding: utf-8 -*-
"""Live-attach wrapper for the stale-ledger backfill (LEDGER-SLTP T2 ops).

``scripts/ledger_close_stale.py`` is fail-closed by design (dry-run default +
verified broker read), but when run standalone its ``src.mt5.connector`` stays
in SIMULATION mode: ``get_positions_ex()`` then returns the two synthetic demo
positions (tickets 1001/1002) with ``ok=True``, so every real ledger ticket
looks "absent from the broker" and the verified-read signal is meaningless.

This wrapper attaches the connector to the REAL MT5 terminal (read-only
``use_live_data_mode``) before delegating to the same ``StaleBackfill`` flow:

1. abort (exit 2) unless the terminal path exists and the attach succeeds;
2. abort (exit 2) unless the broker position read is verified (``ok=True``);
3. delegate — dry-run by default, ``--apply`` appends the ``closed`` records.

Usage:
    python scripts/ledger_backfill_live.py                       # dry-run
    python scripts/ledger_backfill_live.py --apply
    python scripts/ledger_backfill_live.py --terminal <path-to-terminal64.exe>
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Same demo terminal the B-4 harness uses; env override wins.
_DEFAULT_TERMINAL = os.getenv("MT5_TERMINAL_PATH") or (
    r"E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe"
)


def _load_backfill_module() -> Any:
    """Load ``scripts/ledger_close_stale.py`` as a module (no ``src.*`` yet)."""
    import sys

    path = _REPO_ROOT / "scripts" / "ledger_close_stale.py"
    spec = importlib.util.spec_from_file_location("ledger_close_stale", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: @dataclass resolves ``cls.__module__`` via
    # sys.modules at decoration time (a missing entry raises AttributeError).
    sys.modules.setdefault("ledger_close_stale", module)
    spec.loader.exec_module(module)
    return module


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Attach the MT5 connector live (read-only) and run the stale-ledger "
            "backfill from scripts/ledger_close_stale.py."
        )
    )
    parser.add_argument(
        "--terminal", default=_DEFAULT_TERMINAL, help="Path to terminal64.exe."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write the closed records."
    )
    parser.add_argument("--ticket", default=None, help="Optional single-ticket filter.")
    parser.add_argument("--ledger", default=None, help="Optional ledger path override.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    # Resolve paths BEFORE the bootstrap chdirs into services/python.
    terminal = Path(args.terminal).resolve()
    ledger = Path(args.ledger).resolve() if args.ledger else None

    backfill_mod = _load_backfill_module()
    backfill_mod._bootstrap_import_path()

    from src.mt5 import connector

    if not terminal.exists():
        print(f"ABORTED: terminal not found: {terminal}")
        return 2
    if not connector.use_live_data_mode(path=str(terminal)):
        print(f"ABORTED: could not attach MT5 terminal: {terminal}")
        return 2
    if not connector.is_live_mode():
        print("ABORTED: connector reports not-live after a successful attach.")
        return 2

    ok, positions = connector.get_positions_ex()
    if not ok:
        print("ABORTED: broker position read NOT verified (get_positions_ex ok=False).")
        return 2
    print(f"Live attach OK — broker positions: {len(positions)} ticket(s)")

    runner = backfill_mod.StaleBackfill(
        ledger_path=ledger or backfill_mod.DEFAULT_LEDGER,
        apply=args.apply,
        ticket=args.ticket,
        connector_module=connector,
    )
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
