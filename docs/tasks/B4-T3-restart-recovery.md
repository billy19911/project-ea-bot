# B-4 T3 — Restart Recovery Validation

Status: TODO (delegasi OpenCode, setelah T2 selesai)
Parent plan: `docs/plans/B4-LIVE-DEMO-VALIDATION.md` (task T3)
Blocker ref: `docs/audit/RELEASE_BLOCKERS.md` → B-4 (lines 64–79)
Depends on: T1 + T2 (open position + matched reconciliation evidence)

## Goal

Extend the harness with the `recovery-check` subcommand: prove that after the
service/harness process restarts, (a) the durable order ledger persists the T1
order, (b) `OrderStateStore` rehydrates it from `services/python/logs/order_state.jsonl`
into memory at init, (c) a fresh reconciliation run still matches the T1 ticket
against the broker, and (d) the in-memory arm state is cleared by design
(re-arm required) — then re-arm and document the full cycle.

## Verified facts (from recon — trust these)

- `OrderStateStore.__init__` rehydrates the file → memory (`_DEFAULT_PATH =
  logs/order_state.jsonl` relative to cwd, or `ORDER_STATE_PATH` env override).
  The service runs with cwd `services/python` → active file is
  `services/python/logs/order_state.jsonl`.
- Arm state is IN-MEMORY by design: a restart clears it. Selection is persisted
  (`mt5_selected.json`). Re-arm after restart is REQUIRED and expected — this is
  not a bug; the evidence must show the disarm → re-arm cycle explicitly.
- `select_terminal` refuses terminals whose `terminal64.exe` is not running;
  arming requires selected + running + execution-enabled + attached.
- `ReconciliationRunner` + providers wiring: same as T2.

## Deliverables

1. Extend `scripts/b4_demo_validation.py` — implement `recovery-check`:
   - Phase A (pre-restart): record arm state + read T1 ticket from evidence
     JSON + confirm the ticket's record exists in the ledger file.
   - Phase B (simulate process restart): construct a FRESH `OrderStateStore()`
     instance + fresh state machine wiring in a subprocess-free way (the
     harness itself re-initializes the store — e.g. run each phase as separate
     harness invocations so memory genuinely resets between them; simplest:
     `recovery-check` runs in two explicit stages `--stage pre` / `--stage post`,
     and the operator (or report instructions) run them as separate processes).
   - Phase C (post-restart): assert the store rehydrated the T1 ticket state
     from disk; run reconciliation again; assert T1 ticket still matched;
     assert arm state is EMPTY (proves in-memory clearing); re-arm bil2 via the
     same mechanism as T1; confirm armed.
   - Append the `t3` section to evidence JSON + MD.
2. Extend unit tests: rehydration round-trip (write temp ledger → new store
   instance → state present), arm-state-cleared assertion.
3. Update `docs/tasks/B4-T3-report.md` — both stage outputs, evidence that
   state survived via FILE (not memory), re-arm confirmation.

## Acceptance criteria

- [ ] Unit tests GREEN (mock/tmpfile-based).
- [ ] `--stage pre` and `--stage post` run as SEPARATE processes against bil2:
      pre → ticket in ledger + armed; post → ticket rehydrated + matched +
      arm empty → re-armed.
- [ ] Evidence JSON `t3` section with both stage outputs.
- [ ] flake8 (100) + black clean.

## Out of scope

- Restarting the live service itself (the harness simulates its own restart;
  the service restart procedure is operational, not part of this validation).
- Closing the T1 position (leave open; operator closes manually later).
- Changing any gate, arm, or persistence code.
