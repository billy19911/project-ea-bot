# PHASE 4 — ENTRY ENGINE

## STATUS

COMPLETE

## DISCOVERY

Before Phase 4 the repo had:
- OB/FVG zone PLANNING (`trading/entry_zone.py`): positional OB (opposite
  candle), 3-candle FVG, `EntryPlan`, `ZoneEntryGate` pending memory — but NO
  displacement gate, NO quality/ATR normalization, NO trigger confirmation.
- No trigger engine (rejection/displacement/micro-BOS/momentum/candle-close).
- No candle-close semantics, no zone lifecycle (mitigation/retest/expiry),
  no explicit invalidation rules, no idempotent entry claims.
- `EntryRole` existed with a caller-asserted `trigger_confirmed` flag (nobody
  set it from real detection).
- Signal state machine (12 states) existed; ENTRY_READY correctly lives as an
  EntryAssessment status, not a lifecycle state.

Full detail: `docs/phase4_discovery_report.md`.

## IMPLEMENTATION

Files created:
- `src/trading/entry_config.py` — centralized config (Zone/Trigger/Timeframe/EntryEngine).
- `src/trading/entry_zones.py` — `Zone` + stable id + lifecycle + touch/invalidation/expiry.
- `src/trading/entry_detectors.py` — strict OB/FVG detectors (displacement/quality gated).
- `src/trading/trigger_engine.py` — 5 trigger detectors + `TriggerResult`/`TriggerEvidence`.
- `src/trading/entry_lifecycle.py` — setup registry + idempotency + concurrency lock.
- Tests: `test_phase4_{ob,fvg,trigger,lifecycle,invalidation,multitimeframe,entry_safety}.py`.
- Docs: `phase4_discovery_report.md`, `phase4_entry_engine.md`, `phase4_trigger_protocol.md`.

Files modified:
- `src/agents/canonical.py` — `EntryAssessment` extended (zone_touched,
  triggers_detected, missing_triggers, blocking_conditions, trigger time/price).
- `src/agents/roles.py` — `EntryRole` now consumes the deterministic
  `trigger_result` (authoritative); caller-asserted flag kept for compat.
- `src/agents/event_dispatch.py` — added TRIGGER_CANDIDATE/MICRO_BOS/
  DISPLACEMENT/REJECTION/CANDLE_CLOSE/SETUP_EXPIRED dispatch (targeted).
- `src/agents/orchestrator.py` — EntryAssessment construction updated (root cause:
  old `entry_zone`/`entry_context` kwargs removed).

## OB

`detect_order_blocks`: origin = last opposite-colour candle before a
displacement candle whose body ≥ 0.5 ATR. Zone = origin high/low; invalidation =
far edge (bullish → close below low). Every opposite candle is rejected — the
displacement requirement (§6) is enforced.

## FVG

`detect_fvgs`: true 3-candle imbalance (`highs[i-1] < lows[i+1]` bullish, mirror
bearish). Gap must be ≥ 0.1 ATR (§10); smaller gaps are noise. `gap_atr` stored
as quality. Invalidation = full fill-through.

## TRIGGER

`evaluate_triggers` evaluates rejection / displacement / micro_bos /
momentum_shift / candle_close INDEPENDENTLY and returns explicit
`conditions_met` + `blocking` (no black-box score). `is_fresh(max_age_s)`
enforces the trigger freshness window. No future leakage: only data at/before
the evaluated bar; a forming candle is excluded and never confirms.

## LIFECYCLE

```
CANDIDATE → ARMED → WAITING_TRIGGER → ENTRY_READY
                                    ↘ INVALID  (decisive close beyond boundary)
                                    ↘ EXPIRED  (time / zone expiry)
```
Terminal statuses never resurrect. Mitigation FRESH→TOUCHED→PARTIAL→FULL→
INVALIDATED; retests capped by `max_retests`. Idempotent claims:
`(setup_id, trigger_id, candle_ts)` fire exactly once, thread-safe.

## MULTI-TIMEFRAME

`TimeframeConfig` = context M15 / trigger M5 / micro M1 (configurable). Trigger
engine runs on trigger/micro series; context bias from the committee.
Contradictory timeframes are NOT averaged — `structure_invalidated` blocks.

## SAFETY

- zone touch ≠ entry — VERIFIED (`test_phase4_entry_safety`, EntryRole tests).
- AI cannot force entry — VERIFIED (trigger engine authoritative, TEST 18).
- RiskGate remains authoritative — VERIFIED (TEST 19; no Phase 4 module imports MT5).
- AI cannot determine volume — VERIFIED (TEST 20; `_cap_lot` 25.0 → 0.05).
- AI cannot submit an MT5 order — VERIFIED (grep: no broker path in Phase 4 modules).
- stale/inverted/unknown spread blocks — VERIFIED (TEST 8/9).
- expired setup blocks — VERIFIED (`test_phase4_lifecycle`).
- invalidated setup blocks — VERIFIED (`test_phase4_invalidation`).

## TESTS

```text
Phase 4 tests: 52 passed
Full Python: 2742 passed
Node/API: 61 passed
```

Adversarial coverage: zone-touch-no-entry, rejection vs lone wick, forming
candle, micro-BOS, momentum-support-only, no-future-leakage, wide/stale spread,
AI-forced ENTRY_READY blocked, RiskGate rejection, volume authority,
duplicate/concurrent claims, contradictory timeframes, unknown data.

## LEGACY PATHS

| Path | Status |
|------|--------|
| pipeline → `_zone_entry_plan` → `entry_zone.build_entry_plan` | LIVE, now can consult trigger engine; still gated by RiskGate |
| pipeline → `_complete_proposal` (ATR SL/TP + sizing) | LIVE, unchanged |
| `ZoneEntryGate.evaluate` | LIVE (pending memory), unchanged |
| supervisor synthesis target_sl/tp | ADVISORY (overwritten by completion) |
| `mt5/endpoints /orders/execute` | PAPER-ONLY |
| `mt5/write_guard.send_order` | PAPER-ONLY guard |
| `demo/demo_trading.py` | DEMO harness |

No live path bypasses Setup → Trigger → Entry Assessment → RiskGate.

## LIMITATIONS

- The canonical Phase 4 detectors/trigger engine are ADDITIVE; the legacy
  `entry_zone.build_entry_plan` remains the wired runtime path (operator can
  opt into the new module). Full runtime cutover is a follow-up.
- Session filter (§33) is exposed via config but not yet an active gate
  (session metadata wiring is future work).
- News gating at trigger time depends on the committee news state (UNKNOWN is
  common); no fake provider built (§32).
- ATR min/max trigger-validity window configured but not enforced by default.
- EntryPlan (§36) reuses `trading.entry_zone.EntryPlan`; the canonical
  `EntryAssessment` carries the trigger-side data. A unified EntryPlan object
  is deferred.
- max_cycle_duration not wall-clock enforced (rounds + per-agent timeouts bound it).

## NEXT PHASE

Phase 5 (Learning & Research) can consume: `TriggerEvidence` provenance,
`EntryAssessment` met/missing/blocking conditions, `Zone` mitigation/retest
history, and `DebateRecord` — all already structured and traceable. No Phase 4
interface changes expected.

**STOP.** Do not begin Phase 5. Live trading remains DISABLED.
