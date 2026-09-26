# B-4 — DEMO validation evidence (consolidated)

Final consolidated record for blocker **B-4 — No live broker validation has ever
been performed** (`docs/audit/RELEASE_BLOCKERS.md`).

Machine-readable detail: `docs/evidence/B-4-demo-validation.json`.

Validation was performed **end-to-end** against a DEMO account: arm → order →
fill → confirmation → reconciliation → restart recovery — all recorded below.
Per-task reports: `docs/tasks/B4-T1-report.md`, `docs/tasks/B4-T2-report.md`,
`docs/tasks/B4-T3-report.md`.

## Summary

| Task | What was validated | Result | Key evidence |
| --- | --- | --- | --- |
| **T1** | Controlled DEMO order placed (arm → check → send → fill → confirmation) | ✅ order placed — ticket `1353670649`, `#BTCUSD` BUY vol `0.01`, magic `84004`, comment `B4DEMO`, order_check retcode `0`; position left OPEN | `json` → `t1` |
| **T2** | Live reconciliation vs broker (internal durable ledger vs live positions) | ✅ T1 ticket **matched by ticket** (`matched == [1353670649]`, `missing_internal == []`); ⚠️ `has_critical == True` due to **expected artifacts** (3 ledger field diffs + 14 stale `missing_in_broker`) — see Known gaps | `json` → `t2` |
| **T3** | Restart recovery across two separate OS processes (`--stage pre` / `--stage post`) | ✅ ledger persisted to FILE, state **rehydrated from FILE** by a fresh process, reconciliation matched again, arm state EMPTY (in-memory by design) → **re-armed bil2** | `json` → `t3` |

## Environment

| Item | Value |
| --- | --- |
| Account login | `49662626` |
| Server | `HFMarketsGlobal-Demo` |
| `trade_mode` | `0` (DEMO — enforced by harness guard) |
| Currency / leverage | `IDR` / `1000` |
| Terminal path | `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe` (`bil2`) |
| Symbol | `#BTCUSD` |
| Volume | `0.01` (symbol minimum, step `0.01`) |
| Python | `3.11.16` |
| Raw evidence | `docs/evidence/B-4-demo-validation.json` |
| T1 timestamp (UTC) | `2026-09-26T13:41:40.749124+00:00` |
| T2 timestamp (UTC) | `2026-09-26T13:50:35.872256+00:00` |
| T3 timestamp (UTC) | pre `2026-09-26T14:00:06.569595+00:00` / post `2026-09-26T14:00:07.558223+00:00` |

## T1 — Controlled DEMO validation harness

- Timestamp (UTC): `2026-09-26T13:41:40.749124+00:00` (initial fill `2026-09-26T13:39:20`; the
  recorded `t1` section is the idempotent re-run that preserved the fill)
- Terminal: `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe` (`bil2`)
- Dry-run: `True` (re-run; initial fill was `False`)
- Symbol: `#BTCUSD`, volume `0.01`, magic `84004`, comment `B4DEMO`
- Account: login `49662626` server `HFMarketsGlobal-Demo` trade_mode `0`
- order_check retcode: `0` (Done)
- execute_order: success `True` ticket `1353670649` retcode `0`
- Position: ticket `1353670649` #BTCUSD vol `0.01` price `83913.594` (left OPEN for T2/T3)
- Ledger: `logs/order_state.jsonl` → `b4-t1-1353670649` state `position_confirmed`
- Python: `3.11.16`

### T1 — live fill

- Timestamp (UTC): `2026-09-26T13:39:20.242578+00:00`
- Terminal: `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe` (`bil2`)
- Dry-run: `False`
- Symbol: `#BTCUSD`
- Account: login `49662626` server `HFMarketsGlobal-Demo` trade_mode `0`
- order_check retcode: `0` (Done)
- execute_order: success `True` ticket `1353670649` retcode `0`
- Position: ticket `1353670649` #BTCUSD vol `0.01` price `83913.594` (left OPEN for T2/T3)
- Ledger: `logs/order_state.jsonl` → `b4-t1-1353670649` state `position_confirmed`
- Python: `3.11.16`

### T1 — idempotent re-run (fill preserved, no second order)

- Timestamp (UTC): `2026-09-26T13:41:40.749124+00:00`
- Terminal: `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe` (`bil2`)
- Dry-run: `True`
- Symbol: `#BTCUSD`
- Account: login `49662626` server `HFMarketsGlobal-Demo` trade_mode `0`
- Result: `already_validated` — no second order submitted; existing ticket `1353670649` left OPEN
- Note: invoked from the repo root to confirm the harness cwd-bootstrap works anywhere; the
  open-position guard correctly skipped the submit.
- order_check retcode: `0` (Done) — preserved from the original fill run
- Python: `3.11.16`

## T2 — Live reconciliation

