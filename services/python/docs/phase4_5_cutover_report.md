# Phase 4.5 — Cutover Report

## 1. Before

```
pipeline B6 → ZoneEntryGate.evaluate → entry_zone.build_entry_plan
  → zone found & price at zone ⇒ OVERWRITE entry/SL/TP ⇒ execute
```
Zone proximity alone was authoritative for entry levels. No trigger
confirmation (rejection/displacement/micro-BOS/momentum/candle-close) between
"price at zone" and "execute". The canonical orchestrator + Trigger Engine from
Phase 2–4 existed but were DORMANT in production (unit-tested only).

## 2. After

```
pipeline B6 → legacy zone plan (levels only, advisory)
  → _evaluate_canonical_trigger (Trigger Engine, AUTHORITATIVE)
  → no confirmation ⇒ WAIT (None + reason, no overwrite, no execute)
  → confirmation ⇒ attach trigger_assessment + overwrite SL/TP
```

The Trigger Engine is the sole authority for trigger confirmation. Zone presence
no longer executes.

## 3. Files changed

- `src/agents/canonical.py` — EntryAssessment extended with Phase 4.5 contract
  fields (zone_id, trigger_id/type, trigger_confirmed, evaluation_ts,
  fresh/expired/invalidated, mitigation_state, retest_count, timeframe triple,
  evidence_refs, reason_codes).
- `src/orchestration/pipeline.py` — `_evaluate_canonical_trigger` added;
  `_zone_entry_plan` now gates legacy plan behind it; shadow comparator
  `_last_shadow_verdicts` recorded; `__init__` initializes it.
- `src/agents/orchestrator.py` — `_evaluate_entry_triggers` added; Level 4
  EntryRole now receives the deterministic `trigger_result`.

## 4. Files added

- `src/trading/entry_adapter.py` — TriggerResult → EntryAssessment (single
  direction; fail-closed).
- `tests/test_phase4_5_cutover.py` — 19 tests (A–L + adversarial Cases 1–7).
- Docs: `phase4_5_discovery_report.md`, `phase4_5_runtime_architecture.md`,
  this file.

## 5. Legacy paths retained (compatibility / read-only)

- `trading.entry_zone.build_entry_plan` — still computes zone levels; NO longer
  authoritative for entry (gated by trigger).
- `ZoneEntryGate` — kept as the runtime pending-memory + plan provider.
- `pipeline._complete_proposal` — deterministic SL/TP/size completion (not a
  bypass; runs before the gate).
- `EntryRole(trigger_confirmed=...)` legacy caller flag — kept for compat;
  `trigger_result` overrides it (locked by test_phase4_entry_safety +
  test_phase4_5_cutover K).

## 6. Legacy paths de-authorized

- `_zone_entry_plan` legacy zone plan: authority moved to the trigger gate.
  A plan without trigger confirmation returns `None` (WAIT).
- No legacy path can produce ENTRY_READY: only `entry_adapter` sets
  `trigger_confirmed=True`, driven by the Trigger Engine.

## 7. Adapter decisions

- A1 (zone-plan trigger gate): implemented inside `_zone_entry_plan` — smallest
  risk, one seam, no parallel pipeline.
- A2 (EntryRole precedence): already deterministic-first; locked by test.
- A3 (proposal→orchestrator bridge): the orchestrator consumes the SAME
  context shape the pipeline uses; no second pipeline activated.

## 8. State-machine integration

Unchanged. `signal_state_machine` (12 states) + `DecisionState` transitions are
intact; EXECUTING remains reachable only via ENTRY_READY/WAITING_TRIGGER.

## 9. Trigger Engine integration

`evaluate_triggers` (Phase 4) is called from `_evaluate_canonical_trigger`
(pipeline) and `_evaluate_entry_triggers` (orchestrator). Both fail-closed.

## 10. Idempotency

`EntryLifecycleManager.claim_entry(setup_id, trigger_id, candle_ts)` — exactly
one True across 8/20 concurrent threads (tested). ExecutionEngine ledger
unchanged.

## 11. Error handling

Trigger error → WAIT + reason. No fallback to legacy execution. Verified by
`test_adv_case4_trigger_crash_no_fallback_execution` and G.

## 12. Regression results

```
Phase 4.5 tests: 19 passed
Full Python: 2761 passed (1 flaky unrelated endpoint test passed on re-run)
Node/API: 61 passed
```

## 13. Safety verification

| Invariant | Status |
|-----------|--------|
| 1 AI cannot create MT5 order | VERIFIED (no broker path in Phase 4.5 code) |
| 2 AI cannot choose volume | VERIFIED (`_cap_lot` unchanged; 25.0→0.05) |
| 3 RiskGate authoritative | VERIFIED (J; unchanged gate) |
| 4 Trigger Engine authoritative | VERIFIED (adapter is sole ENTRY_READY source) |
| 5 Zone touch ≠ entry | VERIFIED (B; pipeline returns None on touch-only) |
| 6 Expired setup cannot trade | VERIFIED (E, Case 6) |
| 7 Invalidated setup cannot trade | VERIFIED (D, Case 7) |
| 8 UNKNOWN ≠ confirmation | VERIFIED (fail-closed adapter) |
| 9 Trigger failure ≠ fallback exec | VERIFIED (G, Case 4) |
| 10 Duplicate ≠ duplicate execution | VERIFIED (H, I, Case 5) |
| 11 No majority vote authoritative | VERIFIED (static audit) |
| 12 DecisionState authoritative | VERIFIED (unchanged) |
| 13 No full committee on M1 | VERIFIED (dispatch unchanged) |
| 14 No future candle leakage | VERIFIED (Phase 4 test retained) |
| 15 Live trading DISABLED | VERIFIED (simulation/armed-terminal guards intact) |

## 12. Remaining technical debt

- The legacy `entry_zone.build_entry_plan` remains a level provider; a future
  phase can replace its output with canonical Zone levels.
- The orchestrator remains additive (not the pipeline's default synthesis
  backend); full unification is deferred.
- Session filter / ATR min-max windows remain configured-but-inactive (per
  §19–§20: not activated in Phase 4.5).
- `EntryPlan` (legacy) and canonical `EntryAssessment` coexist; a unified plan
  object is future work.

## 13. Shadow comparison

The pipeline records `_last_shadow_verdicts[symbol] = {legacy, canonical,
verdict, reason}` every zone-plan cycle (MATCH / CONFLICT) — observability
only, never a decision input. Verified by `test_shadow_verdict_recorded`.

**STOP.** Live trading remains DISABLED. Do not begin Phase 5.
