# Task: Multi-Terminal Execution with Per-Account Active/Inactive Flag (B-9)

## Objective
Enable parallel order execution across multiple MT5 accounts. Each terminal has independent arm/disarm control. Inactive terminals do not participate in signal execution.

## Current State (Single-Terminal)
- Global state: `_selected_id` (str) + `_execution_armed` (bool) in `services/python/src/mt5/terminals.py`
- One terminal selected, one arm switch
- Execution engine checks if selected terminal is armed
- Config `mt5_terminals.json` already has 9 terminal entries with `"execution": true|false`

## Target State (Multi-Terminal)
- State: `_terminal_states: dict[str, dict]` with per-terminal `{"armed": bool, "selected": bool}`
- Multiple terminals can be armed simultaneously
- New endpoint: `POST /mt5/terminals/{terminal_id}/arm` with body `{"armed": bool}`
- Execution engine loops all armed terminals, sends orders to each independently
- Risk gate shared globally (single kill switch, single exposure limit)

## Implementation Steps

### 1. State Refactor (`services/python/src/mt5/terminals.py`)
- Replace globals `_selected_id`, `_execution_armed` with `_terminal_states: dict[str, dict]`
- Add `arm_terminal(terminal_id: str, armed: bool) -> dict` — validate config `execution: true`, update state
- Add `get_armed_terminals() -> list[str]` — return list of terminal ids where `armed=True` AND config `execution=True` AND running
- Update `list_terminals()` — enrich each terminal entry with `"armed": bool` from state dict
- Preserve `select_terminal(terminal_id)` — update state dict, keep selection logic for UI focus
- Update `is_execution_armed()` → return `len(get_armed_terminals()) > 0` for backward compat

### 2. API Endpoint (`services/python/src/mt5/endpoints.py`)
- Add route: `@router.post("/mt5/terminals/{terminal_id}/arm")`
  - Body: `class ArmTerminalRequest(BaseModel): armed: bool`
  - Call `terminal_manager.arm_terminal(terminal_id, armed)`
  - Return `{"ok": bool, "terminal_id": str, "armed": bool, "message": str}`
- Keep legacy `POST /mt5/terminals/arm` (no id in path) — arms/disarms selected terminal for backward compat

### 3. Execution Engine (`services/python/src/execution/engine.py`)
- Replace `_native_execution_armed() -> bool` with `_get_armed_terminal_ids() -> list[str]`
  - Import `from mt5.terminals import get_armed_terminals`
  - Return `get_armed_terminals()`
- Update order execution flow (around line 837):
  ```python
  armed_ids = self._get_armed_terminal_ids()
  if not armed_ids:
      logger.warning("Execution blocked: no armed terminals")
      return None
  # Loop armed terminals
  results = []
  for term_id in armed_ids:
      # Send order to this terminal (binding already attached to selected terminal)
      # For now: execute on first armed terminal only (full multi-terminal execution = future enhancement)
      # Log which terminal receives order
      logger.info(f"Executing order on terminal {term_id}")
      # Existing order send logic here
      break  # Single-terminal execution for Phase 1; remove `break` for full parallel in Phase 2
  ```
- Log terminal id with each order execution

### 4. Tests (`services/python/tests/mt5/test_terminals.py`)
- Test arm single terminal → verify state
- Test arm multiple terminals → verify both armed
- Test disarm one → other remains armed
- Test arm with `execution: false` in config → rejected
- Test `get_armed_terminals()` returns correct list

### 5. Tests (`services/python/tests/execution/test_engine.py`)
- Mock `get_armed_terminals()` return `["bil2"]` → order executes
- Mock return `[]` → execution blocked
- Mock return `["bil2", "demo2"]` → verify routing (Phase 1: first only; Phase 2: both)

### 6. Dashboard UI (`apps/web/src/components/TerminalControl.tsx`)
- Change from single arm switch to per-terminal toggles
- Table structure:
  ```
  | Terminal | Account | Status | Armed | Actions |
  |----------|---------|--------|-------|---------|
  | bil2     | 12345   | Running| [x]   | Select  |
  | demo2    | 67890   | Stopped| [ ]   | Select  |
  ```
- Each row: arm toggle calls `POST /mt5/terminals/{id}/arm` with `{"armed": !current}`
- Disable toggle if `execution_allowed: false` or `running: false`

### 7. Node Client (`apps/api/src/pythonClient.ts`)
- Add method:
  ```typescript
  async armTerminal(terminalId: string, armed: boolean): Promise<any> {
    return this.post(`/mt5/terminals/${terminalId}/arm`, { armed });
  }
  ```
- Keep legacy `async armExecution(armed: boolean)` → calls old endpoint

## Acceptance Criteria
1. Arm terminal `bil2` via `POST /mt5/terminals/bil2/arm {"armed": true}` → success
2. Arm second terminal → both show `armed: true` in `GET /mt5/terminals`
3. Disarm `bil2` → second terminal still armed
4. Execute signal → order sent to armed terminal (logged with terminal id)
5. Config `execution: false` terminal → arm request rejected
6. Dashboard shows per-terminal arm toggle
7. All tests pass (2102+ tests green)
8. Lint clean (black/isort/flake8)

## Constraints
- **SAFETY**: LIVE account `vito2` has `execution: false` in config → cannot be armed
- **Demo only**: `bil2` (HFMarketsGlobal-Demo) is target
- **Fail-closed**: terminal not in config or not running → arm rejected
- **No breaking changes**: existing single-terminal workflows still work via legacy endpoint
- **No new dependencies**
- **Graceful degradation**: if execution fails on one terminal, log error but don't crash

## Out of Scope (Phase 2)
- True parallel execution (Phase 1: first armed terminal only)
- Per-terminal risk gate (shared global for now)
- Per-terminal position reconciliation
- Dynamic terminal discovery

## Files to Modify
- `services/python/src/mt5/terminals.py`
- `services/python/src/mt5/endpoints.py`
- `services/python/src/execution/engine.py`
- `services/python/tests/mt5/test_terminals.py`
- `services/python/tests/execution/test_engine.py`
- `apps/web/src/components/TerminalControl.tsx`
- `apps/api/src/pythonClient.ts`

## Safety Checklist
- [ ] `vito2` (LIVE) has `execution: false` in config
- [ ] Arm validation checks config `execution: true`
- [ ] Arm validation checks terminal is running
- [ ] Execution engine blocks if no armed terminals
- [ ] Tests verify isolation (arm A ≠ arm B)
- [ ] Lint passes
- [ ] Full suite passes (2102+ tests)

---
**Priority:** P1  
**Estimated effort:** 3-4 hours  
**Created:** 2026-09-24  
**Assignee:** OpenCode
