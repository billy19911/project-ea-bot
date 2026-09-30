# Phase 4.5 — Canonical Runtime Architecture

## Authoritative path (after cutover)

```
MARKET EVENT
  → pipeline.run()
  → supervisor.analyze() → proposal {symbol, direction, confidence...}
  → _complete_proposal (deterministic ATR SL/TP + sizing + _cap_lot)
  → RiskGate.validate_proposal → approved?
  → B6 _zone_entry_plan (if zone_entry_enabled):
       1. ZoneEntryGate.evaluate → legacy zone plan (levels ONLY, advisory)
       2. _evaluate_canonical_trigger → Trigger Engine (AUTHORITATIVE)
       3. plan WITHOUT trigger confirmation → WAIT (no overwrite, no execute)
       4. plan WITH confirmation → attach trigger_assessment, overwrite SL/TP
  → _build_order_request → approval_token → ExecutionEngine → MT5
  → reconciliation
```

## Why this shape

The pipeline is the single orchestration path (no parallel canonical pipeline).
The canonical Trigger Engine is injected at the ONE decision point that used
to be authoritative on zone proximity alone (B6). Everything downstream
(RiskGate → MoneyManager → order builder → ExecutionEngine) is untouched.

## EntryAssessment contract (§2)

`agents.canonical.EntryAssessment` carries: setup_id, direction, zone_type,
zone_id, trigger_id/type, trigger_confirmed, required/satisfied (detected) /
missing / blocking conditions, trigger + evaluation timestamps, fresh/expired/
invalidated flags, mitigation_state, retest_count, timeframe triple
(context/trigger/micro), evidence_refs, reason_codes.

Built ONLY by `trading.entry_adapter.adapt_trigger_to_assessment` from a
`TriggerResult` (+ Zone + lifecycle status). No other constructor path sets
`trigger_confirmed=True`.

## State machine (§5)

DETECTED → ANALYZING → CANDIDATE → VALIDATED → ARMED → WAITING_TRIGGER →
ENTRY_READY → EXECUTING → OPEN → MANAGING → CLOSED, with REJECTED/EXPIRED/
INVALID terminals. EXECUTING only from ENTRY_READY/WAITING_TRIGGER per the
existing `signal_state_machine` + canonical `DecisionState` transitions —
unchanged by Phase 4.5.

## Idempotency (§11)

Two layers, both kept:
- `EntryLifecycleManager.claim_entry(setup_id, trigger_id, candle_ts)` —
  canonical trigger-level idempotency (thread-safe).
- `ExecutionEngine` idempotency keys + durable ledger — execution-level
  (unchanged).

## Error handling (§16)

Trigger evaluation error → `(False, reason, {})` → pipeline WAITs with a
reason. Legacy zone levels are NEVER used as a fallback execution path.

## Dispatch (§12)

ZONE_TOUCH / TRIGGER_CANDIDATE / MICRO_BOS / DISPLACEMENT / REJECTION /
CANDLE_CLOSE → LEVEL_ENTRY targeted (entry role only). SETUP_INVALIDATED /
SETUP_EXPIRED → deterministic lifecycle. No full committee on M1 ticks
(unchanged Phase 3 behavior).
