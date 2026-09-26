# LEDGER-SLTP T3 — Live SL/TP attach validation (demo order + close + ledger closure)

You are T3 of a 4-task chain. Prerequisites: T1+T2 complete — read their reports. Ledger is
clean, reconciliation `has_critical=False`, guard unblocked, account FLAT. Do ONLY T3 scope.
You run non-interactively: decide, document, continue.

## Environment
- Repo: C:/xampp/htdocs/project-ea-bot. **Never commit.** Never reformat.
- Python: services/python/.venv/Scripts/python.exe — `src.*` imports only with cwd=services/python.
- Tests (from services/python): `./.venv/Scripts/python.exe -m pytest -q`.
- Lint: `./.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 <files>`
  + `black --check` (check only).
- DEMO broker only. Terminal bil2: "E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe".
  Filling FOK (IOC is rejected retcode 10030). Symbol #BTCUSD (24/7), volume 0.01,
  magic 84004, comment e.g. LCSLTP.

## Goal
Validate live SL/TP attach through the SAME engine path as B-4 T1
(`ExecutionEngine._send_to_mt5`, native `mt5.order_send` payload) and prove the closure
lifecycle end-to-end (monitor marks the ledger `closed` when the position disappears).

## Harness changes (additive only — default behavior unchanged)
Extend `scripts/b4_demo_validation.py`:
- SL/TP distance options (percent or points) computed from symbol info
  (`trade_stops_level`, `point`, `digits`); default ≈1.5% of price for #BTCUSD; ALWAYS
  greater than the symbol's stops level; rounded to symbol digits.
- Fill `OrderRequest.sl/.tp`; after fill, read back `positions_get(ticket)` and compare
  `sl`/`tp` ≈ requested (document the tolerance you use).
- Optional hold-seconds / close-after. Reuse the existing select/arm/order-check machinery.
All 49 tests in `services/python/tests/test_b4_demo_validation.py` must stay green.
New unit tests (new file `services/python/tests/test_sltp_attach.py`): request construction
includes sl/tp; distance computation respects stops level; readback comparison logic (pure,
no live). If extension cannot be done cleanly without touching existing defaults/tests,
create `scripts/sltp_live_validation.py` importing the harness instead — document the choice.

## Live run (one order, demo)
1) Service up with T1/T2 code. If restart lost the armed terminal: re-select + re-arm —
   follow the exact operational pattern in `docs/tasks/B4-T1-*-report.md` (B-4 T1 did this).
2) `order_check` first (FOK); only then send. At most ONE filled order — retry only on a
   clean rejection with no fill (document any retry).
3) Read back the broker position: record `sl`/`tp` (must be non-zero and ≈ requested).
4) Hold the position open ≥2 monitor intervals (read the interval from `runtime.py`) so the
   monitor observes it; confirm via service logs that the monitor saw the position.
5) Close via helper: reuse `_b4_close.py` if it accepts a ticket argument; otherwise
   generalize into `scripts/mt5_close_ticket.py --ticket N`. Record retcode/deal/price/P&L.
6) After close: wait ≥2 monitor intervals; verify the ledger gains `closed` for the ticket
   (monitor path) and `POST /reconciliation/run` stays `has_critical=False` (no new stale
   record). If the monitor did not observe it (timing), document exactly why — DO NOT fake,
   hand-edit the ledger, or bypass. Mark the step not-observed and state the residual.

## Evidence + report
- `docs/evidence/LEDGER-SLTP-live.json` (+ .md): requested sl/tp + how computed; order
  retcode/ticket/deal/price; broker readback sl/tp; close result; ledger `closed` line
  verbatim; reconciliation before/after. No secrets.
- `docs/tasks/LEDGER-SLTP-T3-report.md`: commands, raw outputs, deviations, honest status.
- Constraints same as T1 (no commit, no reformat, preserve user changes, no secrets).