- Timestamp (UTC): `2026-09-26T13:50:35.872256+00:00`
- Terminal: `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe` (`bil2`)
- Broker live mode: `True`
- T1 ticket: `1353670649`
- T1 ticket matched: `True`
- Matched tickets: `[1353670649]`
- Missing in broker: `[1348784058, 1348874223, 1348874358, 1348963010, 1348984819, 1349697094, 1349909054, 1350068378, 1350246238, 1352094141, 1352313902, 1352414292, 1352414491, 1352688152]`
- Missing internal: `[]`
- has_critical: `True` (total mismatches `17`)
- Field differences (matched pairs):
  - ticket `1353670649` field `volume` internal `None` broker `0.01` → **expected_ledger_shape_gap**
  - ticket `1353670649` field `symbol` internal `` broker `#BTCUSD` → **expected_ledger_shape_gap**
  - ticket `1353670649` field `magic` internal `0` broker `84004` → **expected_ledger_shape_gap**
- Result: `matched`

## T3 — Restart recovery (`pre` stage)

- Timestamp (UTC): `2026-09-26T14:00:06.569595+00:00`
- Terminal: `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe` (`bil2`)
- Ledger file: `logs\order_state.jsonl`
- T1 ticket: `1353670649`
- Ledger-file record: `b4-t1-1353670649` state `position_confirmed` ticket `1353670649` — **persisted on disk (not memory)**
- Arm state (pre-restart): armed `True` armed_terminals `['bil2']` permitted `True`
- Saved selection (survives restart): `bil2`
- Result: `pre_ok`

## T3 — Restart recovery (`post` stage)

- Timestamp (UTC): `2026-09-26T14:00:07.558223+00:00`
- Terminal: `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe` (`bil2`)
- Ledger file: `logs\order_state.jsonl`
- T1 ticket: `1353670649`
- Rehydrated state (fresh store): `position_confirmed` from `logs\order_state.jsonl` — **rebuilt from FILE at init**
- Arm state AFTER restart (memory cleared by design): armed `False` armed_terminals `[]` → `arm_cleared=True`
- Reconciliation re-run: matched `True` matched tickets `[1353670649]` critical `True`
- Re-armed 'bil2': armed `True` permitted `True`
- Result: `recovered`

## Closure — validation position closed (operational cleanup)

The T1 position was left OPEN deliberately for T2/T3. It was closed afterwards so the
demo account is left flat (direct broker call via one-shot helper `_b4_close.py` — an
operational cleanup, **not** an engine-path validation; the app's close path remains
unexercised):

- Ticket `1353670649` (`#BTCUSD` BUY `0.01`, magic `84004`) — closed 2026-09-26,
  server time `17:21:23` (broker server = UTC+3 → `14:21:23` UTC).
- Close: retcode `10009` (Done), deal `1207703177`, price `83907.844`
  (open `83913.594`), filling `FOK`.
- Realized P/L: `-1078.47` IDR (demo; swap `0`, commission `0`).
- Account after close: balance `493585650.79` IDR, equity `493585650.79` IDR,
  positions `0` (flat).

## Known gaps (documented, not hidden)

Findings 1–2 below are **expected artifacts of the current design**, not bugs, and
were classified as such in `docs/tasks/B4-T2-report.md`; finding 3 is a
validation-coverage gap (plan deviation). All are recorded here because they affect
live readiness and require follow-up before live deployment.

1. **Ledger record data-shape gap.** The append-only ledger's `position_confirmed`
   records carry only `{intent_id, state, ticket, timestamp}` — no `volume`, `symbol`,
   or `magic`. During reconciliation the internal side therefore reads `None`/`""`/`0`
   where the broker reports `0.01`/`#BTCUSD`/`84004`, producing 3 field diffs on the
   matched pair. `Reconciler` reports them honestly (they are surfaced, not hidden).
2. **Stale `position_confirmed` records without closure state → `has_critical=True`.**
   The append-only ledger never writes a "closed" state, so 14 records from Sep 24–25
   (tickets `1348784058 … 1352688152`) remain as `missing_in_broker` although their
   broker positions are already closed. This makes `has_critical() == True`.
3. **Validation order carried no SL/TP (plan deviation).** Plan B-4 line 51 stated
   "SL/TP diset", but the T1 harness built the `OrderRequest` with only
   `symbol/order_type/volume/price/magic/comment` — `sl`/`tp` fell back to the
   `0.0` defaults (`scripts/b4_demo_validation.py` ~line 393; `order_check` payload
   also `"sl": 0.0, "tp": 0.0`). The broker position therefore had `sl=0.0 tp=0.0`,
   and the SL/TP *attach* path (engine payload wiring + `validate_order` SL/TP sanity
   checks) was **not exercised live**. The T1 report's "Plan deviations" section did
   not record this deviation. **Impact:** B-4 validates the entry leg only
   (arm → order → fill → confirmation → reconciliation → restart recovery); live
   SL/TP attach, position modify, and close remain unvalidated. **Follow-up
   required before live deployment.**

**Implication (follow-up required before live deployment):** the `ReconciliationGuard`
**fail-closes NEW orders** while those stale records remain (`last_ok=False`). This is
correct fail-closed behaviour, but it blocks new entries until the ledger gains a
closure lifecycle (mark-closed / pruning / lifecycle provider). Cleaning the ledger is
**out of B-4 scope** (no reconciler/gate/provider tolerances were changed to force a
pass). Recommended follow-up: ledger closure lifecycle (or pruning) so closed positions
stop counting as internal `position_confirmed` records. For finding 3, a second
controlled demo order **with SL/TP set** (or a dedicated follow-up task) would close
the SL/TP validation gap.
