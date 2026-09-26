# B-4 T1 — Controlled DEMO Validation Harness

Status: TODO (delegasi OpenCode)
Parent plan: `docs/plans/B4-LIVE-DEMO-VALIDATION.md` (task T1)
Blocker ref: `docs/audit/RELEASE_BLOCKERS.md` → B-4 (lines 64–79)

## Goal

Build the controlled DEMO-account validation harness: a standalone script that
arms the DEMO terminal `bil2`, places exactly one small order through the
**native engine path** (`ExecutionEngine` → `_send_to_mt5`, NOT the paper
`/mt5/orders/execute`), verifies the fill on the broker, and records machine-
readable evidence. This is the "arm a demo terminal, place a small order,
verify fill" half of B-4.

## Deliverables

1. `scripts/b4_demo_validation.py` — CLI harness (subcommand skeleton so T2/T3
   can extend it later):
   - `validate` (default): pre-flight → DEMO guard → arm → submit 1 order →
     verify fill → evidence JSON/MD.
   - `--symbol` (default `#BTCUSD`), `--volume` (default = `symbol_info.volume_min`),
     `--dry-run` (order_check only, no submit), `--timeout` seconds.
   - `reconcile` / `recovery-check` subcommands: stubs raising
     `NotImplementedError("T2/T3")` — do not implement them here.
2. `services/python/tests/test_b4_demo_validation.py` — unit tests (mock MT5,
   no live connection required).
3. `docs/tasks/B4-T1-report.md` — short report: what was built, test counts,
   dry-run output, live-run output (if performed), deviations.

## Context you must read first

- `docs/plans/B4-LIVE-DEMO-VALIDATION.md` — the approved plan.
- `services/python/src/execution/engine.py` — `OrderRequest` (~lines 40–90),
  `ExecutionEngine.__init__` (~125–205), `validate_order` (~272–384),
  approval gate (~384–470), `execute_order` success path (~455–560),
  `_native_execution_armed`/`_get_armed` (~722–800), `_send_to_mt5` (~787–965),
  `_parse_send_result` (~960–1035).
- `services/python/src/mt5/endpoints.py` — arm endpoint (~91–147) and all
  `@router.` routes; `services/python/src/mt5/terminals.py` —
  `select_terminal` (~594–690), `arm_terminal` (~725–845).
- `services/python/src/orchestration/pipeline.py` (~455–510) — how the
  approval token is stamped for engine execution. The harness MUST pass
  through the same gates (arm + approval, fail-closed) — never bypass or
  disable a gate.
- `services/python/src/execution/state_machine.py` + `src/persistence/order_state_store.py`
  — durable order ledger wiring (`set_store(OrderStateStore())`).
- `_b4_probe2.py` (repo root) — working example of read-only pre-flight
  (DEMO guard + `#BTCUSD` tick + engine-shaped `order_check`); reuse its
  patterns.

## Verified facts (from recon — trust these)

- `bil2` terminal path: `E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe`.
  DEMO login `49662626`, `trade_mode 0`. Terminal is currently NOT running —
  `mt5.initialize(path=...)` is expected to launch it; if launch/connect fails,
  abort with a clear message (no retry loops).
- Broker requires **FOK** filling (IOC rejected retcode `10030`; FOK retcode
  `0`). Engine defaults already match — do not change filling logic.
- `#BTCUSD` has fresh ticks 24/7 (weekend-safe); XAUUSD is closed on weekends.
- `select_terminal` refuses terminals whose `terminal64.exe` is not running.
- Import rule: `import src.*` only works when cwd is `services/python`.
  The harness must bootstrap this itself: resolve repo root from
  `__file__`, `os.chdir(services/python)`, and insert it at `sys.path[0]`
  BEFORE importing `src.*` — so the harness behaves identically no matter
  where it is invoked from.
- The live service process runs with cwd `services/python`, so the ACTIVE
  ledger file is `services/python/logs/order_state.jsonl` (root
  `logs/order_state.jsonl` is stale — ignore it). The harness must resolve
  the same file (it will, after the cwd bootstrap).
- `order_state.jsonl` records are only `{intent_id, state, ticket, timestamp}`
  — no symbol/volume. Do not add fields in T1; T2 handles matching by ticket.
- A second Python process may attach the same terminal via
  `mt5.initialize(path=...)`; no service is currently attached to bil2.

## Harness behavior (`validate`)

1. **Pre-flight**: initialize MT5 with the bil2 path; wait for connection
   (bounded timeout). If `account_info()` is None → abort.
2. **DEMO guard (fail-closed)**: `trade_mode != 0` → print reason and exit
   non-zero WITHOUT submitting anything. This guard is non-negotiable.
3. **Market check**: fetch tick for `--symbol`; if tick is stale/None → abort
   with message (do not submit).
4. **Open-position guard**: if broker already has a position with the
   harness magic/comment → skip submit, print "already validated" and exit 0
   (idempotent re-run). Exactly ONE order per validation.
5. **Arm**: arm `bil2` through the same mechanism as the service arm endpoint
   (`terminals.arm_terminal` semantics — read the endpoint + terminals code).
6. **Submit**: build an engine `OrderRequest` (symbol, BUY, volume =
   `volume_min`, magic/comment `B4DEMO`), obtain the approval token the same
   way the pipeline does, call `engine.execute_order`. `--dry-run` performs
   `order_check` only and stops before submit.
7. **Fill verify**: poll `get_positions()`/order result until the position
   ticket appears (bounded timeout). Capture raw retcode + result.
8. **Evidence**: write `docs/evidence/B-4-demo-validation.json` (create dir)
   with a `t1` section: timestamp, terminal path, account login + trade_mode,
   symbol, tick snapshot, request summary, retcode, ticket, position snapshot
   (symbol/volume/price), python version. Also create/append
   `docs/evidence/B-4-demo-validation.md` with a T1 section (keep it
   append-friendly for T2/T3).
9. **Do NOT close the position** — T2/T3 need it open. Note this in output.

## Safety / constraints

- DEMO guard fail-closed; never run against `trade_mode != 0`.
- Max ONE order per run; no loops that could submit repeatedly.
- `--dry-run` must be the first live action; only run live `validate` after
  unit tests + dry-run pass.
- No commits. Preserve all existing user changes (do not touch
  `services/python/src/config.py`, `services/python/src/main.py`,
  `services/python/src/orchestration/pipeline.py`, `apps/api/src/index.ts`
  beyond what this task strictly needs — ideally zero changes there).
- If live run fails due to environment (terminal won't launch, market data
  missing), STOP and write the failure into the report — do not hack around
  gates or retry endlessly.

## Acceptance criteria

- [ ] `services/python/.venv/Scripts/python.exe -m pytest tests/test_b4_demo_validation.py -q` → all GREEN (mock-based, no MT5 needed).
- [ ] `flake8 --max-line-length=100 --extend-ignore=E203,W503 scripts/b4_demo_validation.py services/python/tests/test_b4_demo_validation.py` → 0.
- [ ] `black --check` clean on both files.
- [ ] `--dry-run` executed live (bil2) → order_check retcode 0 captured in report.
- [ ] Live `validate` run: 1 fill captured → evidence JSON + MD written,
      position left OPEN, ticket recorded in report.
- [ ] `docs/tasks/B4-T1-report.md` written.

## Out of scope

- T2 reconciliation run, T3 restart recovery (later tasks; leave stubs).
- Hardening `/mt5/orders/execute` (T5).
- Any change to production gates or execution logic in `src/`.
