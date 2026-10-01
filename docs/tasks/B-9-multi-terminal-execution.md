# B-9 — Multi-Terminal Execution with Per-Account Active/Inactive Flag

## Goal
Enable parallel execution across multiple MT5 accounts with individual active/inactive control. Inactive accounts do not participate in signal execution; active accounts receive orders independently.

## Current Architecture (Single-Terminal)
- **State**: global `_selected_id` (str) + `_execution_armed` (bool) in `src/mt5/terminals.py`
- **Selection**: one terminal selected via `POST /mt5/terminals/select`
- **Arm switch**: single `POST /mt5/terminals/arm` → arms/disarms the selected terminal
- **Execution**: `ExecutionEngine._native_execution_armed()` checks if selected terminal is armed
- **Config**: `mt5_terminals.json` already supports 9 entries with `"execution": true|false` per terminal

## Target Architecture (Multi-Terminal)
- **State**: dict `{terminal_id: {"armed": bool, "selected": bool}}` — multiple terminals can be armed simultaneously
- **Selection**: unchanged (UI/dashboard focus)
- **Arm switch**: `POST /mt5/terminals/{terminal_id}/arm` with `{"armed": true|false}` → per-terminal control
- **Execution**: loop all armed terminals; send order to each independently
- **Risk gate**: shared global (single kill switch, single exposure limit across all terminals); per-terminal isolation deferred to future enhancement
- **Position monitor**: loop all armed terminals for reconciliation

## Acceptance Criteria
1. **Config unchanged**: `mt5_terminals.json` structure preserved; `"execution": true` remains prerequisite for arming
2. **State refactor**: replace global `_selected_id` + `_execution_armed` with `_terminal_states: dict[str, dict]`
3. **API endpoint**: new `POST /mt5/terminals/{terminal_id}/arm` accepts `{"armed": bool}`; returns updated state for that terminal
4. **Backward compat**: existing `POST /mt5/terminals/arm` (no id in path) arms/disarms the selected terminal (graceful migration)
5. **Execution loop**: `ExecutionEngine._native_execution_armed()` → `_get_armed_terminals()` returns `list[str]` of armed terminal ids; order execution loops this list
6. **Dashboard UI**: table shows all terminals; per-row arm toggle (replace single global switch)
7. **Tests**: 
   - Arm terminal A → execute → order sent to A only
   - Arm terminal A + B → execute → orders sent to both
   - Disarm A → B still armed → order sent to B only
   - Config `execution: false` → arm rejected
8. **Lint clean**: black/isort/flake8 pass
9. **No new dependencies**

## Files to Modify
- `services/python/src/mt5/terminals.py` — state refactor, `arm_terminal(terminal_id, armed)`, `get_armed_terminals()`
- `services/python/src/mt5/endpoints.py` — new route `POST /mt5/terminals/{terminal_id}/arm`
- `services/python/src/execution/engine.py` — replace `_native_execution_armed()` with `_get_armed_terminals()`, loop order sends
- `services/python/tests/mt5/test_terminals.py` — multi-arm tests
- `services/python/tests/execution/test_engine.py` — multi-terminal execution tests
- `apps/web/src/components/TerminalControl.tsx` — multi-row table, per-terminal arm toggle
- `apps/api/src/pythonClient.ts` — add `armTerminal(terminalId, armed)` method

## Constraints
- **SAFETY**: LIVE account (`vito2`) read-only — no order execution to LIVE
- **Demo target**: `bil2` (HFMarketsGlobal-Demo) only
- **Fail-closed**: terminal not in config or `execution: false` → arm rejected
- **Graceful degradation**: if loop fails on terminal A, log error but continue to terminal B
- **No breaking changes**: existing single-terminal workflows must still work (selected terminal arm via legacy endpoint)

## Out of Scope (Future Enhancement)
- Per-terminal risk gate (separate exposure limit, kill switch per account)
- Per-terminal position reconciliation isolation
- Dynamic terminal discovery without config edit
- Cross-account netting or correlation analysis

## Implementation Plan
1. Refactor `terminals.py` state: `_terminal_states` dict, `arm_terminal(id, armed)`, `get_armed_terminals()`
2. Add endpoint `POST /mt5/terminals/{terminal_id}/arm`
3. Update `engine.py`: `_get_armed_terminals()` → loop order execution
4. Write tests (arm single, arm multiple, execution routing)
5. Update UI: multi-row table, per-terminal toggle
6. Update Node client: `armTerminal(terminalId, armed)`
7. Lint + full suite
8. Manual smoke test: arm `bil2` → verify order sent; arm 2nd terminal (if available) → verify parallel

