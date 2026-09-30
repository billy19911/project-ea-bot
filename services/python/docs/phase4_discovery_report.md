# PHASE 4 DISCOVERY REPORT — Entry Engine

## 1. Existing OB Implementation

`trading/entry_zone.py::find_order_blocks(highs, lows, opens, lookback)`:
- WITH opens: classic SMC — last opposite-colour candle before impulse
  (down-candle below price ⇒ bullish OB; up-candle above price ⇒ bearish OB).
  Band = that candle's high/low.
- WITHOUT opens: fallback to recent swing-low/high ±10% range bands.
- Returns `[{type: bullish|bearish, top, bottom, mid}]` (latest only per side).

`agents/analysts/structure_analyst.py::_detect_order_blocks(prices, highs, lows)`:
- Independent implementation: last N-candle opposite move before expansion,
  exposes as `key_levels` entries. Kept separate (analyst evidence vs zone planning).

GAP vs Phase 4 spec (§6–8): existing OB does NOT require displacement magnitude,
structural significance (BOS linkage), timeframe tagging, freshness, invalidation
price, or mitigation history. Band selection is positional, not structural.

## 2. Existing FVG Implementation

`trading/entry_zone.py::find_fair_value_gaps(highs, lows, lookback=15)`:
- Bullish: `lows[i+1] > highs[i-1]` → band (highs[i-1], lows[i+1]); bearish mirror.
- Returns last 5. Pure OHLC relationships — CORRECT per §9.
`structure_analyst._detect_fvg`: same 3-candle rule, returns last 3.

GAP vs Phase 4 spec (§10): no gap_size, no ATR normalization, no displacement
strength, no timeframe/freshness/mitigation/structure_context, no minimum quality
threshold. Every tiny gap is equally valid.

## 3. Existing Setup Representation

`agents/canonical.py::SetupCandidate`: setup_id, assessment_id, symbol, direction,
setup_type, timeframe, entry_context, invalidation (str), target_context,
required/missing/met conditions, supporting/contradicting refs, setup_quality,
status, created_at, expires_at, challenges[].

GAP: no zone object linkage (zone_top/bottom/type), no mitigation state
(FRESH/TOUCHED/MITIGATED/INVALIDATED), no touch_count/retest_count, no
`setup_id` stability scheme (orchestrator derives `setup_<assessment_id>` —
stable per assessment but regenerated per new assessment = per cycle),
no `forbidden_conditions`, no `optional_confirmations`.

## 4. Existing Trigger Logic

NONE as a dedicated engine. What exists:
- `pipeline._zone_entry_plan()`: builds `EntryPlan` via `entry_zone` when price
  is at the zone; returns plan or "waiting" reason. Zone presence ⇒ plan.
- `roles.EntryRole.analyze()`: returns ENTRY_READY only when
  `trigger_confirmed=True` in context; zone touch alone ⇒ WAIT_TRIGGER.
  Nobody currently sets `trigger_confirmed=True` from real detection — the
  interface exists, the detectors do not.
- No rejection/displacement/micro-BOS/momentum-shift/candle-close detectors.

## 5. Existing State Transitions

`trading/signal_state_machine.py`: 12-state machine
(DETECTED→…→WAITING_TRIGGER→EXECUTING→OPEN→MANAGING→CLOSED, REJECTED/EXPIRED
terminals) with `Signal.transition()` validation + history. `ENTRY_READY` is
NOT a signal state — correctly, per §4, readiness lives in
`DecisionState + EntryAssessment` (ENTRY_READY is an assessment status, not a
lifecycle state).

## 6. Existing Timeframe Handling

`entry_zone.build_entry_plan()`: htf_closes (M30/H1 bias) / zone_highs-lows
(M5 zone) / trigger_price (M1 live). Timeframes are CALLER-provided lists —
no timeframe registry, no `TimeframeConfig`. Pipeline `_zone_entry_plan()`
reads `zone_highs/zone_lows` from `analysis_context`. Configurable per call
but scattered (DEFAULT_ZONE_TOLERANCE_ATR etc. module constants).

## 7. Existing Invalidation Logic

- `build_entry_plan`: SL beyond far zone edge; `max_risk_atr` rejects absurd
  stops. Invalidation is IMPLICIT (SL side), not an explicit rule object.
- SetupCandidate.invalidation: free-text string, no price, no close-vs-wick rule.
- No "decisive close beyond boundary" semantics; no per-zone-type invalidation
  rules (OB vs FVG full-fill policy).

## 8. Existing SL/TP Logic

`entry_zone.EntryPlan`: entry=current price (market order), SL=far zone edge,
TP=entry ± rr×risk (DEFAULT_RR=2.0). `pipeline._complete_proposal`:
ATR-based SL/TP via MoneyManager (1.5 ATR SL, TPmax=3R) + spread anchoring.
MoneyManager.calculate_sl_tp: single source of truth (sl_multiplier=1.5,
tp at TPmax=3R). synthesis.py SL_ATR_MULT=1.5/TP_ATR_MULT=4.5 — ALIGNED
(previous "TP terlihat beda" bug fixed).

