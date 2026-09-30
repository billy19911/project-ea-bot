# PHASE 4.5 DISCOVERY REPORT — Canonical Runtime Integration & Entry Cutover

## 1. Current Runtime Path (legacy-authoritative)

```
EVENT → pipeline.run()
  → A: supervisor.analyze() → proposal dict {symbol, direction, SL/TP/size?}
  → _build_validation_inputs → _complete_proposal (ATR SL/TP + sizing + _cap_lot)
  → RiskGate.validate_proposal → approved?
  → B6 (if zone_entry_enabled): _zone_entry_plan()
       → ZoneEntryGate.evaluate() → entry_zone.build_entry_plan()
       → plan found? price-at-zone ⇒ OVERWRITE proposal entry/SL/TP
       → plan None ⇒ BLOCKED "menunggu zona OB/FVG"
  → _build_order_request → approval_token → ExecutionEngine → MT5
```

Key finding: **zone presence ⇒ executable plan**. `build_entry_plan` returns a
plan when price is within the zone window — there is NO trigger evaluation
(rejection/displacement/micro-BOS/momentum/candle-close) between "price at
zone" and "overwrite SL/TP → execute". The `zone_entry` stage is OK-gated on
zone proximity alone.

## 2. Canonical Runtime Path (Phase 2–4, additive, NOT wired as default)

```
EVENT → CommitteeOrchestrator.run()
  → decide_dispatch (targeted roles only)
  → roles → evidence → MarketAssessment
  → SetupCandidate (directional evidence only)
  → DebateEngine (bounded, targeted)
  → EntryRole + trigger engine → EntryAssessment (ENTRY_READY/WAIT/INVALID)
  → DecisionState (action BUY/SELL only if consistent + ready)
```

Key finding: the canonical path produces STRUCTURE (assessment/setup/decision)
but the pipeline NEVER calls it. `orchestrator.py` is invoked only by unit
tests + smoke checks. The production `TradingPipeline` uses
`supervisor.analyze()` (synthesis path), not the orchestrator.

## 3. Legacy Path (inventory)

| Path | File | Authority today | Verdict |
|------|------|-----------------|---------|
| `_zone_entry_plan` → `entry_zone.build_entry_plan` | pipeline.py:1826 | Decides entry levels on zone proximity | LEGACY-AUTHORITATIVE — must become adapter |
| `_complete_proposal` (ATR SL/TP + sizing + `_cap_lot`) | pipeline.py:1188 | Fills missing SL/TP/size deterministically | KEEP (deterministic completion, not a bypass) |
| `ZoneEntryGate.evaluate` + `_pending` | entry_zone.py:391 | Remembers pending entries; returns plan when at zone | KEEP as pending-memory; plan issuance must require trigger |
| `EntryRole(trigger_confirmed)` caller flag | roles.py:514 | Legacy compat path can yield ENTRY_READY | DEMOTE to non-authoritative (trigger_result wins) |
| synthesis `target_sl/target_tp` | synthesis.py | Advisory only (overwritten by completion) | Already non-authoritative |
| `mt5/endpoints /orders/execute`, `write_guard.send_order` | mt5/ | PAPER-ONLY | Non-live, keep |
| `demo/demo_trading.py` | demo/ | DEMO harness | Non-live, keep |

## 4. All Entry Decision Points

1. `supervisor._synthesise` → proposal BUY/SELL/HOLD (synthesis evidence weights).
2. `pipeline._complete_proposal` → fills SL/TP/size (deterministic).
3. `pipeline` B6 `_zone_entry_plan` → OVERWRITES entry/SL/TP from zone plan ← **CUTOVER POINT**.
4. `RiskGate.validate_proposal` → approve/block.
5. `pipeline._build_order_request` → builds OrderRequest (no authority change).
6. `ExecutionEngine.execute_order` → sends (approval_token enforced).
7. `CommitteeOrchestrator` → DecisionState (canonical, currently unused by pipeline).
8. `EntryRole.analyze` → ENTRY_READY/WAIT (canonical interface, trigger_result-aware).

## 5. Adapters Required

- **A1 — Zone-plan adapter**: `_zone_entry_plan` must consult the canonical
  trigger engine AFTER finding a zone plan: zone found + trigger confirmed →
  return plan; zone found + trigger missing → return None (WAIT_TRIGGER).
  `ZoneEntryGate.evaluate` keeps pending-memory; `build_entry_plan` keeps
  computing zones(levels (it does NOT decide entry alone anymore).
- **A2 — EntryRole precedence**: `trigger_result` (deterministic) already wins
  over caller-asserted `trigger_confirmed` in `roles.py` — verify + lock with
  a regression test (already covered by test_phase4_entry_safety).
- **A3 — Proposal→orchestrator bridge**: pipeline keeps its supervisor path but
  feeds the SAME proposal context the orchestrator would use; no parallel
  pipeline (single orchestration path preserved).

## 6. Potential Duplicate Decision Paths

- Supervisor-synthesis proposal vs orchestrator DecisionState: BOTH produce a
  direction, but only the supervisor path reaches the gate. No live duplicate
  (orchestrator is dormant in production). Cutover must NOT activate both —
  the trigger evaluation is injected INTO the existing pipeline (A1), not as a
  second pipeline.
- `ZoneEntryGate._pending` vs `EntryLifecycleManager`: both remember pending
  entries. Keep ZoneEntryGate as the runtime pending store (wired + tested);
  EntryLifecycleManager remains the canonical idempotency primitive for the
  trigger engine path (claim_entry on (setup_id, trigger_id, candle_ts)).

## 7. Potential Bypasses Found

- **B1 (CONFIRMED, the cutover target)**: B6 zone plan overwrites SL/TP on zone
  proximity WITHOUT trigger confirmation. A zone touch becomes executable
  levels. Fix = A1 (trigger gate inside `_zone_entry_plan`).
- **B2 (legacy compat)**: `EntryRole(trigger_confirmed=True)` without a
  `trigger_result` yields ENTRY_READY. Only reachable via direct role calls
  (orchestrator always passes trigger context in production wiring after
  cutover); pipeline never calls EntryRole. Mitigation = regression test
  asserting trigger_result precedence (exists) + document compat status.
- No AI→MT5 direct path. No RiskGate bypass. No volume bypass (`_cap_lot`
  runs on every path including early returns).

## 8. Tests Impacted

- `test_entry_zone.py` (legacy plan/gate behavior) — must KEEP passing:
  `build_entry_plan` still returns plans (zone planning unchanged); only the
  PIPELINE's use of the plan gains a trigger precondition.
- Phase 4 tests (52) — trigger engine semantics unchanged; no detector changes.
- Pipeline tests using `zone_entry_gate` fakes — the fake gate must expose the
  trigger hook (update fakes, not production logic).
- New tests: canonical cutover (A–L per spec) + adversarial (Case 1–7).

## 9. Migration / Cutover Strategy

- Stage 1 (shadow): pipeline computes BOTH legacy zone plan AND canonical
  trigger evaluation; logs MATCH/CONFLICT per cycle; legacy remains the decider.
- Stage 2 (authoritative): trigger evaluation gates the plan (A1). Legacy
  `build_entry_plan`/`ZoneEntryGate` keep computing zones (read-only data
  source); authority moves to TriggerEngine + EntryAssessment.
- Stage 3 (retire): only if all regression green — narrow legacy to adapter.
  NO deletion in Phase 4.5 (tests + settings UI still reference it).
