# B-4 T1 — Controlled DEMO Validation Harness (Report)

Status: DONE (kode + unit test + dry-run + live run). No commit.
Parent plan: `docs/plans/B4-LIVE-DEMO-VALIDATION.md` (T1)
Blocker ref: `docs/audit/RELEASE_BLOCKERS.md` → B-4 (lines 64–79)

## What was built

1. **`scripts/b4_demo_validation.py`** — standalone CLI harness.
   - Subcommands: `validate` (default), `reconcile` (→ `NotImplementedError("T2")`),
     `recovery-check` (→ `NotImplementedError("T3")`). T2/T3 extend the skeleton.
   - Flags: `--symbol` (`#BTCUSD`), `--volume` (default = `symbol_info.volume_min`),
     `--dry-run`, `--timeout`, `--terminal-id`, `--terminal-path`.
   - Flow: pre-flight → **DEMO guard (fail-closed)** → market check →
     open-position guard (idempotent) → arm → submit 1 order via
     `ExecutionEngine.execute_order` → fill verify → evidence JSON + MD.
   - Import bootstrap: resolves repo root from `__file__`, `os.chdir(services/python)`,
     prepends `services/python` to `sys.path[0]` **before** importing `src.*` — the
     harness behaves identically from any cwd (verified by running it from the repo root).
   - **Gates are all preserved, never bypassed**: the order travels the same
     `arm_terminal` + `execution_permitted()` (armed/eligible/attached terminal) and
     `require_approval=True` + gate-issued `approval_token` path as production. Engine
     wiring matches `orchestration/runtime.py`: `simulation_mode=True, require_approval=True`
     (the native path is still taken because `require_approval=True` disables the
     simulated short-circuit — `engine.py:831`).
   - Durable ledger wiring: `set_store(OrderStateStore())` like `main.py`, so the ticket
     lands in `services/python/logs/order_state.jsonl` for T2 to reconcile by ticket.
2. **`services/python/tests/test_b4_demo_validation.py`** — 29 mock-based unit tests
   (fake `MetaTrader5` + fake `mt5.terminals`; no live connection required).
3. **`docs/evidence/B-4-demo-validation.json` / `.md`** — machine-readable + human evidence
   (append-friendly for T2/T3).

## Acceptance checklist

- [x] `services/python/.venv/Scripts/python.exe -m pytest tests/test_b4_demo_validation.py -q`
      → **29 passed**.
- [x] `flake8 --max-line-length=100 --extend-ignore=E203,W503` on both files → **0**.
- [x] `black --check` clean on both files (also `isort --check-only` clean).
- [x] `--dry-run` live against bil2 → **order_check retcode 0** recorded.
- [x] Live `validate` → **1 fill** (ticket `1353670649`), evidence JSON + MD written,
      position **left OPEN**, ticket recorded.
- [x] Full suite: **2222 passed** (baseline 2193 + 29 new = 2222, exactly; **no regressions**).
- [x] `docs/tasks/B4-T1-report.md` written.

## Dry-run output (live, bil2)

```
Initializing MT5 with terminal: E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe
[OK  ] preflight: connected login=49662626 server=HFMarketsGlobal-Demo
[OK  ] demo_guard: account is DEMO (trade_mode=0)
[OK  ] market_check: tick bid=83872.594 ask=83912.594
[OK  ] open_position_guard: no existing B4 position — proceed
[OK  ] order_check: retcode=0 comment='Done'
Dry-run complete — no order submitted.
```

## Live run output (validate, bil2)

```
Initializing MT5 with terminal: E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe
[OK  ] preflight: connected login=49662626 server=HFMarketsGlobal-Demo
[OK  ] demo_guard: account is DEMO (trade_mode=0)
[OK  ] market_check: tick bid=83872.594 ask=83913.594
[OK  ] open_position_guard: no existing B4 position — proceed
[OK  ] arm: terminal 'bil2' armed and execution permitted
[OK  ] order_check: retcode=0 comment='Done'
[OK  ] submit: dispatching through ExecutionEngine.execute_order
[OK  ] execution: ticket=1353670649
[OK  ] fill_verify: position ticket=1353670649 confirmed OPEN
Validation complete — 1 fill captured. Position left OPEN for T2/T3. NOT closed.
```

Result:
- Symbol `#BTCUSD`, BUY, volume `0.01` (`volume_min`), magic `84004`, comment `B4DEMO`.
- Account login `49662626` (`HFMarketsGlobal-Demo`, trade_mode 0, DEMO).
- Fill: ticket **`1353670649`**, order_check retcode **0**, execute_order retcode **0**.
- Position left **OPEN** at price `83913.594` (T2/T3 need it open).
- Durable ledger `services/python/logs/order_state.jsonl`:
  `{"intent_id": "b4-t1-1353670649", "state": "position_confirmed", "ticket": 1353670649}`.

## Plan deviations (intentional, documented)

1. **Plan named the test file `test_b4_harness.py`; the task brief named
   `test_b4_demo_validation.py`.** Used the task brief's name (authoritative for T1).
2. **Durable ledger wiring added to T1.** The plan placed durable-store wiring implicitly;
   the task brief explicitly lists `set_store(OrderStateStore())` as context. Wiring it in
   T1 means T2 can reconcile by ticket without extra plumbing. On the idempotent re-run path
   the harness records the observed open position as `position_confirmed` keyed on the
   ticket (`b4-t1-<ticket>`) — an honest observation of the broker's real state, not a
   fabricated fill. `order_state.jsonl` field shape (`{intent_id, state, ticket, timestamp}`)
   remains unchanged, as required.
3. **JSON evidence merge.** A re-run (position already open) carries no new
   `order_check`/`execution_result`; the harness preserves those from the prior JSON so the
   original fill evidence is never clobbered.
4. **No `type_filling` forced in the payload.** Broker needs FOK; the engine default already
   works (IOC was rejected with retcode 10030 in recon). No filling logic changed.
5. **Pre-submit `order_check`.** For live `validate`, an `order_check` runs immediately before
   submit as defence-in-depth (the dry-run path proves it standalone). It does not alter the
   engine's own path; the engine still performs its own native `order_send`.

## Safety notes

- DEMO guard is fail-closed and runs before any arm/submit; a non-DEMO `trade_mode` aborts
  with exit code 2 and submits nothing (unit-tested for trade_mode 1/2/99).
- Max ONE order per run; the open-position guard makes re-runs idempotent (no loops that
  could resubmit).
- No production gate or `src/` execution logic was modified. Untouched: `src/config.py`,
  `src/main.py`, `src/orchestration/pipeline.py`, `apps/api/src/index.ts`.
- No commits made.

## Verification commands

```
services/python/.venv/Scripts/python.exe -m pytest tests/test_b4_demo_validation.py -q
services/python/.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 \
    scripts/b4_demo_validation.py services/python/tests/test_b4_demo_validation.py
services/python/.venv/Scripts/python.exe -m black --check \
    scripts/b4_demo_validation.py services/python/tests/test_b4_demo_validation.py
```