DOC CHECK (§35): entry_zone comment says "2R" for DEFAULT_RR=2.0 — this is the
ZONE-plan RR default; the ORDER TP is placed at TPmax=3R downstream
(pipeline completion). Two different stages, both documented; verify no test
asserts contradictory RR on the same object.

## 9. Existing Spread Handling

Canonical: `market/account_context` populates spread_price + spread_pips;
gate checks spread_pips ≤ symbol limit (Phase 1 hardening: derives from
bid/ask when missing; unknown/inverted ⇒ fail-closed). Entry path does NOT
re-check spread at trigger time — the gate runs AFTER proposal, so a trigger
could be "confirmed" on a wide-spread tick and only rejected later at the gate.
Phase 4 §30 requires an execution-filter spread check INSIDE trigger evaluation.

## 10. Existing ATR/Volatility Handling

`indicators.atr(highs, lows, closes, period)` canonical; pipeline resolves ATR
via `extract_price_atr(context)`; entry_zone uses atr for risk-width guard,
zone tolerance/proximity/trigger windows. No "ATR too low/high" trigger-validity
filter; no abnormal-spike detector in the entry path (volatility role exists in
committee but is not consulted by the zone gate).

## 11. Existing Candle-Close Semantics

NO explicit CANDLE_OPEN/FORMING/CLOSED distinction anywhere in the entry path.
`trigger_price` is a live scalar; `build_entry_plan` treats it as executable
now. EntryRole has no `candle_closed` input. A forming-candle trigger would be
accepted as readily as a closed one — Phase 4 §19 must add this.

## 12. Existing Event Dispatch

`agents/event_dispatch.py`: ZONE_TOUCH→(entry,structure) LEVEL_ENTRY;
TRIGGER_APPROACHING→entry; MICRO_BOS/DISPLACEMENT/REJECTION/CANDLE_CLOSE are
NOT first-class event types (no dispatch entries). SETUP_INVALIDATED/
SETUP_EXPIRED → deterministic-only. The orchestrator's entry gate consumes
ZONE_TOUCH; nothing emits MICRO_BOS etc.

## 13. Existing Tests

test_entry_zone.py (plan/bias/zones/gate), test_zone_classification.py,
test_entry_completion.py, test_entry_context_bridge.py,
test_entry_cooldown_guard.py, Phase 3 entry tests (EntryRole interface).
NO tests for rejection/displacement/micro-BOS/momentum-shift/candle-close
detectors (they don't exist), no invalidation/expiry/retest-lifecycle tests,
no multi-timeframe contradiction tests, no no-future-leakage tests.

## 14. Duplicate/Legacy Entry Paths

| Path | Status |
|------|--------|
| pipeline → `_zone_entry_plan` → `entry_zone.build_entry_plan` | LIVE path (F2 gate, operator toggle) |
| pipeline → `_complete_proposal` (ATR SL/TP + sizing) | LIVE path (always on) |
| `ZoneEntryGate.evaluate` (pending memory) | LIVE when gate wired (runtime wires it) |
| supervisor synthesis target_sl/target_tp | ADVISORY (pipeline overwrites via completion; never direct to broker) |
| `mt5/endpoints /orders/execute` | PAPER-ONLY (simulation path, no live broker) |
| `mt5/write_guard.send_order` | PAPER-ONLY guard path |
| `demo/demo_trading.py` | DEMO harness (own engine instance) |

All live-trading paths funnel through pipeline → RiskGate → ExecutionEngine.
No legacy path bypasses the gate for live orders.

## 15. Recommended Integration Points

1. `trading/entry_zone.py`: EXTEND (don't replace) — add displacement/quality
   metadata to `find_order_blocks`/`find_fair_value_gaps` returns (back-compat:
   keep {type,top,bottom,mid} keys, add optional keys).
2. NEW `trading/trigger_engine.py`: pure-function detectors
   (rejection/displacement/micro-BOS/momentum-shift/candle-close) over injected
   OHLC lists + config; returns TriggerEvidence list. No I/O, no MT5.
3. NEW `trading/entry_lifecycle.py` (or extend canonical.SetupCandidate):
   zone registry with stable setup_id, mitigation states, touch/retest counts,
   invalidation/expiry evaluation, idempotency keys.
4. `agents/roles.py::EntryRole`: consume trigger engine output
   (`trigger_confirmed` becomes detector-driven, not caller-asserted).
5. `agents/event_dispatch.py`: add MICRO_BOS/DISPLACEMENT/REJECTION/
   CANDLE_CLOSE/TRIGGER_CANDIDATE/SETUP_EXPIRED dispatch entries (targeted).
6. `orchestration/pipeline.py::_zone_entry_plan`: insert trigger evaluation
   between "price at zone" and "return plan" (zone touch ⇒ WAIT_TRIGGER until
   trigger engine confirms).
7. `trading/signal_state_machine.py`: NO new states; ENTRY_READY stays an
   EntryAssessment status (per §4 preference).
8. `agents/canonical.py::EntryAssessment`: EXTEND with §23 fields
   (triggers_detected, satisfied/missing/blocking conditions, trigger
   time/price, zone metadata) — back-compat defaults.