## Risk Mitigation
- All order execution confined to `execution: true` terminals in config
- Demo-only execution enforced by config (`bil2`)
- LIVE terminal (`vito2`) has `execution: false` → cannot be armed
- Tests verify multi-arm isolation (A armed ≠ B armed)

---
**Created:** 2026-09-24  
**Assignee:** OpenCode (via `opencode-task-runner`)  
**Estimated effort:** 3-4 hours  
**Priority:** P1 (user-requested feature)

---

## B-9 Lanjutan — Multi-Arm Hardening (implemented)

The per-terminal ARM/API/UI already existed, but multi-arm (manual, per-account
arm) could not run END-TO-END because of four gaps. All four are now closed.

### 1. Select no longer disarms (`mt5.terminals.select_terminal`)
`select_terminal` used to loop `for st in _terminal_states.values(): st["armed"] = False`
before re-attaching the binding. That loop is REMOVED. Selecting a terminal now
only (a) validates the entry (not found / not running → reject), (b) re-attaches
the process-wide binding (shutdown + `use_live_data_mode(path)`), (c) marks it
selected and unmarks the rest, (d) saves the selection, (e) clears the symbol
cache. **Arm state is never touched** — success OR failed re-attach. The success
message is now `Terminal '<id>' selected. Attached to: <path>. Arm state unchanged.`
and a failed attach still reports a detached binding without changing any arm
state.

### 2. Arm no longer requires an attached binding (`mt5.terminals.arm_terminal`)
The `if not entry["attached"]: reject` guard is REMOVED. Arm now requires only:
registered + running + `"execution": true`. Rationale: the process-wide MT5
binding is a DATA pointer only; each account is re-attached right before its
order (canonical fan-out), and the single-terminal path validates
"binding attached to an armed terminal" separately (`execution_permitted()` and
the pipeline guard below). Disarm is still always allowed.

### 3. Canonical fan-out re-attaches PER ACCOUNT (`execution.fanout.CanonicalFanout`)
`fan_out` remembers the originally attached path, and for EVERY target with a
truthy `path` it now does `connector.shutdown()` + `connector.use_live_data_mode(path=...)`
+ `clear_symbol_cache()` BEFORE dispatching that account's order. A failed
re-attach fails ONLY that account (`FAILED`, "gagal attach ke terminal '<id>'");
the others still proceed. A `finally` block restores the original binding
(best-effort, never raises). A path-less target (test double) skips re-attach
for backward compat.

### 4. Single-terminal path fails closed when >1 terminal is armed (`orchestration.pipeline`)
`_dispatch_execution` counts armed+eligible terminals (dual-import helper,
fail-closed to 0). When fan-out is OFF and the count is > 1 it does NOT send an
order; it returns a failure adapter with:
`MULTIPLE TERMINALS ARMED — single-terminal execution disabled. Enable canonical fan-out (canonical_fanout_enabled) or disarm all but one.`
Count ≤ 1 keeps the historic behaviour. The fan-out branch is unaffected.

### Gate verification (already enforced, now covered by tests)
`mt5.terminals.execution_permitted()` already required "≥1 armed & eligible
terminal AND the binding currently attached to one of them" (fail-closed). The
engine's `_native_execution_armed()` consults it. New tests confirm: 2 armed +
binding attached to one of them → `True`; binding attached to a NON-armed
terminal → `False`; an armed terminal that stops running → `False`.

### How to use
- **Single account (e.g. `bil2` DEMO)**: arm `bil2` → the fan-out target set is
  the single `bil2`, so a canonical fan-out sends exactly one order.
- **Three accounts**: arm all three (select no longer disarms the others), then
  enable `canonical_fanout_enabled` (Settings knob, default NONAKTIF) so ONE
  canonical signal fans out to every armed terminal with per-account re-attach.

### LIMITATIONS (next phase)
- `modify_position_sltp` changes SL/TP through the CURRENTLY attached binding; if
  a ticket belongs to a different terminal the broker rejects it (order_send to
  the wrong terminal). Per-terminal SL/TP routing is a future phase.
- Per-account monitoring / reconciliation that is terminal-aware (loop every
  armed terminal) is a future phase.
- `canonical_fanout_enabled` is wired when the pipeline is constructed; a change
  takes effect on the next process start (the coordinator is built once).
- Fan-out remains OFF by default; execution stays DISARMED by default.
